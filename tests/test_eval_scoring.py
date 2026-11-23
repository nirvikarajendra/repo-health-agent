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
        for tool, fields in case.get("key_fields", {}).items():
            assert tool in tool_names, case["id"]
            assert set(fields) <= set(scoring.FIELD_MATCH), case["id"]


# --- right_tools ---


def test_right_tools_passes_with_extra_calls():
    calls = [call("list_repos"), call("get_pr_review_time", repo="o/r")]

    assert scoring.check_right_tools(METRIC_CASE, calls).passed


def test_right_tools_names_the_missing_tool():
    check = scoring.check_right_tools(METRIC_CASE, [call("list_repos")])

    assert not check.passed
    assert "get_pr_review_time" in check.reason


# --- numbers ---

HOURS_CASE = METRIC_CASE | {"key_fields": {"get_pr_review_time": ["median_hours"]}}


def numbers(case, name, result, answer) -> scoring.Check:
    return scoring.check_numbers(case, [call(name)], [result], answer)


@pytest.mark.parametrize("answer", ["105,057 stars.", "It has 105057 stars."])
def test_numbers_pass_with_commas(answer):
    check = numbers(METRIC_CASE, "get_repo_overview", OVERVIEW, answer)

    assert check.passed, check.reason


def test_numbers_fail_names_the_missing_field():
    check = numbers(METRIC_CASE, "get_repo_overview", OVERVIEW, "105,000 stars, MIT.")

    assert not check.passed
    assert "stars=105057" in check.reason


@pytest.mark.parametrize("hours", ["30.05", "30.0", "30.1"])
def test_numbers_allow_hours_rounded_to_one_decimal(hours):
    answer = f"Median {hours} hours over 131 PRs."

    assert numbers(HOURS_CASE, "get_pr_review_time", REVIEW, answer).passed


def test_numbers_fail_hours_off_by_more_than_rounding():
    answer = "Median 31 hours over 131 PRs."

    assert not numbers(HOURS_CASE, "get_pr_review_time", REVIEW, answer).passed


def test_numbers_need_hours_only_when_the_case_asks():
    answer = "131 PRs counted."  # No median.

    assert numbers(METRIC_CASE, "get_pr_review_time", REVIEW, answer).passed
    assert not numbers(HOURS_CASE, "get_pr_review_time", REVIEW, answer).passed
    # The case asks, but the median is None: skipped (case 3 today).
    no_median = REVIEW | {"median_hours": None}
    assert numbers(HOURS_CASE, "get_pr_review_time", no_median, answer).passed


@pytest.mark.parametrize(
    ("rate", "passed"),
    [
        ("62.5%", True),
        ("63%", True),
        ("0.63", True),
        ("0.62", True),
        ("0.6", False),  # Fractions allow 2-decimal rounding only.
        ("70%", False),
    ],
)
def test_numbers_match_rate_as_percent_or_fraction(rate, passed):
    answer = f"{rate} of 13 bugs closed."

    assert numbers(METRIC_CASE, "get_bug_close_rate", BUG_RATE, answer).passed is passed


@pytest.mark.parametrize("rate", [0.28, 0.3])
def test_numbers_rate_is_not_part_of_a_version(rate):
    result = BUG_RATE | {"rate": rate}
    answer = "Latest release 0.28.1; 13 bugs counted."

    assert not numbers(METRIC_CASE, "get_bug_close_rate", result, answer).passed


def test_numbers_rate_at_the_end_of_a_sentence():
    result = BUG_RATE | {"rate": 1.0}

    assert numbers(METRIC_CASE, "get_bug_close_rate", result, "The rate was 1.0.").passed


def test_numbers_rate_needs_a_decimal_point_or_percent_sign():
    # Rate 1.0 must not match "1 author", and 100% must not match "100 stars".
    result = BUG_RATE | {"rate": 1.0}

    assert not numbers(METRIC_CASE, "get_bug_close_rate", result, "1 author, 100 stars.").passed


