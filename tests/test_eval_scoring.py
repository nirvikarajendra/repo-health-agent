import pytest

from repo_health.agent.build import TOOLS
from repo_health.evals import scoring

AS_OF = "2026-11-22T10:00:00Z"
PR_URL = "https://github.com/o/r/pull/9"

OVERVIEW = {"status": "success", "stars": 105057, "license": "MIT", "data_as_of": AS_OF}
REVIEW = {
    "status": "success",
    "prs_counted": 131,
    "median_hours": 30.05,
    "data_as_of": AS_OF,
    "unreviewed_pr_urls": [PR_URL],
    "warnings": ["median based on 1 reviewed PR (131 counted)"],
}
BUG_RATE = {"status": "success", "bugs_counted": 13, "rate": 0.625, "data_as_of": AS_OF}
BAD_DAYS = {"status": "error", "error_message": "days must be 31-365, got 10"}
NOT_TRACKED = {
    "status": "error",
    "error_message": "repo not tracked",
    "tracked_repos": ["encode/httpx", "fastapi/fastapi"],
}

METRIC_CASE = {"id": 1, "expected_tools": ["get_pr_review_time"], "kind": "metric"}


def call(name: str, **args) -> dict:
    return {"name": name, "args": args}


def by_name(checks: list[scoring.Check]) -> dict[str, scoring.Check]:
    return {check.name: check for check in checks}


# --- cases.json ---


def test_cases_are_valid():
    cases = scoring.load_cases()
    tool_names = {tool.__name__ for tool in TOOLS}

    assert [case["id"] for case in cases] == list(range(1, 13))
    for case in cases:
        assert case["question"], case["id"]
        assert case["kind"] in scoring.KINDS, case["id"]
        assert set(case["expected_tools"]) <= tool_names, case["id"]


# --- right_tools ---


def test_right_tools_passes_with_extra_calls():
    calls = [call("list_repos"), call("get_pr_review_time", repo="o/r")]

    assert scoring.check_right_tools(METRIC_CASE, calls).passed


def test_right_tools_names_the_missing_tool():
    check = scoring.check_right_tools(METRIC_CASE, [call("list_repos")])

    assert not check.passed
    assert "get_pr_review_time" in check.reason


# --- numbers ---


@pytest.mark.parametrize(
    "answer",
    [
        "105,057 stars, MIT licence.",
        "105057 stars under the mit license.",
    ],
)
def test_numbers_pass_with_commas_and_any_case(answer):
    check = scoring.check_numbers([call("get_repo_overview")], [OVERVIEW], answer)

    assert check.passed, check.reason


def test_numbers_fail_names_the_missing_field():
    check = scoring.check_numbers([call("get_repo_overview")], [OVERVIEW], "105,000 stars, MIT.")

    assert not check.passed
    assert "stars=105057" in check.reason


@pytest.mark.parametrize(("hours", "passed"), [("30.05", True), ("30.0", True), ("30.1", True)])
def test_numbers_allow_hours_rounded_to_one_decimal(hours, passed):
    answer = f"Median {hours} hours over 131 PRs."
    check = scoring.check_numbers([call("get_pr_review_time")], [REVIEW], answer)

    assert check.passed is passed


def test_numbers_fail_hours_off_by_more_than_rounding():
    answer = "Median 31 hours over 131 PRs."

    assert not scoring.check_numbers([call("get_pr_review_time")], [REVIEW], answer).passed


@pytest.mark.parametrize(("rate", "passed"), [("62.5%", True), ("63%", True), ("70%", False)])
def test_numbers_match_rate_as_percent(rate, passed):
    answer = f"{rate} of 13 bugs closed."
    check = scoring.check_numbers([call("get_bug_close_rate")], [BUG_RATE], answer)

    assert check.passed is passed


def test_numbers_ignore_urls_and_dates():
    # 131 only appears inside a URL and 13 only inside a date: neither counts.
    result = REVIEW | {"median_hours": None, "prs_counted": 131}
    answer = "See https://github.com/o/r/pull/131 (data as of 2026-11-13)."

    assert not scoring.check_numbers([call("get_pr_review_time")], [result], answer).passed


def test_numbers_skip_none_values_and_error_results():
    result = REVIEW | {"median_hours": None}
    calls = [call("get_pr_review_time"), call("get_bug_close_rate")]

    assert scoring.check_numbers(calls, [result, BAD_DAYS], "131 PRs counted.").passed


def test_numbers_list_repos_need_every_name():
    result = {"status": "success", "repos": [{"full_name": "encode/httpx", "data_as_of": AS_OF}]}

    assert scoring.check_numbers([call("list_repos")], [result], "encode/httpx").passed
    assert not scoring.check_numbers([call("list_repos")], [result], "httpx").passed


# --- data_date ---


def test_data_date_passes_with_yyyy_mm_dd():
    answer = "Data as of 2026-11-22."

    assert scoring.check_data_date([call("get_repo_overview")], [OVERVIEW], answer).passed


