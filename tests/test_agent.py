"""Agent tools against the real test database, and the agent's setup. No Gemini calls."""

import json
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from repo_health.agent import tools
from repo_health.agent.build import INSTRUCTION, TOOLS, build_agent
from repo_health.metrics import models

AS_OF = datetime(2026, 10, 20, tzinfo=UTC)
DAY = timedelta(days=1)

# Each wrapper that takes a repo, with the model whose fields it returns.
REPO_TOOLS = [
    (tools.get_repo_overview, models.RepoOverview),
    (tools.get_first_response_time, models.FirstResponseTime),
    (tools.get_bug_close_rate, models.BugCloseRate),
    (tools.get_pr_review_time, models.PrReviewTime),
    (tools.get_release_cadence, models.ReleaseCadence),
    (tools.get_contributor_stats, models.ContributorStats),
]


def name_of(value):
    """Readable test ids: a tool's function name, else pytest's default."""
    return getattr(value, "__name__", None)


@pytest.fixture
def tools_db(monkeypatch, migrated_db_url):
    """Point the wrappers' connect() at the test database instead of DATABASE_URL."""
    monkeypatch.setattr(tools, "connect", lambda: psycopg.connect(migrated_db_url))


@pytest.fixture
def tracked(db_conn, repo_id, tools_db) -> int:
    """encode/httpx with a successful sync at AS_OF, committed so the wrappers can see it."""
    db_conn.execute(
        "INSERT INTO sync_runs (repo_full_name, repo_id, status, finished_at)"
        " VALUES ('encode/httpx', %s, 'success', %s)",
        (repo_id, AS_OF),
    )
    db_conn.commit()
    return repo_id


@pytest.fixture
def activity(db_conn, tracked) -> int:
    """One item per metric for encode/httpx, committed so the wrappers can see it.

    Issue 5: outside, unanswered. Issue 7: open bug, 60 days old. PR 9: outside, unreviewed.
    Release v1: 10 days before AS_OF. Commits: 2 by alice, 1 day before AS_OF.
    """
    issue = (
        "INSERT INTO issues (repo_id, number, is_pull_request, state, author_login,"
        " author_association, labels, created_at, updated_at)"
        " VALUES (%s, %s, %s, 'open', 'outsider', 'NONE', %s, %s, %s)"
    )
    db_conn.execute(issue, (tracked, 5, False, [], AS_OF - DAY, AS_OF - DAY))
    db_conn.execute(issue, (tracked, 7, False, ["bug"], AS_OF - 60 * DAY, AS_OF - 60 * DAY))
    db_conn.execute(issue, (tracked, 9, True, [], AS_OF - DAY, AS_OF - DAY))
    db_conn.execute(
        "INSERT INTO pull_requests (repo_id, number, is_draft, base_ref)"
        " VALUES (%s, 9, false, 'main')",
        (tracked,),
    )
    db_conn.execute(
        "INSERT INTO releases (id, repo_id, tag, is_prerelease, is_draft, published_at)"
        " VALUES (1, %s, 'v1', false, false, %s)",
        (tracked, AS_OF - 10 * DAY),
    )
    for sha in ("a1", "a2"):
        db_conn.execute(
            "INSERT INTO commits (repo_id, sha, author_login, committed_at)"
            " VALUES (%s, %s, 'alice', %s)",
            (tracked, sha, AS_OF - DAY),
        )
    db_conn.commit()
    return tracked


def test_list_repos_returns_repos_with_iso_dates(tracked):
    result = tools.list_repos()

    assert result == {
        "status": "success",
        "repos": [{"full_name": "encode/httpx", "data_as_of": "2026-10-20T00:00:00Z"}],
    }


def test_list_repos_with_no_repos(db_conn, tools_db):
    assert tools.list_repos() == {"status": "success", "repos": []}


def test_get_repo_overview_returns_a_json_ready_dict(tracked, load_fixture):
    repo = load_fixture("repo.json")

    result = tools.get_repo_overview("ENCODE/httpx")

    assert result["status"] == "success"
    assert result["full_name"] == "encode/httpx"
    assert result["stars"] == repo["stargazers_count"]
    assert result["data_as_of"] == "2026-10-20T00:00:00Z"
    json.dumps(result)  # Only plain JSON types: no datetime objects left.


def test_first_response_time_wrapper_adds_issue_links(activity):
    # Issues 5 and 7 are both outside, unanswered and within 90 days: oldest (7) first.
    result = tools.get_first_response_time("encode/httpx")

    assert (result["status"], result["days"], result["issues_counted"]) == ("success", 90, 2)
    assert result["unanswered_issue_numbers"] == [7, 5]
    assert result["unanswered_issue_urls"] == [
        "https://github.com/encode/httpx/issues/7",
        "https://github.com/encode/httpx/issues/5",
    ]
    assert result["data_as_of"] == "2026-10-20T00:00:00Z"
    json.dumps(result)


