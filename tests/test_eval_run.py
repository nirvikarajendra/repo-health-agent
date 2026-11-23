import json

from google.adk.events.event import Event
from google.genai import types

from repo_health.evals.run import extract_turn, rescore

AGENT = "repo_health_agent"


def model_event(*parts: types.Part) -> Event:
    return Event(author=AGENT, content=types.Content(role="model", parts=list(parts)))


def tool_event(*parts: types.Part) -> Event:
    return Event(author=AGENT, content=types.Content(role="user", parts=list(parts)))


def call(name: str, **args) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


def response(name: str, result: dict) -> types.Part:
    return types.Part(function_response=types.FunctionResponse(name=name, response=result))


def text(value: str, thought: bool = False) -> types.Part:
    return types.Part(text=value, thought=thought or None)


def test_one_tool_call_then_answer():
    result = {"status": "success", "stars": 15652}
    events = [
        model_event(call("get_repo_overview", repo="encode/httpx")),
        tool_event(response("get_repo_overview", result)),
        model_event(text("encode/httpx has 15,652 stars.")),
    ]

    tool_calls, tool_results, answer = extract_turn(events)

    assert tool_calls == [{"name": "get_repo_overview", "args": {"repo": "encode/httpx"}}]
    assert tool_results == [result]
    assert answer == "encode/httpx has 15,652 stars."


def test_parallel_calls_keep_their_order():
    # A health question: several calls in one model turn, results in the same order.
    events = [
        model_event(call("get_repo_overview", repo="o/r"), call("get_release_cadence", repo="o/r")),
        tool_event(
            response("get_repo_overview", {"stars": 1}),
            response("get_release_cadence", {"latest_release_tag": "v1"}),
        ),
        model_event(text("Done.")),
    ]

    tool_calls, tool_results, _ = extract_turn(events)

    assert [c["name"] for c in tool_calls] == ["get_repo_overview", "get_release_cadence"]
    assert tool_results == [{"stars": 1}, {"latest_release_tag": "v1"}]


def test_thought_parts_are_not_in_the_answer():
    events = [model_event(text("I should check the date.", thought=True), text("1 repo."))]

    assert extract_turn(events)[2] == "1 repo."


def test_no_final_text_gives_an_empty_answer():
    events = [
        model_event(call("list_repos")),
        tool_event(response("list_repos", {"status": "success", "repos": []})),
    ]

    tool_calls, tool_results, answer = extract_turn(events)

    assert (len(tool_calls), len(tool_results), answer) == (1, 1, "")


def test_rescore_uses_the_current_checks_and_leaves_the_file_alone(tmp_path):
    # Case 9, run 3 as saved: it failed "refusal" under the old checks.
    saved = {
        "results": [
            {
                "case_id": 9,
                "run": 3,
                "question": "What's fastapi's bug close rate over the last 10 days?",
                "tool_calls": [{"name": "get_bug_close_rate", "args": {"days": 10}}],
                "tool_results": [
                    {"status": "error", "error_message": "days must be 31-365, got 10"}
                ],
                "answer": "I don't know because the window length of days must be between"
                " 31 and 365.",
                "checks": [{"name": "refusal", "passed": False, "reason": "old"}],
            },
            {"case_id": 99, "run": 1, "tool_calls": [], "tool_results": [], "answer": ""},
        ]
    }
    path = tmp_path / "results.json"
    path.write_text(json.dumps(saved))

    cases, results = rescore(path)

    assert [case["id"] for case in cases] == [9]  # Case 99 is no longer in cases.json.
    assert all(check["passed"] for check in results[0]["checks"]), results[0]["checks"]
    assert json.loads(path.read_text()) == saved
