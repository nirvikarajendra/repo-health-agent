"""get_pr_review_time against a real Postgres (TEST_DATABASE_URL). Skipped if it's unset."""

from datetime import UTC, datetime, timedelta

import pytest

from repo_health.collector.repos import parse_repo, upsert_repo
from repo_health.metrics.pr_review_time import get_pr_review_time

AS_OF = datetime(2026, 10, 20, tzinfo=UTC)
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)

INSERT_ISSUE = """
INSERT INTO issues (repo_id, number, is_pull_request, state, author_login, author_association,
                    created_at, closed_at, updated_at)
VALUES (%(repo_id)s, %(number)s, true, %(state)s, %(author_login)s, %(author_association)s,
        %(created_at)s, %(closed_at)s, %(created_at)s)
"""
INSERT_PULL = """
INSERT INTO pull_requests (repo_id, number, is_draft, merged_at, base_ref)
VALUES (%(repo_id)s, %(number)s, %(is_draft)s, %(merged_at)s, 'main')
"""
INSERT_REVIEW = """
INSERT INTO reviews (id, repo_id, pr_number, reviewer_login, author_association, state,
                     submitted_at)
VALUES (%(id)s, %(repo_id)s, %(pr_number)s, %(reviewer_login)s, %(author_association)s,
        %(state)s, %(submitted_at)s)
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


def add_pr(conn, repo_id, number, created_at, is_draft=False, merged_at=None, **fields):
    """An open, ready PR by outsider `alice` unless the arguments say otherwise."""
    issue = {
        "repo_id": repo_id,
        "number": number,
        "state": "open",
        "author_login": "alice",
        "author_association": "NONE",
        "created_at": created_at,
        "closed_at": None,
    }
    conn.execute(INSERT_ISSUE, issue | fields)
    pull = {"repo_id": repo_id, "number": number, "is_draft": is_draft, "merged_at": merged_at}
    conn.execute(INSERT_PULL, pull)


def add_review(
    conn,
    repo_id,
    pr_number,
    submitted_at,
    login="maintainer",
    association="MEMBER",
    state="APPROVED",
):
    """A maintainer's approving review unless the arguments say otherwise."""
    review_id = conn.execute("SELECT count(*) + 1 FROM reviews").fetchone()[0]
    row = {
        "id": review_id,
        "repo_id": repo_id,
        "pr_number": pr_number,
        "reviewer_login": login,
        "author_association": association,
        "state": state,
        "submitted_at": submitted_at,
    }
    conn.execute(INSERT_REVIEW, row)


def test_unknown_repo_returns_none(db_conn, synced):
    assert get_pr_review_time(db_conn, "nobody/nothing") is None


def test_no_complete_snapshot_gives_all_none_with_note(db_conn, repo_id):
    # No success sync run, so data_as_of is NULL; the PR is ignored.
    add_pr(db_conn, repo_id, 1, AS_OF - DAY)

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert result.note == "no complete snapshot"
    assert result.data_as_of is None
    numbers = [
        result.median_hours,
        result.prs_counted,
        result.prs_without_review,
        result.unreviewed_pr_numbers,
        result.unreviewed_merged,
        result.unreviewed_closed_unmerged,
        result.unreviewed_still_open,
    ]
    assert numbers == [None] * 7


@pytest.mark.parametrize("days", [0, 366, 30.5, True])
def test_days_out_of_range_raises(db_conn, synced, days):
    with pytest.raises(ValueError):
        get_pr_review_time(db_conn, "encode/httpx", days=days)


def test_no_prs_in_window_gives_zero_counts(db_conn, synced):
    add_pr(db_conn, synced, 1, AS_OF - 100 * DAY)  # Before the 90-day window.

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert result.data_as_of == AS_OF
    assert result.days == 90
    assert result.median_hours is None
    assert (result.prs_counted, result.prs_without_review) == (0, 0)
    assert result.unreviewed_pr_numbers == []
    assert result.note is None


def test_draft_prs_are_left_out(db_conn, synced):
    add_pr(db_conn, synced, 1, AS_OF - DAY, is_draft=True)

    assert get_pr_review_time(db_conn, "encode/httpx").prs_counted == 0


