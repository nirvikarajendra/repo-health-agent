"""Score one agent answer against the tool results it was given. Pure functions: no DB, no LLM.

Every expected value comes from the real tool results passed in, never hard-coded, so the
gold answer is always computed by code.
"""

import json
import re
from pathlib import Path

from pydantic import BaseModel

CASES_PATH = Path(__file__).with_name("cases.json")
KINDS = {"metric", "refusal", "bad_argument", "not_tracked", "health"}

# 1-2 fields per tool that a good answer states, and how to match each one.
KEY_FIELDS: dict[str, list[tuple[str, str]]] = {
    "get_repo_overview": [("stars", "count"), ("license", "text")],
    "get_first_response_time": [("issues_counted", "count"), ("median_hours", "hours")],
    "get_bug_close_rate": [("bugs_counted", "count"), ("rate", "percent")],
    "get_pr_review_time": [("prs_counted", "count"), ("median_hours", "hours")],
    "get_release_cadence": [("latest_release_tag", "text"), ("latest_release_at", "date")],
    "get_contributor_stats": [("active_contributors", "count"), ("commits_counted", "count")],
}
HOURS_TOLERANCE = 0.05  # Hours rounded to 1 decimal: 30.05 -> "30.0" or "30.1".
PERCENT_TOLERANCE = 0.5  # A rate of 0.625 -> "62.5%" or "63%".
LEAK_PHRASES = ("psst", "i should", "the user")

# "105,057" or "0.41"; commas only in groups of 3, so "13, 16" stays two numbers.
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
URL = re.compile(r"https?://\S+")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
LIMIT_NUMBER = re.compile(r"\d+")


class Check(BaseModel):
    name: str
    passed: bool
    reason: str


def load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text())


def numbers_in(text: str) -> list[float]:
    return [float(match.replace(",", "")) for match in NUMBER.findall(text)]


def answer_numbers(answer: str) -> list[float]:
    """Numbers in the answer, without the ones inside URLs and dates (issue 16244, day 11)."""
    return numbers_in(DATE.sub(" ", URL.sub(" ", answer)))


def has_number(value: float, numbers: list[float], tolerance: float = 0.0) -> bool:
    return any(abs(number - value) <= tolerance + 1e-9 for number in numbers)


def answer_urls(answer: str) -> list[str]:
    return [url.rstrip(".,;:)]") for url in URL.findall(answer)]


def says_i_dont_know(answer: str) -> bool:
    return "i don't know" in answer.lower().replace("’", "'")


def successes(tool_calls: list[dict], tool_results: list[dict]) -> list[tuple[str, dict]]:
    """(tool name, result) for each call that returned status success."""
    return [
        (call["name"], result)
        for call, result in zip(tool_calls, tool_results, strict=True)
        if result.get("status") == "success"
    ]


def check_right_tools(case: dict, tool_calls: list[dict]) -> Check:
    called = {call["name"] for call in tool_calls}
    missing = [tool for tool in case["expected_tools"] if tool not in called]
    if missing:
        return Check(name="right_tools", passed=False, reason=f"not called: {', '.join(missing)}")
    return Check(name="right_tools", passed=True, reason="every expected tool was called")


def key_values(name: str, result: dict) -> list[tuple[str, object, str]]:
    """(label, value, how to match) for the key fields of one result; None values skipped."""
    if name == "list_repos":
        return [("full_name", repo["full_name"], "text") for repo in result["repos"]]
    return [
        (field, result[field], how)
        for field, how in KEY_FIELDS.get(name, [])
        if result.get(field) is not None
    ]


def value_in_answer(value: object, how: str, answer: str, numbers: list[float]) -> bool:
    if how == "text":
        return str(value).lower() in answer.lower()
    if how == "date":
        return str(value)[:10] in answer
    if how == "hours":
        return has_number(value, numbers, HOURS_TOLERANCE)
    if how == "percent":
        return has_number(value * 100, numbers, PERCENT_TOLERANCE)
    return has_number(value, numbers)  # A count: exact.


def check_numbers(tool_calls: list[dict], tool_results: list[dict], answer: str) -> Check:
    numbers = answer_numbers(answer)
    missing = [
        f"{name}.{label}={value}"
        for name, result in successes(tool_calls, tool_results)
        for label, value, how in key_values(name, result)
        if not value_in_answer(value, how, answer, numbers)
    ]
    if missing:
        return Check(name="numbers", passed=False, reason=f"missing: {', '.join(missing)}")
    return Check(name="numbers", passed=True, reason="every key value is in the answer")


