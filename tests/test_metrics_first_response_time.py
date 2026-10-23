"""get_first_response_time against a real Postgres (TEST_DATABASE_URL). Skipped if it's unset."""

from datetime import UTC, datetime, timedelta

import pytest

from repo_health.collector.repos import parse_repo, upsert_repo
from repo_health.metrics.first_response_time import ISSUES_ONLY, get_first_response_time

AS_OF = datetime(2026, 10, 20, tzinfo=UTC)
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)

INSERT_ISSUE = """
INSERT INTO issues (repo_id, number, is_pull_request, state, state_reason, author_login,
                    author_association, created_at, closed_at, updated_at)
VALUES (%(repo_id)s, %(number)s, %(is_pull_request)s, %(state)s, %(state_reason)s,
        %(author_login)s, %(author_association)s, %(created_at)s, %(closed_at)s, %(created_at)s)
"""
INSERT_COMMENT = """
INSERT INTO comments (id, repo_id, issue_number, author_login, author_association, created_at)
VALUES (%(id)s, %(repo_id)s, %(issue_number)s, %(author_login)s, %(author_association)s,
        %(created_at)s)
"""


@pytest.fixture
def synced(db_conn, repo_id) -> int:
    """The repo with one successful sync finishing at AS_OF, so data_as_of = AS_OF."""
    db_conn.execute(
        "INSERT INTO sync_runs (repo_full_name, repo_id, status, finished_at)"
        " VALUES ('encode/httpx', %s, 'success', %s)",
        (repo_id, AS_OF),
    )
    return repo_id


def add_issue(conn, repo_id, number, created_at, **fields):
    """An outside, open, non-PR issue by `alice` unless `fields` say otherwise."""
    row = {
        "repo_id": repo_id,
        "number": number,
        "is_pull_request": False,
        "state": "open",
        "state_reason": None,
        "author_login": "alice",
        "author_association": "NONE",
        "created_at": created_at,
        "closed_at": None,
    }
    conn.execute(INSERT_ISSUE, row | fields)


def add_comment(conn, repo_id, issue_number, created_at, login="maintainer", association="MEMBER"):
    """A maintainer comment unless `login`/`association` say otherwise."""
    comment_id = conn.execute("SELECT count(*) + 1 FROM comments").fetchone()[0]
    conn.execute(
        INSERT_COMMENT,
        {
            "id": comment_id,
            "repo_id": repo_id,
            "issue_number": issue_number,
            "author_login": login,
            "author_association": association,
            "created_at": created_at,
        },
    )


def test_unknown_repo_returns_none(db_conn, synced):
    assert get_first_response_time(db_conn, "nobody/nothing") is None


def test_no_complete_snapshot_gives_all_none_with_note(db_conn, repo_id):
    # No success sync run, so data_as_of is NULL; the issue is ignored.
    add_issue(db_conn, repo_id, 1, AS_OF - DAY)

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.full_name == "encode/httpx"
    assert result.data_as_of is None
    assert result.note == "no complete snapshot"
    numbers = [
        result.median_hours,
        result.issues_counted,
        result.issues_without_response,
        result.unanswered_issue_numbers,
        result.unanswered_closed_completed,
        result.unanswered_closed_not_planned,
        result.unanswered_still_open,
    ]
    assert numbers == [None] * 7


@pytest.mark.parametrize("days", [0, 366, -5, 30.5, True])
def test_days_out_of_range_raises(db_conn, synced, days):
    with pytest.raises(ValueError):
        get_first_response_time(db_conn, "encode/httpx", days=days)


def test_no_issues_in_window_gives_zero_counts(db_conn, synced):
    add_issue(db_conn, synced, 1, AS_OF - 100 * DAY)  # Before the 90-day window.

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.data_as_of == AS_OF
    assert result.days == 90
    assert result.median_hours is None
    assert result.issues_counted == 0
    assert result.issues_without_response == 0
    assert result.unanswered_issue_numbers == []
    assert result.note == ISSUES_ONLY


def test_maintainer_and_bot_issues_are_not_counted(db_conn, synced):
    add_issue(db_conn, synced, 1, AS_OF - DAY, author_association="OWNER")
    add_issue(db_conn, synced, 2, AS_OF - DAY, author_association="MEMBER")
    add_issue(db_conn, synced, 3, AS_OF - DAY, author_association="COLLABORATOR")
    add_issue(db_conn, synced, 4, AS_OF - DAY, author_login="dependabot[bot]")
    add_issue(db_conn, synced, 5, AS_OF - DAY, author_login="Copilot")

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.issues_counted == 0


def test_pull_requests_are_ignored(db_conn, synced):
    add_issue(db_conn, synced, 1, AS_OF - DAY, is_pull_request=True)
    add_comment(db_conn, synced, 1, AS_OF - DAY + HOUR)

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.issues_counted == 0


def test_window_is_open_at_start_and_closed_at_data_as_of(db_conn, synced):
    # Window (AS_OF - 90 days, AS_OF]: only issue 2 is in it.
    add_issue(db_conn, synced, 1, AS_OF - 90 * DAY)  # Exactly at the start: out.
    add_issue(db_conn, synced, 2, AS_OF)  # Exactly at data_as_of: in.
    add_issue(db_conn, synced, 3, AS_OF + HOUR)  # After data_as_of: out.

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.issues_counted == 1
    assert result.unanswered_issue_numbers == [2]


def test_comment_after_data_as_of_is_no_response(db_conn, synced):
    add_issue(db_conn, synced, 1, AS_OF - DAY)
    add_comment(db_conn, synced, 1, AS_OF + HOUR)

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.median_hours is None
    assert result.issues_without_response == 1


