"""get_bug_close_rate against a real Postgres (TEST_DATABASE_URL). Skipped if it's unset."""

from datetime import UTC, datetime, timedelta

import pytest

from repo_health.collector.repos import parse_repo, upsert_repo
from repo_health.metrics.bug_close_rate import get_bug_close_rate

AS_OF = datetime(2026, 10, 20, tzinfo=UTC)
DAY = timedelta(days=1)

INSERT_ISSUE = """
INSERT INTO issues (repo_id, number, is_pull_request, state, state_reason, author_login,
                    author_association, labels, created_at, closed_at, updated_at)
VALUES (%(repo_id)s, %(number)s, %(is_pull_request)s, %(state)s, %(state_reason)s,
        %(author_login)s, %(author_association)s, %(labels)s, %(created_at)s, %(closed_at)s,
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
    """An open, non-PR issue labelled `bug` by `alice` unless `fields` say otherwise."""
    row = {
        "repo_id": repo_id,
        "number": number,
        "is_pull_request": False,
        "state": "open",
        "state_reason": None,
        "author_login": "alice",
        "author_association": "NONE",
        "labels": ["bug"],
        "created_at": created_at,
        "closed_at": None,
    }
    conn.execute(INSERT_ISSUE, row | fields)


def test_not_a_bug_label_alone_means_not_labelled(db_conn, synced):
    # psf/requests uses "Question/Not a bug": it has the word "bug" but must not count.
    add_issue(db_conn, synced, 1, AS_OF - 60 * DAY, labels=["Question/Not a bug"])
    add_issue(db_conn, synced, 2, AS_OF - 60 * DAY, labels=["NOT  A  BUG"])  # Case, spaces.

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert result.note == "not labelled"
    assert (result.rate, result.bugs_counted, result.bugs_fixed) == (None, None, None)
    assert result.labelled_bug_issues == 0


def test_not_a_bug_label_is_not_counted_in_the_window(db_conn, synced):
    # Issue 1 (bug, open) counts; issue 2 (only "Question/Not a bug") doesn't.
    # Issue 3 has both labels: "bug" still makes it a bug. Counted 2, fixed 0.
    add_issue(db_conn, synced, 1, AS_OF - 60 * DAY)
    add_issue(db_conn, synced, 2, AS_OF - 60 * DAY, labels=["Question/Not a bug"])
    add_issue(db_conn, synced, 3, AS_OF - 60 * DAY, labels=["bug", "Question/Not a bug"])

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert result.bugs_counted == 2
    assert result.unfixed_bug_numbers == [1, 3]
    assert result.labelled_bug_issues == 2  # Issues 1 and 3; issue 3 has two labels, counted once.


def closed(created_at, after, reason="completed") -> dict:
    """Fields for an issue closed `after` its creation with `reason`."""
    return {"state": "closed", "state_reason": reason, "closed_at": created_at + after}


def test_unknown_repo_returns_none(db_conn, synced):
    assert get_bug_close_rate(db_conn, "nobody/nothing") is None


def test_no_complete_snapshot_gives_all_none_with_note(db_conn, repo_id):
    # No success sync run, so data_as_of is NULL; the labelled bug is ignored.
    add_issue(db_conn, repo_id, 1, AS_OF - 60 * DAY)

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert result.note == "no complete snapshot"
    assert result.data_as_of is None
    numbers = [
        result.rate,
        result.bugs_counted,
        result.bugs_fixed,
        result.unfixed_bug_numbers,
        result.labelled_bug_issues,
    ]
    assert numbers == [None] * 5


@pytest.mark.parametrize("days", [30, 366, 0, 30.5, True])
def test_days_out_of_range_raises(db_conn, synced, days):
    with pytest.raises(ValueError):
        get_bug_close_rate(db_conn, "encode/httpx", days=days)


def test_debug_and_other_labels_mean_not_labelled(db_conn, synced):
    add_issue(db_conn, synced, 1, AS_OF - 60 * DAY, labels=["debug", "enhancement"])

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert result.note == "not labelled"
    assert result.labelled_bug_issues == 0


def test_pull_requests_with_a_bug_label_are_ignored(db_conn, synced):
    # The only bug label is on a PR: not a bug, and the repo stays "not labelled".
    add_issue(db_conn, synced, 1, AS_OF - 60 * DAY, is_pull_request=True)

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert result.note == "not labelled"


def test_bug_label_matches_words_ignoring_case(db_conn, synced):
    # Bug, type: bug, kind/bug match; debug alone doesn't: 3 counted, all open.
    add_issue(db_conn, synced, 1, AS_OF - 60 * DAY, labels=["Bug"])
    add_issue(db_conn, synced, 2, AS_OF - 60 * DAY, labels=["type: bug"])
    add_issue(db_conn, synced, 3, AS_OF - 60 * DAY, labels=["kind/bug"])
    add_issue(db_conn, synced, 4, AS_OF - 60 * DAY, labels=["debug"])

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert result.bugs_counted == 3
    assert result.unfixed_bug_numbers == [1, 2, 3]
    assert result.labelled_bug_issues == 3


def test_window_boundaries(db_conn, synced):
    # Window (AS_OF - 365 days, AS_OF - 30 days]: only issue 2 is in it.
    add_issue(db_conn, synced, 1, AS_OF - 365 * DAY)  # Exactly at the start: out.
    add_issue(db_conn, synced, 2, AS_OF - 30 * DAY)  # Exactly 30 days old: in.
    add_issue(db_conn, synced, 3, AS_OF - 29 * DAY)  # Not had its 30 days yet: out.

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert result.bugs_counted == 1
    assert result.unfixed_bug_numbers == [2]


def test_shortest_window_is_31_days(db_conn, synced):
    # days=31: window (AS_OF - 31 days, AS_OF - 30 days], so only issue 2 is in it.
    add_issue(db_conn, synced, 1, AS_OF - 31 * DAY)  # At the start: out.
    add_issue(db_conn, synced, 2, AS_OF - 30 * DAY - timedelta(hours=1))

    result = get_bug_close_rate(db_conn, "encode/httpx", days=31)

    assert result.bugs_counted == 1


def test_fixed_means_closed_within_30_days(db_conn, synced):
    # Issue 1 closed exactly 30 days after creation: fixed.
    # Issue 2 closed 30 days and 1 second after: counted, not fixed. Rate 1/2.
    created = AS_OF - 100 * DAY
    add_issue(db_conn, synced, 1, created, **closed(created, 30 * DAY))
    add_issue(db_conn, synced, 2, created, **closed(created, 30 * DAY + timedelta(seconds=1)))

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert (result.bugs_counted, result.bugs_fixed, result.rate) == (2, 1, 0.5)
    assert result.unfixed_bug_numbers == [2]


def test_not_planned_and_duplicate_closed_by_data_as_of_are_left_out(db_conn, synced):
    # Issues 2 and 3 are left out entirely; issue 1 (fixed) is the only one counted.
    created = AS_OF - 100 * DAY
    add_issue(db_conn, synced, 1, created, **closed(created, DAY))
    add_issue(db_conn, synced, 2, created, **closed(created, DAY, "not_planned"))
    add_issue(db_conn, synced, 3, created, **closed(created, DAY, "duplicate"))

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert (result.bugs_counted, result.bugs_fixed, result.rate) == (1, 1, 1.0)


def test_closed_as_not_planned_after_data_as_of_counts_as_not_fixed(db_conn, synced):
    # Still open at AS_OF: counted, not fixed, whatever happened later.
    created = AS_OF - 100 * DAY
    add_issue(db_conn, synced, 1, created, **closed(created, 101 * DAY, "not_planned"))

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert (result.bugs_counted, result.bugs_fixed, result.rate) == (1, 0, 0.0)


def test_open_bug_counts_as_not_fixed(db_conn, synced):
    add_issue(db_conn, synced, 1, AS_OF - 100 * DAY)

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert (result.bugs_counted, result.bugs_fixed, result.rate) == (1, 0, 0.0)


def test_closed_with_no_reason_within_30_days_is_fixed(db_conn, synced):
    # Older issues have state_reason NULL: treated as completed, so fixed.
    created = AS_OF - 100 * DAY
    add_issue(db_conn, synced, 1, created, **closed(created, DAY, None))

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert (result.bugs_counted, result.bugs_fixed) == (1, 1)


def test_labelled_but_nothing_in_window_gives_zero_counts_and_no_note(db_conn, synced):
    add_issue(db_conn, synced, 1, AS_OF - 400 * DAY)  # Before the 365-day window.

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert result.rate is None
    assert (result.bugs_counted, result.bugs_fixed) == (0, 0)
    assert result.unfixed_bug_numbers == []
    assert result.labelled_bug_issues == 1
    assert result.note is None


def test_name_matches_ignoring_case(db_conn, synced):
    add_issue(db_conn, synced, 1, AS_OF - 60 * DAY)

    result = get_bug_close_rate(db_conn, "ENCODE/Httpx")

    assert result.full_name == "encode/httpx"
    assert result.bugs_counted == 1


def test_ghost_author_is_counted(db_conn, synced):
    add_issue(db_conn, synced, 1, AS_OF - 60 * DAY, author_login=None)

    assert get_bug_close_rate(db_conn, "encode/httpx").bugs_counted == 1


def test_bug_reports_by_bots_are_left_out(db_conn, synced):
    # Only issue 1 (a person) counts; the bot issues still count as labelled.
    add_issue(db_conn, synced, 1, AS_OF - 60 * DAY)
    add_issue(db_conn, synced, 2, AS_OF - 60 * DAY, author_login="renovate[bot]")
    add_issue(db_conn, synced, 3, AS_OF - 60 * DAY, author_login="Copilot")

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert result.bugs_counted == 1
    assert result.labelled_bug_issues == 3


def test_rate_is_fixed_over_counted(db_conn, synced):
    # 4 counted: issue 1 fixed, 2 closed too late, 3 and 4 open. Rate 1/4 = 0.25.
    created = AS_OF - 100 * DAY
    add_issue(db_conn, synced, 1, created, **closed(created, 2 * DAY))
    add_issue(db_conn, synced, 2, created, **closed(created, 40 * DAY))
    add_issue(db_conn, synced, 3, created)
    add_issue(db_conn, synced, 4, created)

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert (result.bugs_counted, result.bugs_fixed, result.rate) == (4, 1, 0.25)


def test_unfixed_bug_numbers_are_oldest_first_and_capped_at_10(db_conn, synced):
    # 12 unfixed bugs; higher numbers are older, so oldest first is 12, 11, ..., 3.
    # Issue 13 is fixed and must not appear.
    for number in range(1, 13):
        add_issue(db_conn, synced, number, AS_OF - (40 + number) * DAY)
    created = AS_OF - 60 * DAY
    add_issue(db_conn, synced, 13, created, **closed(created, DAY))

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert (result.bugs_counted, result.bugs_fixed) == (13, 1)
    assert result.unfixed_bug_numbers == [12, 11, 10, 9, 8, 7, 6, 5, 4, 3]


def test_other_repos_bugs_are_ignored(db_conn, synced, load_fixture):
    # The other repo (id 1) has bugs in the window; ours has none at first.
    other = parse_repo(load_fixture("repo.json"), load_fixture("community_profile.json"))
    upsert_repo(db_conn, other | {"id": 1, "full_name": "other/repo"})
    add_issue(db_conn, 1, 1, AS_OF - 60 * DAY)
    add_issue(db_conn, 1, 2, AS_OF - 60 * DAY)

    before = get_bug_close_rate(db_conn, "encode/httpx")

    # Their bugs don't make ours labelled (labelled check filters by repo).
    assert (before.note, before.labelled_bug_issues) == ("not labelled", 0)

    # Now ours has one bug, before the window: labelled, but nothing counted.
    add_issue(db_conn, synced, 1, AS_OF - 400 * DAY)

    after = get_bug_close_rate(db_conn, "encode/httpx")

    assert after.labelled_bug_issues == 1  # Not 3: theirs aren't included.
    assert after.bugs_counted == 0  # Not 2: the window filters by repo too.


def test_hyphen_and_underscore_not_a_bug_labels_mean_not_labelled(db_conn, synced):
    add_issue(db_conn, synced, 1, AS_OF - 60 * DAY, labels=["not-a-bug"])
    add_issue(db_conn, synced, 2, AS_OF - 60 * DAY, labels=["Not_A_Bug"])

    result = get_bug_close_rate(db_conn, "encode/httpx")

    assert (result.note, result.labelled_bug_issues) == ("not labelled", 0)


def test_bugs_created_after_data_as_of_are_ignored(db_conn, synced):
    # A later, failed sync can leave newer issues behind; they must not make the repo labelled.
    add_issue(db_conn, synced, 1, AS_OF + DAY)

    before = get_bug_close_rate(db_conn, "encode/httpx")

    assert (before.note, before.labelled_bug_issues) == ("not labelled", 0)

    # With one bug before data_as_of, only that one is in labelled_bug_issues.
    add_issue(db_conn, synced, 2, AS_OF - 400 * DAY)

    assert get_bug_close_rate(db_conn, "encode/httpx").labelled_bug_issues == 1
