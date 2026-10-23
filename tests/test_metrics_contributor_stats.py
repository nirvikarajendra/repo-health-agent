"""get_contributor_stats against a real Postgres (TEST_DATABASE_URL). Skipped if it's unset."""

from datetime import UTC, datetime, timedelta

import pytest

from repo_health.collector.repos import parse_repo, upsert_repo
from repo_health.metrics.contributor_stats import get_contributor_stats

AS_OF = datetime(2026, 10, 20, tzinfo=UTC)
DAY = timedelta(days=1)

INSERT_COMMIT = """
INSERT INTO commits (repo_id, sha, author_login, committed_at)
VALUES (%(repo_id)s, %(sha)s, %(author_login)s, %(committed_at)s)
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


def add_commits(conn, repo_id, author_login, count=1, committed_at=AS_OF - DAY):
    """`count` commits by `author_login`, each with its own sha."""
    for _ in range(count):
        sha = f"sha{conn.execute('SELECT count(*) FROM commits').fetchone()[0]}"
        row = {
            "repo_id": repo_id,
            "sha": sha,
            "author_login": author_login,
            "committed_at": committed_at,
        }
        conn.execute(INSERT_COMMIT, row)


def numbers(result) -> tuple:
    return (
        result.active_contributors,
        result.authors_for_half_of_commits,
        result.commits_counted,
        result.bot_commits,
        result.unattributed_commits,
    )


def test_unknown_repo_returns_none(db_conn, synced):
    assert get_contributor_stats(db_conn, "nobody/nothing") is None


def test_no_complete_snapshot_gives_all_none_with_note(db_conn, repo_id):
    # No success sync run, so data_as_of is NULL; the commit is ignored.
    add_commits(db_conn, repo_id, "alice")

    result = get_contributor_stats(db_conn, "encode/httpx")

    assert result.note == "no complete snapshot"
    assert result.data_as_of is None
    assert numbers(result) == (None,) * 5


@pytest.mark.parametrize("days", [0, 366, 30.5, True])
def test_days_out_of_range_raises(db_conn, synced, days):
    with pytest.raises(ValueError):
        get_contributor_stats(db_conn, "encode/httpx", days=days)


def test_no_commits_in_window_gives_zero_counts(db_conn, synced):
    add_commits(db_conn, synced, "alice", committed_at=AS_OF - 400 * DAY)  # Before the window.

    result = get_contributor_stats(db_conn, "encode/httpx")

    # active 0, concentration None, counted 0, bots 0, unattributed 0.
    assert numbers(result) == (0, None, 0, 0, 0)
    assert (result.days, result.data_as_of, result.note) == (365, AS_OF, None)


def test_only_bot_commits(db_conn, synced):
    # 3 by dependabot[bot] + 2 by Copilot: all bots, nobody active.
    add_commits(db_conn, synced, "dependabot[bot]", 3)
    add_commits(db_conn, synced, "Copilot", 2)

    assert numbers(get_contributor_stats(db_conn, "encode/httpx")) == (0, None, 0, 5, 0)


def test_only_unattributed_commits(db_conn, synced):
    add_commits(db_conn, synced, None, 4)

    assert numbers(get_contributor_stats(db_conn, "encode/httpx")) == (0, None, 0, 0, 4)


def test_counted_bot_and_unattributed_add_up_to_all_commits(db_conn, synced):
    # alice 3, bob 1 (counted 4), github-actions[bot] 2, unattributed 1: 7 in all.
    add_commits(db_conn, synced, "alice", 3)
    add_commits(db_conn, synced, "bob")
    add_commits(db_conn, synced, "github-actions[bot]", 2)
    add_commits(db_conn, synced, None)

    result = get_contributor_stats(db_conn, "encode/httpx")

    # alice's 3 of 4 is at least 50%, so 1 author.
    assert numbers(result) == (2, 1, 4, 2, 1)


def test_window_is_open_at_start_and_closed_at_data_as_of(db_conn, synced):
    # Window (AS_OF - 365 days, AS_OF]: only bob's commit is in it.
    add_commits(db_conn, synced, "alice", committed_at=AS_OF - 365 * DAY)  # At the start: out.
    add_commits(db_conn, synced, "bob", committed_at=AS_OF)  # At data_as_of: in.
    add_commits(db_conn, synced, "carol", committed_at=AS_OF + DAY)  # After data_as_of: out.

    result = get_contributor_stats(db_conn, "encode/httpx")

    assert (result.active_contributors, result.commits_counted) == (1, 1)


def test_shorter_days_window(db_conn, synced):
    # days=30: alice at -10 d is in, bob at -40 d is out.
    add_commits(db_conn, synced, "alice", committed_at=AS_OF - 10 * DAY)
    add_commits(db_conn, synced, "bob", committed_at=AS_OF - 40 * DAY)

    result = get_contributor_stats(db_conn, "encode/httpx", days=30)

    assert (result.days, result.active_contributors, result.commits_counted) == (30, 1, 1)


@pytest.mark.parametrize(
    ("commits_per_author", "expected"),
    [
        ([5], 1),  # One author: 5/5.
        ([2, 2], 1),  # 2/4 is exactly 50%: enough.
        ([3, 2, 1], 1),  # 3/6 = 50%.
        ([2, 2, 1, 1], 2),  # 2/6 < 50%; 4/6 ≥ 50%.
        ([1, 1, 1, 1, 1], 3),  # 2/5 < 50%; 3/5 ≥ 50%.
    ],
)
def test_authors_for_half_of_commits(db_conn, synced, commits_per_author, expected):
    for index, count in enumerate(commits_per_author):
        add_commits(db_conn, synced, f"author{index}", count)

    result = get_contributor_stats(db_conn, "encode/httpx")

    assert result.authors_for_half_of_commits == expected
    assert result.active_contributors == len(commits_per_author)


def test_bots_do_not_change_concentration(db_conn, synced):
    # Without the bot filter, dependabot[bot]'s 10 of 13 would make it 1 author;
    # among people (alice 1, bob 1, carol 1) it takes 2.
    for login in ("alice", "bob", "carol"):
        add_commits(db_conn, synced, login)
    add_commits(db_conn, synced, "dependabot[bot]", 10)

    result = get_contributor_stats(db_conn, "encode/httpx")

    assert (result.authors_for_half_of_commits, result.active_contributors) == (2, 3)


def test_name_matches_ignoring_case(db_conn, synced):
    add_commits(db_conn, synced, "alice")

    result = get_contributor_stats(db_conn, "ENCODE/Httpx")

    assert (result.full_name, result.active_contributors) == ("encode/httpx", 1)


def test_other_repos_commits_are_ignored(db_conn, synced, load_fixture):
    # The other repo (id 1) has 5 commits by bob; ours has 1 by alice.
    other = parse_repo(load_fixture("repo.json"), load_fixture("community_profile.json"))
    upsert_repo(db_conn, other | {"id": 1, "full_name": "other/repo"})
    add_commits(db_conn, synced, "alice")
    add_commits(db_conn, 1, "bob", 5)

    result = get_contributor_stats(db_conn, "encode/httpx")

    assert numbers(result) == (1, 1, 1, 0, 0)