def test_numbers_ignore_urls_and_dates():
    # 131 only appears inside a URL and 13 only inside a date: neither counts.
    result = REVIEW | {"median_hours": None, "prs_counted": 131}
    answer = "See https://github.com/o/r/pull/131 (data as of 2026-11-13)."

    assert not numbers(METRIC_CASE, "get_pr_review_time", result, answer).passed


def test_numbers_skip_none_values_and_error_results():
    result = REVIEW | {"median_hours": None}
    calls = [call("get_pr_review_time"), call("get_bug_close_rate")]

    check = scoring.check_numbers(HOURS_CASE, calls, [result, BAD_DAYS], "131 PRs counted.")

    assert check.passed


def test_numbers_list_repos_need_every_name():
    result = {"status": "success", "repos": [{"full_name": "encode/httpx", "data_as_of": AS_OF}]}

    assert numbers(METRIC_CASE, "list_repos", result, "encode/httpx").passed
    assert not numbers(METRIC_CASE, "list_repos", result, "httpx").passed


# --- numbers: real answers from evals-results/2026-11-22-2108.json ---

FASTAPI_BUGS = {"status": "success", "bugs_counted": 13, "rate": 1.0, "data_as_of": AS_OF}


@pytest.mark.parametrize(
    "answer",
    [
        # Case 12, run 2.
        "- Bug close rate: Over the 365 days ending on 2026-11-22, the bug close rate was 1.0, "
        "with 13 out of 13 counted bugs closed as completed within 30 days",
        # Case 4, run 3.
        "- fastapi/fastapi: 1.00 (13 out of 13 counted bugs closed as completed within 30 days)"
        " as of 2026-11-22.",
    ],
)
def test_real_answers_give_the_rate_as_a_fraction(answer):
    case = {"id": 4, "expected_tools": ["get_bug_close_rate"], "kind": "metric"}

    assert numbers(case, "get_bug_close_rate", FASTAPI_BUGS, answer).passed


def test_real_answer_counting_people_needs_no_commit_count():
    # Case 7, run 1: the question asks how many people, not how many commits.
    case = scoring.load_cases()[6]
    result = {
        "status": "success",
        "active_contributors": 6,
        "commits_counted": 91,
        "data_as_of": AS_OF,
    }
    answer = (
        "Based on data collected as of 2026-11-22, there were 6 active contributors (distinct "
        "people excluding bots with a commit on the default branch) over the 365 days leading "
        "up to that date for `pallets/flask`."
    )

    assert numbers(case, "get_contributor_stats", result, answer).passed


HTTPX_OVERVIEW = {
    "status": "success",
    "stars": 15838,
    "license": "BSD-3-Clause",
    "data_as_of": AS_OF,
}
# Case 8, run 1: stars but no licence.
HTTPX_HEALTH_LINE = (
    "Overview: encode/httpx has 15838 stars, 2033 forks, and 153 open issues"
    " (data_as_of: 2026-11-22)."
)


def test_real_health_answer_needs_no_licence():
    case = scoring.load_cases()[7]  # Case 8: "Is encode/httpx healthy?"

    assert numbers(case, "get_repo_overview", HTTPX_OVERVIEW, HTTPX_HEALTH_LINE).passed


def test_licence_question_needs_the_licence():
    case = scoring.load_cases()[1]  # Case 2 asks for the licence in key_fields.

    check = numbers(case, "get_repo_overview", HTTPX_OVERVIEW, HTTPX_HEALTH_LINE)

    assert not check.passed
    assert "license=BSD-3-Clause" in check.reason
    answer = "encode/httpx has 15838 stars and the BSD-3-Clause license."
    assert numbers(case, "get_repo_overview", HTTPX_OVERVIEW, answer).passed


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


def test_real_bad_argument_answer_needs_only_the_range():
    # Case 9, run 3: gives 31 and 365 but not the 10 the model asked for ("got 10").
    case = {"kind": "bad_argument"}
    answer = "I don't know because the window length of days must be between 31 and 365."

    assert scoring.check_refusal(case, [BAD_DAYS], answer).passed
    half = "I don't know because the window must be at least 31 days."
    assert not scoring.check_refusal(case, [BAD_DAYS], half).passed


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
