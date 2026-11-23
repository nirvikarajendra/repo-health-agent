"""Run the eval cases against the real agent and score each answer.

    uv run python -m repo_health.evals.run --runs 3
    uv run python -m repo_health.evals.run --cases 1,10 --runs 1

Calls Gemini (needs GOOGLE_API_KEY and GEMINI_MODEL in .env). Results are saved to
evals-results/YYYY-MM-DD-HHMMSS.json.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google.adk.events.event import Event
from google.adk.runners import InMemoryRunner
from google.genai import errors, types

from repo_health.agent.build import build_agent
from repo_health.config import get_settings
from repo_health.evals.scoring import Check, load_cases, score

RESULTS_DIR = Path("evals-results")
# Free tier: 15 Gemini requests per minute, so one every 4 seconds.
SECONDS_PER_REQUEST = 4
USER_ID = "eval"


def extract_turn(events: list[Event]) -> tuple[list[dict], list[dict], str]:
    """Turn one question's ADK events into (tool_calls, tool_results, answer).

    Calls and results keep their order, so tool_results[i] is what tool_calls[i] returned.
    The answer is the text of the final response, without the model's thought parts.
    """
    tool_calls, tool_results, texts = [], [], []
    for event in events:
        for function_call in event.get_function_calls():
            tool_calls.append({"name": function_call.name, "args": dict(function_call.args or {})})
        for function_response in event.get_function_responses():
            tool_results.append(dict(function_response.response or {}))
        if event.is_final_response() and event.content and event.content.parts:
            texts += [part.text for part in event.content.parts if part.text and not part.thought]
    return tool_calls, tool_results, "".join(texts).strip()


def ask(runner: InMemoryRunner, question: str) -> tuple[list[Event], int]:
    """Ask one question in a fresh session. Returns its events and how many Gemini requests."""
    session = runner.session_service.create_session_sync(app_name=runner.app_name, user_id=USER_ID)
    message = types.Content(role="user", parts=[types.Part(text=question)])
    events = list(runner.run(user_id=USER_ID, session_id=session.id, new_message=message))
    # Each event written by the agent (not a tool result) is one model response.
    model_requests = sum(
        1
        for event in events
        if event.author != "user" and event.content and not event.get_function_responses()
    )
    return events, max(model_requests, 1)


def check_answer(
    case: dict, tool_calls: list[dict], tool_results: list[dict], answer: str
) -> list[dict]:
    """The scoring checks, plus a failed "answer" check if the answer is empty."""
    checks = score(case, tool_calls, tool_results, answer)
    if not answer:
        checks.append(Check(name="answer", passed=False, reason="empty answer"))
    return [check.model_dump() for check in checks]


def run_case(runner: InMemoryRunner, case: dict, run: int) -> tuple[dict, int]:
    events, requests = ask(runner, case["question"])
    tool_calls, tool_results, answer = extract_turn(events)
    result = {
        "case_id": case["id"],
        "run": run,
        "question": case["question"],
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "answer": answer,
        "checks": check_answer(case, tool_calls, tool_results, answer),
    }
    return result, requests


def rescore(path: Path) -> tuple[list[dict], list[dict]]:
    """Re-score a saved results file with the current cases and checks. No Gemini calls.

    Returns (cases, results) for print_summary; the file itself is not changed.
    """
    saved = json.loads(path.read_text())["results"]
    cases_by_id = {case["id"]: case for case in load_cases()}
    results = []
    for result in saved:
        case = cases_by_id.get(result["case_id"])
        if case is None:
            print(f"skipping case {result['case_id']}: no longer in cases.json")
            continue
        checks = check_answer(case, result["tool_calls"], result["tool_results"], result["answer"])
        results.append(result | {"checks": checks})
    case_ids = {result["case_id"] for result in results}
    return [case for case in cases_by_id.values() if case["id"] in case_ids], results


def print_summary(cases: list[dict], results: list[dict]) -> None:
    print(f"\n{'case':<5} {'question':<45} {'runs':<20} failed checks")
    for case in cases:
        runs = [result for result in results if result["case_id"] == case["id"]]
        if not runs:
            continue
        scores = " ".join(
            f"{sum(c['passed'] for c in r['checks'])}/{len(r['checks'])}" for r in runs
        )
        failed = ", ".join(
            f"{check['name']} (run {r['run']})"
            for r in runs
            for check in r["checks"]
            if not check["passed"]
        )
        question = case["question"][:44]
        print(f"{case['id']:<5} {question:<45} {scores:<20} {failed}")

    checks = [check for result in results for check in result["checks"]]
    passed = sum(check["passed"] for check in checks)
    percent = 100 * passed / len(checks) if checks else 0.0
    case_ids = {result["case_id"] for result in results}
    perfect = sum(
        all(check["passed"] for r in results if r["case_id"] == case_id for check in r["checks"])
        for case_id in case_ids
    )
    print(f"\nChecks passed: {passed}/{len(checks)} ({percent:.1f}%).", end=" ")
    print(f"Cases passing every run: {perfect}/{len(case_ids)}.")


def save(output: dict) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{datetime.now():%Y-%m-%d-%H%M%S}.json"
    path.write_text(json.dumps(output, indent=2))
    return path


def main() -> None:
    # Gemini reads GOOGLE_API_KEY from the environment; adk web/run load .env, plain python doesn't.
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the eval cases against the agent.")
    parser.add_argument("--runs", type=int, default=1, help="times to ask each question")
    parser.add_argument("--cases", help="comma-separated case ids, e.g. 1,10 (default: all)")
    parser.add_argument(
        "--rescore", type=Path, help="re-score a saved results file with the current checks"
    )
    args = parser.parse_args()

    if args.rescore:  # No Gemini calls, nothing saved.
        print_summary(*rescore(args.rescore))
        return

    cases = load_cases()
    if args.cases:
        wanted = {int(case_id) for case_id in args.cases.split(",")}
        cases = [case for case in cases if case["id"] in wanted]

    model = get_settings().gemini_model
    runner = InMemoryRunner(agent=build_agent(model))
    output = {
        "model": model,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "runs": args.runs,
        "stopped_early": None,
        "results": [],
    }
    try:
        for run in range(1, args.runs + 1):
            for case in cases:
                print(f"run {run}, case {case['id']}: {case['question']}")
                result, requests = run_case(runner, case, run)
                output["results"].append(result)
                time.sleep(SECONDS_PER_REQUEST * requests)  # Stay under 15 requests/minute.
    # KeyboardInterrupt is listed because Ctrl+C is not an Exception subclass.
    except (Exception, KeyboardInterrupt) as error:
        if isinstance(error, errors.APIError) and error.code == 429:
            # ADK adds a long "possible fix" text to the message; the code and status are enough.
            output["stopped_early"] = f"Gemini quota reached: {error.code} {error.status}"
            print("\nGemini quota reached (429), stopping. Saving what we have.")
        else:
            output["stopped_early"] = f"{type(error).__name__}: {error}"
            raise  # Show the traceback, after the finally block has saved the results.
    finally:
        print_summary(cases, output["results"])
        print(f"\nSaved {save(output)}")
    if output["stopped_early"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