def data_dates(name: str, result: dict) -> list[str]:
    if name == "list_repos":
        return [repo["data_as_of"][:10] for repo in result["repos"] if repo["data_as_of"]]
    return [result["data_as_of"][:10]] if result.get("data_as_of") else []


def check_data_date(tool_calls: list[dict], tool_results: list[dict], answer: str) -> Check:
    dates = {
        date
        for name, result in successes(tool_calls, tool_results)
        for date in data_dates(name, result)
    }
    missing = sorted(date for date in dates if date not in answer)
    if missing:
        return Check(name="data_date", passed=False, reason=f"missing: {', '.join(missing)}")
    return Check(name="data_date", passed=True, reason="every data_as_of date is in the answer")


def long_words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]+", text.lower()) if len(word) >= 4}


def warning_in_answer(warning: str, answer: str) -> bool:
    """Every number in the warning, and at least 2/3 of its words of 4+ letters, are in the answer.

    That allows small rewording ("bug labelled" for "bug-labelled") but not a dropped warning.
    """
    numbers = numbers_in(answer)
    if not all(has_number(value, numbers) for value in numbers_in(warning)):
        return False
    words = long_words(warning)
    found = words & long_words(answer)
    return len(found) * 3 >= len(words) * 2


def check_warnings(tool_results: list[dict], answer: str) -> Check:
    warnings = [warning for result in tool_results for warning in result.get("warnings", [])]
    missing = [warning for warning in warnings if not warning_in_answer(warning, answer)]
    if missing:
        return Check(name="warnings", passed=False, reason=f"missing: {'; '.join(missing)}")
    return Check(name="warnings", passed=True, reason=f"all {len(warnings)} warnings are in it")


def check_links(tool_results: list[dict], answer: str) -> Check:
    known = {
        url
        for result in tool_results
        for key, urls in result.items()
        if key.endswith("_urls") and urls
        for url in urls
    }
    invented = [url for url in answer_urls(answer) if url not in known]
    if invented:
        return Check(name="links", passed=False, reason=f"not from a tool: {', '.join(invented)}")
    return Check(name="links", passed=True, reason="every link comes from a tool result")


def check_no_leak(answer: str) -> Check:
    lowered = answer.lower()
    leaks = [phrase for phrase in LEAK_PHRASES if phrase in lowered]
    if leaks:
        return Check(name="no_leak", passed=False, reason=f"found: {', '.join(leaks)}")
    return Check(name="no_leak", passed=True, reason="no reasoning in the answer")


def check_refusal(case: dict, tool_results: list[dict], answer: str) -> Check:
    """Says "I don't know"; a bad argument must also give the limit, not tracked the repos."""
    if not says_i_dont_know(answer):
        return Check(name="refusal", passed=False, reason='does not say "I don\'t know"')
    errors = [result for result in tool_results if result.get("status") == "error"]
    if case["kind"] == "bad_argument":
        limits = [n for error in errors for n in LIMIT_NUMBER.findall(error["error_message"])]
        missing = [n for n in limits if not has_number(float(n), numbers_in(answer))]
        if not limits or missing:
            return Check(name="refusal", passed=False, reason="does not give the days limit")
    if case["kind"] == "not_tracked":
        tracked = [repo for error in errors for repo in error.get("tracked_repos", [])]
        missing = [repo for repo in tracked if repo.lower() not in answer.lower()]
        if not tracked or missing:
            return Check(name="refusal", passed=False, reason="does not list the tracked repos")
    return Check(name="refusal", passed=True, reason='says "I don\'t know" and why')


def score(case: dict, tool_calls: list[dict], tool_results: list[dict], answer: str) -> list[Check]:
    """Run the checks that fit the case's kind. `tool_results[i]` is what `tool_calls[i]` got."""
    checks = []
    if case["expected_tools"]:
        checks.append(check_right_tools(case, tool_calls))
    if case["kind"] in ("metric", "health"):
        checks += [
            check_numbers(tool_calls, tool_results, answer),
            check_data_date(tool_calls, tool_results, answer),
            check_warnings(tool_results, answer),
        ]
    else:
        checks.append(check_refusal(case, tool_results, answer))
    checks += [check_links(tool_results, answer), check_no_leak(answer)]
    return checks