def test_bug_close_rate_wrapper_adds_issue_links(activity):
    result = tools.get_bug_close_rate("encode/httpx")

    assert (result["status"], result["days"], result["bugs_counted"]) == ("success", 365, 1)
    assert result["unfixed_bug_urls"] == ["https://github.com/encode/httpx/issues/7"]
    json.dumps(result)


def test_pr_review_time_wrapper_adds_pull_links(activity):
    # PRs get /pull/ links, issues get /issues/ links.
    result = tools.get_pr_review_time("encode/httpx")

    assert (result["status"], result["days"], result["prs_counted"]) == ("success", 90, 1)
    assert result["unreviewed_pr_urls"] == ["https://github.com/encode/httpx/pull/9"]
    json.dumps(result)


def test_release_cadence_wrapper(activity):
    result = tools.get_release_cadence("encode/httpx")

    assert result["status"] == "success"
    assert (result["latest_release_tag"], result["days_since_latest_release"]) == ("v1", 10.0)
    assert result["latest_release_at"] == "2026-10-10T00:00:00Z"
    json.dumps(result)


def test_contributor_stats_wrapper(activity):
    result = tools.get_contributor_stats("encode/httpx")

    assert (result["status"], result["days"]) == ("success", 365)
    assert (result["active_contributors"], result["commits_counted"]) == (1, 2)
    json.dumps(result)


def test_wrappers_pass_days_through(activity):
    # Issue 5 (1 day old) is inside a 7-day window; alice's commits, exactly 1 day old,
    # are at the open start of a 1-day window, so they're out.
    assert tools.get_first_response_time("encode/httpx", days=7)["issues_counted"] == 1
    assert tools.get_contributor_stats("encode/httpx", days=1)["commits_counted"] == 0


def test_no_snapshot_urls_are_none(db_conn, repo_id, tools_db):
    # No successful sync: numbers are None, so the links are too (no crash).
    db_conn.commit()

    result = tools.get_first_response_time("encode/httpx")

    assert (result["note"], result["unanswered_issue_urls"]) == ("no complete snapshot", None)


@pytest.mark.parametrize("tool", [tool for tool, _ in REPO_TOOLS], ids=name_of)
def test_unknown_repo_returns_error_with_tracked_repos(tracked, tool):
    assert tool("nobody/nothing") == {
        "status": "error",
        "error_message": "repo not tracked",
        "tracked_repos": ["encode/httpx"],
    }


@pytest.mark.parametrize(
    ("tool", "days", "message"),
    [
        (tools.get_first_response_time, 0, "days must be 1-365, got 0"),
        (tools.get_bug_close_rate, 30, "days must be 31-365, got 30"),
        (tools.get_pr_review_time, 366, "days must be 1-365, got 366"),
        (tools.get_contributor_stats, -1, "days must be 1-365, got -1"),
    ],
    ids=name_of,
)
def test_bad_days_returns_error_instead_of_crashing(tracked, tool, days, message):
    assert tool("encode/httpx", days=days) == {"status": "error", "error_message": message}


def test_wrapper_connections_refuse_writes(db_conn, tools_db):
    with tools.read_only_connection() as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM repos")


@pytest.mark.parametrize(("tool", "model"), REPO_TOOLS, ids=name_of)
def test_docstrings_show_the_models_field_descriptions(tool, model):
    # ADK sends only the docstring to the model, so the limits must be in it.
    for name, field in model.model_fields.items():
        assert name in tool.__doc__
        if field.description:
            assert field.description in tool.__doc__


def test_build_agent_has_exactly_the_seven_tools(monkeypatch):
    # No API key is needed: building the agent makes no Gemini call.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    agent = build_agent("test-model")

    assert agent.model == "test-model"
    assert agent.instruction == INSTRUCTION
    assert [tool.__name__ for tool in agent.tools] == [
        "list_repos",
        "get_repo_overview",
        "get_first_response_time",
        "get_bug_close_rate",
        "get_pr_review_time",
        "get_release_cadence",
        "get_contributor_stats",
    ]
    assert agent.tools == TOOLS


def test_instruction_keeps_the_rules():
    rules = [
        "only from tool results",
        "never estimate",
        "data_as_of",
        "I don't know",
        "not tracked",
        "tracked_repos",
        "no tool covers the question",
        "Give no overall score",
        "every item in warnings",
        "up to 3 links from *_urls",
        "Never build links yourself",
        "YYYY-MM-DD",
    ]
    for rule in rules:
        assert rule in INSTRUCTION, rule


@pytest.mark.parametrize("model", [None, ""])
def test_build_agent_without_a_model_names_the_setting(model):
    with pytest.raises(ValueError, match="GEMINI_MODEL"):
        build_agent(model)