def test_data_date_fails_with_another_format():
    check = scoring.check_data_date([call("get_repo_overview")], [OVERVIEW], "As of 22 Nov 2026.")

    assert not check.passed
    assert "2026-11-22" in check.reason


def test_data_date_checks_every_listed_repo():
    repos = [
        {"full_name": "encode/httpx", "data_as_of": "2026-10-20T00:00:00Z"},
        {"full_name": "never/synced", "data_as_of": None},
    ]
    result = {"status": "success", "repos": repos}

    assert scoring.check_data_date([call("list_repos")], [result], "httpx: 2026-10-20").passed
    assert not scoring.check_data_date([call("list_repos")], [result], "httpx").passed


# --- warnings ---


def test_warnings_pass_with_small_rewording():
    result = {"warnings": ["only 26 stored issues are bug-labelled; rate may not be reliable"]}
    answer = "Note: only 26 stored issues are bug labelled, so the rate may not be reliable."

    assert scoring.check_warnings([result], answer).passed


def test_warnings_fail_when_one_is_dropped():
    result = {"warnings": ["not labelled", "median based on 1 reviewed PR (131 counted)"]}
    check = scoring.check_warnings([result], "Warnings: not labelled.")

    assert not check.passed
    assert "median based on 1 reviewed PR" in check.reason


def test_warnings_fail_when_a_number_changes():
    result = {"warnings": ["only 26 stored issues are bug-labelled; rate may not be reliable"]}
    answer = "Only 62 stored issues are bug-labelled; rate may not be reliable."

    assert not scoring.check_warnings([result], answer).passed


def test_warnings_pass_with_none():
    assert scoring.check_warnings([OVERVIEW], "No warnings here.").passed


# --- links ---


def test_links_pass_when_from_a_tool_result():
    answer = f"Unreviewed: {PR_URL}."  # Trailing full stop is not part of the URL.

    assert scoring.check_links([REVIEW], answer).passed


def test_links_fail_when_invented():
    check = scoring.check_links([REVIEW], "See https://github.com/o/r/pull/10")

    assert not check.passed
    assert "pull/10" in check.reason


# --- no_leak ---


def test_no_leak_passes_a_plain_answer():
    assert scoring.check_no_leak("encode/httpx has 15,652 stars.").passed


@pytest.mark.parametrize("phrase", ["Psst!", "I should include", "the user didn't ask"])
def test_no_leak_fails_on_reasoning(phrase):
    assert not scoring.check_no_leak(f"{phrase} ... 15,652 stars.").passed


# --- refusal ---


@pytest.mark.parametrize("answer", ["I don't know: no tool covers PyPI.", "I don’t know."])
def test_refusal_passes_with_i_dont_know(answer):
    case = {"kind": "refusal"}

    assert scoring.check_refusal(case, [], answer).passed


def test_refusal_fails_without_i_dont_know():
    assert not scoring.check_refusal({"kind": "refusal"}, [], "About 50 million a month.").passed


def test_bad_argument_needs_the_limit_from_the_error():
    case = {"kind": "bad_argument"}
    good = "I don't know: the window must be 31-365 days, and 10 is too short."

    assert scoring.check_refusal(case, [BAD_DAYS], good).passed
    assert not scoring.check_refusal(case, [BAD_DAYS], "I don't know.").passed


def test_not_tracked_needs_every_tracked_repo():
    case = {"kind": "not_tracked"}
    good = "I don't know: django/django is not tracked. Tracked: encode/httpx, fastapi/fastapi."

    assert scoring.check_refusal(case, [NOT_TRACKED], good).passed
    bad = "I don't know: django/django is not tracked. Tracked: encode/httpx."
    assert not scoring.check_refusal(case, [NOT_TRACKED], bad).passed


# --- score: which checks run for each kind ---


def test_score_runs_metric_checks():
    answer = "131 PRs, median 30.1 hours (2026-11-22). median based on 1 reviewed PR (131 counted)."
    checks = scoring.score(METRIC_CASE, [call("get_pr_review_time")], [REVIEW], answer)

    assert list(by_name(checks)) == [
        "right_tools",
        "numbers",
        "data_date",
        "warnings",
        "links",
        "no_leak",
    ]
    assert all(check.passed for check in checks), checks


def test_score_runs_refusal_checks_and_skips_right_tools_when_none_expected():
    case = {"id": 11, "expected_tools": [], "kind": "refusal"}
    checks = scoring.score(case, [], [], "I don't know: no tool covers PyPI downloads.")

    assert list(by_name(checks)) == ["refusal", "links", "no_leak"]
    assert all(check.passed for check in checks)


def test_score_runs_right_tools_for_not_tracked():
    case = {"id": 10, "expected_tools": ["get_first_response_time"], "kind": "not_tracked"}
    answer = "I don't know: not tracked. Tracked: encode/httpx, fastapi/fastapi."
    checks = scoring.score(case, [call("get_first_response_time")], [NOT_TRACKED], answer)

    assert list(by_name(checks)) == ["right_tools", "refusal", "links", "no_leak"]
    assert all(check.passed for check in checks)