def test_bot_prs_are_left_out(db_conn, synced):
    add_pr(db_conn, synced, 1, AS_OF - DAY, author_login="dependabot[bot]")
    add_pr(db_conn, synced, 2, AS_OF - DAY, author_login="Copilot")

    assert get_pr_review_time(db_conn, "encode/httpx").prs_counted == 0


def test_maintainer_prs_are_left_out(db_conn, synced):
    for number, association in enumerate(["OWNER", "MEMBER", "COLLABORATOR"], start=1):
        add_pr(db_conn, synced, number, AS_OF - DAY, author_association=association)

    assert get_pr_review_time(db_conn, "encode/httpx").prs_counted == 0


def test_ghost_author_is_counted_and_can_be_reviewed(db_conn, synced):
    # NULL author is a person: counted, and a maintainer review at 3 h is a review.
    add_pr(db_conn, synced, 1, AS_OF - DAY, author_login=None)
    add_review(db_conn, synced, 1, AS_OF - DAY + 3 * HOUR)

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert (result.prs_counted, result.median_hours) == (1, 3.0)


def test_pr_without_a_pull_requests_row_is_left_out(db_conn, synced):
    issue = {
        "repo_id": synced,
        "number": 1,
        "state": "open",
        "author_login": "alice",
        "author_association": "NONE",
        "created_at": AS_OF - DAY,
        "closed_at": None,
    }
    db_conn.execute(INSERT_ISSUE, issue)  # No INSERT_PULL.

    assert get_pr_review_time(db_conn, "encode/httpx").prs_counted == 0


def test_window_is_open_at_start_and_closed_at_data_as_of(db_conn, synced):
    # Window (AS_OF - 90 days, AS_OF]: only PR 2 is in it.
    add_pr(db_conn, synced, 1, AS_OF - 90 * DAY)  # Exactly at the start: out.
    add_pr(db_conn, synced, 2, AS_OF)  # Exactly at data_as_of: in.
    add_pr(db_conn, synced, 3, AS_OF + HOUR)  # After data_as_of: out.

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert result.prs_counted == 1
    assert result.unreviewed_pr_numbers == [2]


def test_review_after_data_as_of_does_not_count(db_conn, synced):
    add_pr(db_conn, synced, 1, AS_OF - DAY)
    add_review(db_conn, synced, 1, AS_OF + HOUR)

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert (result.median_hours, result.prs_without_review) == (None, 1)


def test_review_with_no_submitted_at_does_not_count(db_conn, synced):
    # A pending review (still being written) has no submitted_at.
    add_pr(db_conn, synced, 1, AS_OF - DAY)
    add_review(db_conn, synced, 1, None, state="PENDING")

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert (result.median_hours, result.prs_without_review) == (None, 1)


def test_reviews_that_are_not_maintainer_reviews_are_ignored(db_conn, synced):
    # One PR per kind of review that doesn't count: all 5 stay unreviewed.
    for number in range(1, 6):
        add_pr(db_conn, synced, number, AS_OF - DAY)
    at = AS_OF - DAY + HOUR
    add_review(db_conn, synced, 1, at, login="bob", association="CONTRIBUTOR")
    add_review(db_conn, synced, 2, at, login="copilot-pull-request-reviewer[bot]")
    add_review(db_conn, synced, 3, at, login="Copilot")
    add_review(db_conn, synced, 4, at, login="alice")  # The PR's author (self-review).
    add_review(db_conn, synced, 5, at, login=None)  # Deleted user: never a maintainer.

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert (result.prs_counted, result.prs_without_review) == (5, 5)
    assert result.median_hours is None


def test_plain_comment_is_not_a_review(db_conn, synced):
    add_pr(db_conn, synced, 1, AS_OF - DAY)
    db_conn.execute(
        "INSERT INTO comments (id, repo_id, issue_number, author_login, author_association,"
        " created_at) VALUES (1, %s, 1, 'maintainer', 'MEMBER', %s)",
        (synced, AS_OF - DAY + HOUR),
    )

    assert get_pr_review_time(db_conn, "encode/httpx").prs_without_review == 1