def test_comments_that_are_not_responses_are_ignored(db_conn, synced):
    # One issue per kind of comment that doesn't count: all 4 stay unanswered.
    for number in range(1, 5):
        add_issue(db_conn, synced, number, AS_OF - DAY)
    add_comment(db_conn, synced, 1, AS_OF - DAY + HOUR, login="bob", association="NONE")
    add_comment(db_conn, synced, 2, AS_OF - DAY + HOUR, login="github-actions[bot]")
    add_comment(db_conn, synced, 3, AS_OF - DAY + HOUR, login="Copilot")
    add_comment(db_conn, synced, 4, AS_OF - DAY + HOUR, login="alice")  # The issue's author.

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.issues_counted == 4
    assert result.issues_without_response == 4
    assert result.median_hours is None


def test_earliest_maintainer_comment_counts(db_conn, synced):
    # Comments at +5 h and +2 h (inserted in that order): the response is at 2 h.
    add_issue(db_conn, synced, 1, AS_OF - DAY)
    add_comment(db_conn, synced, 1, AS_OF - DAY + 5 * HOUR)
    add_comment(db_conn, synced, 1, AS_OF - DAY + 2 * HOUR)

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.median_hours == 2.0
    assert result.issues_without_response == 0


def test_ghost_issue_author_is_counted_and_can_be_answered(db_conn, synced):
    # NULL author is a person: counted, and a maintainer reply at 3 h is a response.
    add_issue(db_conn, synced, 1, AS_OF - DAY, author_login=None)
    add_comment(db_conn, synced, 1, AS_OF - DAY + 3 * HOUR)

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.issues_counted == 1
    assert result.median_hours == 3.0


def test_ghost_commenter_is_never_a_response(db_conn, synced):
    # NULL login is not a maintainer, even if the comment says MEMBER.
    add_issue(db_conn, synced, 1, AS_OF - DAY)
    add_comment(db_conn, synced, 1, AS_OF - DAY + HOUR, login=None, association="MEMBER")

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.issues_without_response == 1


def test_issues_counted_but_none_answered(db_conn, synced):
    for number in range(1, 4):
        add_issue(db_conn, synced, number, AS_OF - DAY)

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.median_hours is None
    assert result.issues_counted == 3
    assert result.issues_without_response == 3


def test_median_of_even_count_averages_the_middle_two(db_conn, synced):
    # Responses at 1 h and 3 h, plus one unanswered issue (left out of the median):
    # median = (1 + 3) / 2 = 2.0.
    for number in range(1, 4):
        add_issue(db_conn, synced, number, AS_OF - DAY)
    add_comment(db_conn, synced, 1, AS_OF - DAY + HOUR)
    add_comment(db_conn, synced, 2, AS_OF - DAY + 3 * HOUR)

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.median_hours == 2.0
    assert result.issues_counted == 3
    assert result.issues_without_response == 1


def test_name_matches_ignoring_case(db_conn, synced):
    add_issue(db_conn, synced, 1, AS_OF - DAY)

    result = get_first_response_time(db_conn, "ENCODE/Httpx")

    assert result.full_name == "encode/httpx"
    assert result.issues_counted == 1


def test_other_repos_issues_and_comments_are_ignored(db_conn, synced, load_fixture):
    # Both repos have issue #1; only the other repo's has a maintainer comment.
    # Ours: 1 counted, 1 unanswered. Losing the issue repo_id filter makes it 2 counted;
    # losing the comment one makes ours answered.
    other = parse_repo(load_fixture("repo.json"), load_fixture("community_profile.json"))
    upsert_repo(db_conn, other | {"id": 1, "full_name": "other/repo"})
    add_issue(db_conn, synced, 1, AS_OF - DAY)
    add_issue(db_conn, 1, 1, AS_OF - DAY)
    add_comment(db_conn, 1, 1, AS_OF - DAY + HOUR)

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.issues_counted == 1
    assert result.issues_without_response == 1
    assert result.median_hours is None


def test_unanswered_issues_split_by_state_at_data_as_of(db_conn, synced):
    # completed: 1 (completed), 2 (no reason) → 2
    # not planned: 3 (not_planned), 4 (duplicate) → 2
    # still open: 5 (open), 6 (closed after data_as_of) → 2
    closed = {"state": "closed", "closed_at": AS_OF - HOUR}
    add_issue(db_conn, synced, 1, AS_OF - DAY, **closed, state_reason="completed")
    add_issue(db_conn, synced, 2, AS_OF - DAY, **closed)
    add_issue(db_conn, synced, 3, AS_OF - DAY, **closed, state_reason="not_planned")
    add_issue(db_conn, synced, 4, AS_OF - DAY, **closed, state_reason="duplicate")
    add_issue(db_conn, synced, 5, AS_OF - DAY)
    add_issue(
        db_conn,
        synced,
        6,
        AS_OF - DAY,
        state="closed",
        state_reason="not_planned",
        closed_at=AS_OF + HOUR,
    )

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.issues_without_response == 6
    assert result.unanswered_closed_completed == 2
    assert result.unanswered_closed_not_planned == 2
    assert result.unanswered_still_open == 2


def test_unanswered_issue_numbers_are_oldest_first_and_capped_at_10(db_conn, synced):
    # 12 unanswered issues; higher numbers are older, so oldest first is 12, 11, ..., 3.
    # Issue 13 is answered and must not appear.
    for number in range(1, 13):
        add_issue(db_conn, synced, number, AS_OF - number * HOUR)
    add_issue(db_conn, synced, 13, AS_OF - 20 * HOUR)
    add_comment(db_conn, synced, 13, AS_OF - 19 * HOUR)

    result = get_first_response_time(db_conn, "encode/httpx")

    assert result.issues_without_response == 12
    assert result.unanswered_issue_numbers == [12, 11, 10, 9, 8, 7, 6, 5, 4, 3]