# --- Warnings: built in Python, so the agent doesn't have to spot the limits. ---


def test_wrappers_return_warnings_from_real_results(activity):
    # activity: 2 unanswered outside issues, 1 open bug (1 labelled), 1 unreviewed PR,
    # 1 release, 2 commits by alice.
    expected = {
        tools.get_repo_overview: [],
        tools.get_first_response_time: [
            "Only issues are counted; Discussions are not included.",  # The note comes first.
            "no median: none of the 2 counted issues got a maintainer comment",
        ],
        tools.get_bug_close_rate: [
            "only 1 stored issue is bug-labelled; rate may not be reliable",
            "rate based on 1 bug",
        ],
        tools.get_pr_review_time: ["no median: none of the 1 counted PR got a formal review"],
        tools.get_release_cadence: ["only 1 release; median gap based on 0 gaps"],
        tools.get_contributor_stats: ["based on only 2 commits"],
    }
    for tool, warnings in expected.items():
        assert tool("encode/httpx")["warnings"] == warnings, tool.__name__


def test_no_snapshot_warnings_are_only_the_note(db_conn, repo_id, tools_db):
    db_conn.commit()

    assert tools.get_pr_review_time("encode/httpx")["warnings"] == ["no complete snapshot"]


def test_not_labelled_bug_warning_is_only_the_note(tracked):
    # No bug-labelled issues: the note says so, with no extra warnings.
    assert tools.get_bug_close_rate("encode/httpx")["warnings"] == ["not labelled"]


@pytest.mark.parametrize(
    ("counted", "without", "expected"),
    [
        (155, 154, ["median based on 1 reviewed PR (155 counted)"]),
        (155, 151, ["median based on 4 reviewed PRs (155 counted)"]),  # 4 < 5: warn.
        (155, 150, []),  # 5 reviewed: enough.
        (3, 3, ["no median: none of the 3 counted PRs got a formal review"]),
        (0, 0, ["no PRs from outside people in the window"]),
    ],
)
def test_pr_review_warnings(counted, without, expected):
    result = {"prs_counted": counted, "prs_without_review": without}

    assert tools.pr_review_warnings(result) == expected


def test_first_response_warnings_say_answered_issues():
    result = {"issues_counted": 13, "issues_without_response": 12}

    expected = ["median based on 1 answered issue (13 counted)"]
    assert tools.first_response_warnings(result) == expected


@pytest.mark.parametrize(
    ("labelled", "counted", "expected"),
    [
        (26, 16, ["only 26 stored issues are bug-labelled; rate may not be reliable"]),
        (50, 16, []),  # 50 labelled: enough.
        (49, 5, ["only 49 stored issues are bug-labelled; rate may not be reliable"]),
        (80, 4, ["rate based on 4 bugs"]),  # 4 < 5: warn.
        (80, 0, ["no bugs in the window, so no rate"]),
        (0, None, []),  # Not labelled: the note covers it.
    ],
)
def test_bug_close_warnings(labelled, counted, expected):
    result = {"labelled_bug_issues": labelled, "bugs_counted": counted}

    assert tools.bug_close_warnings(result) == expected


@pytest.mark.parametrize(
    ("releases", "gaps", "span", "expected"),
    [
        # fastapi-like: 5 releases within 1.2 days.
        (337, 4, 1.2, ["median gap based on a burst: 5 releases within 1.2 days"]),
        (337, 4, 7.0, []),  # 7 days is not a burst.
        (337, 4, 6.9, ["median gap based on a burst: 5 releases within 6.9 days"]),
        (2, 1, 0.0, ["only 2 releases; median gap based on 1 gap"]),  # 1 gap: no burst rule.
        (
            3,
            2,
            3.0,
            [
                "only 3 releases; median gap based on 2 gaps",
                "median gap based on a burst: 3 releases within 3.0 days",
            ],
        ),
        (5, 4, 200.0, []),
        (0, 0, None, []),  # No releases: the note covers it.
    ],
)
def test_release_cadence_warnings(releases, gaps, span, expected):
    result = {"releases_counted": releases, "gaps_counted": gaps, "recent_span_days": span}

    assert tools.release_cadence_warnings(result) == expected


@pytest.mark.parametrize(
    ("counted", "unattributed", "expected"),
    [
        (3, 0, ["based on only 3 commits"]),
        (4, 0, ["based on only 4 commits"]),  # 4 < 5: warn.
        (5, 0, []),
        (0, 0, ["no commits by people in the window"]),
        (746, 2, ["2 commits with no linked GitHub account left out"]),
        (1, 1, ["based on only 1 commit", "1 commit with no linked GitHub account left out"]),
    ],
)
def test_contributor_warnings(counted, unattributed, expected):
    result = {"commits_counted": counted, "unattributed_commits": unattributed}

    assert tools.contributor_warnings(result) == expected