def test_earliest_review_counts_whatever_its_state(db_conn, synced):
    # Reviews at +5 h (APPROVED) and +3 h (DISMISSED, inserted second): first review is 3 h.
    add_pr(db_conn, synced, 1, AS_OF - DAY)
    add_review(db_conn, synced, 1, AS_OF - DAY + 5 * HOUR)
    add_review(db_conn, synced, 1, AS_OF - DAY + 3 * HOUR, state="DISMISSED")

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert (result.median_hours, result.prs_without_review) == (3.0, 0)


def test_median_of_even_count_averages_the_middle_two(db_conn, synced):
    # Reviews at 1 h (COMMENTED) and 3 h, plus one unreviewed PR (left out of the median):
    # median = (1 + 3) / 2 = 2.0.
    for number in range(1, 4):
        add_pr(db_conn, synced, number, AS_OF - DAY)
    add_review(db_conn, synced, 1, AS_OF - DAY + HOUR, state="COMMENTED")
    add_review(db_conn, synced, 2, AS_OF - DAY + 3 * HOUR, state="CHANGES_REQUESTED")

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert result.median_hours == 2.0
    assert (result.prs_counted, result.prs_without_review) == (3, 1)


def test_unreviewed_prs_split_by_state_at_data_as_of(db_conn, synced):
    # merged: 1 → 1; closed unmerged: 2 → 1; still open: 3 (open), 4 (merged after
    # data_as_of), 5 (closed after data_as_of) → 3. PR 6 is reviewed: in no group.
    created = AS_OF - 10 * DAY
    done = AS_OF - DAY
    later = AS_OF + DAY
    add_pr(db_conn, synced, 1, created, merged_at=done, state="closed", closed_at=done)
    add_pr(db_conn, synced, 2, created, state="closed", closed_at=done)
    add_pr(db_conn, synced, 3, created)
    add_pr(db_conn, synced, 4, created, merged_at=later, state="closed", closed_at=later)
    add_pr(db_conn, synced, 5, created, state="closed", closed_at=later)
    add_pr(db_conn, synced, 6, created, merged_at=done, state="closed", closed_at=done)
    add_review(db_conn, synced, 6, created + HOUR)

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert result.prs_without_review == 5
    assert result.unreviewed_merged == 1
    assert result.unreviewed_closed_unmerged == 1
    assert result.unreviewed_still_open == 3


def test_unreviewed_pr_numbers_are_oldest_first_and_capped_at_10(db_conn, synced):
    # 12 unreviewed PRs; higher numbers are older, so oldest first is 12, 11, ..., 3.
    # PR 13 is reviewed and must not appear.
    for number in range(1, 13):
        add_pr(db_conn, synced, number, AS_OF - number * HOUR)
    add_pr(db_conn, synced, 13, AS_OF - 20 * HOUR)
    add_review(db_conn, synced, 13, AS_OF - 19 * HOUR)

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert result.prs_without_review == 12
    assert result.unreviewed_pr_numbers == [12, 11, 10, 9, 8, 7, 6, 5, 4, 3]


def test_name_matches_ignoring_case(db_conn, synced):
    add_pr(db_conn, synced, 1, AS_OF - DAY)

    result = get_pr_review_time(db_conn, "ENCODE/Httpx")

    assert (result.full_name, result.prs_counted) == ("encode/httpx", 1)


def test_other_repos_prs_and_reviews_are_ignored(db_conn, synced, load_fixture):
    # Both repos have PR #1; only the other repo has one more PR and a maintainer review.
    # Ours: 1 counted, 1 unreviewed. Losing the PR repo filter makes it 2 counted;
    # losing the review one makes ours reviewed.
    other = parse_repo(load_fixture("repo.json"), load_fixture("community_profile.json"))
    upsert_repo(db_conn, other | {"id": 1, "full_name": "other/repo"})
    add_pr(db_conn, synced, 1, AS_OF - DAY)
    add_pr(db_conn, 1, 1, AS_OF - DAY)
    add_pr(db_conn, 1, 2, AS_OF - DAY)
    add_review(db_conn, 1, 1, AS_OF - DAY + HOUR)

    result = get_pr_review_time(db_conn, "encode/httpx")

    assert (result.prs_counted, result.prs_without_review) == (1, 1)
    assert result.median_hours is None
