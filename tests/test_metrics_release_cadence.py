"""get_release_cadence against a real Postgres (TEST_DATABASE_URL). Skipped if it's unset."""

from datetime import UTC, datetime, timedelta

from repo_health.collector.repos import parse_repo, upsert_repo
from repo_health.metrics.release_cadence import get_release_cadence

AS_OF = datetime(2026, 10, 20, tzinfo=UTC)
DAY = timedelta(days=1)

INSERT_RELEASE = """
INSERT INTO releases (id, repo_id, tag, is_prerelease, is_draft, published_at)
VALUES (%(id)s, %(repo_id)s, %(tag)s, %(is_prerelease)s, %(is_draft)s, %(published_at)s)
"""


def sync(conn, repo_id) -> None:
    """One successful sync finishing at AS_OF, so data_as_of = AS_OF."""
    conn.execute(
        "INSERT INTO sync_runs (repo_full_name, repo_id, status, finished_at)"
        " VALUES ('encode/httpx', %s, 'success', %s)",
        (repo_id, AS_OF),
    )


def add_release(conn, repo_id, release_id, tag, published_at, prerelease=False, draft=False):
    row = {
        "id": release_id,
        "repo_id": repo_id,
        "tag": tag,
        "is_prerelease": prerelease,
        "is_draft": draft,
        "published_at": published_at,
    }
    conn.execute(INSERT_RELEASE, row)


def test_unknown_repo_returns_none(db_conn, repo_id):
    sync(db_conn, repo_id)

    assert get_release_cadence(db_conn, "nobody/nothing") is None


def test_no_complete_snapshot_gives_all_none_with_note(db_conn, repo_id):
    # No success sync run, so data_as_of is NULL; the release is ignored.
    add_release(db_conn, repo_id, 1, "v1", AS_OF - DAY)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert result.note == "no complete snapshot"
    assert result.data_as_of is None
    numbers = [
        result.latest_release_tag,
        result.latest_release_at,
        result.days_since_latest_release,
        result.releases_last_365_days,
        result.median_gap_days,
        result.gaps_counted,
        result.recent_release_tags,
        result.releases_counted,
    ]
    assert numbers == [None] * 8


def test_no_releases_gives_note_and_zero_counts(db_conn, repo_id):
    sync(db_conn, repo_id)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert result.note == "no GitHub releases"
    assert result.data_as_of == AS_OF
    assert (result.latest_release_tag, result.latest_release_at) == (None, None)
    assert (result.days_since_latest_release, result.median_gap_days) == (None, None)
    assert (result.releases_counted, result.releases_last_365_days) == (0, 0)
    assert (result.gaps_counted, result.recent_release_tags) == (0, [])


def test_prereleases_and_drafts_are_not_releases(db_conn, repo_id):
    sync(db_conn, repo_id)
    add_release(db_conn, repo_id, 1, "v2.0rc1", AS_OF - DAY, prerelease=True)
    add_release(db_conn, repo_id, 2, "v2.0", AS_OF - DAY, draft=True)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert (result.note, result.releases_counted) == ("no GitHub releases", 0)


def test_releases_after_data_as_of_or_unpublished_are_ignored(db_conn, repo_id):
    # Only v1 counts: v2 is published after data_as_of, v3 has no published_at.
    sync(db_conn, repo_id)
    add_release(db_conn, repo_id, 1, "v1", AS_OF - 10 * DAY)
    add_release(db_conn, repo_id, 2, "v2", AS_OF + DAY)
    add_release(db_conn, repo_id, 3, "v3", None)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert result.releases_counted == 1
    assert (result.latest_release_tag, result.days_since_latest_release) == ("v1", 10.0)


def test_release_exactly_at_data_as_of_is_counted(db_conn, repo_id):
    sync(db_conn, repo_id)
    add_release(db_conn, repo_id, 1, "v1", AS_OF)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert (result.latest_release_at, result.days_since_latest_release) == (AS_OF, 0.0)


def test_one_release_has_no_gap(db_conn, repo_id):
    sync(db_conn, repo_id)
    add_release(db_conn, repo_id, 1, "v1", AS_OF - 3 * DAY)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert result.median_gap_days is None
    assert (result.gaps_counted, result.recent_release_tags) == (0, ["v1"])
    assert result.note is None


def test_two_releases_have_one_gap(db_conn, repo_id):
    # v1 at -10 d, v2 at -4 d: one gap of 6 days, 4 days since the latest.
    sync(db_conn, repo_id)
    add_release(db_conn, repo_id, 1, "v1", AS_OF - 10 * DAY)
    add_release(db_conn, repo_id, 2, "v2", AS_OF - 4 * DAY)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert (result.median_gap_days, result.gaps_counted) == (6.0, 1)
    assert (result.latest_release_tag, result.days_since_latest_release) == ("v2", 4.0)


def test_gaps_use_only_the_last_5_but_count_uses_all(db_conn, repo_id):
    # 7 releases at -100, -90, -10, -9, -7, -4, -3 days. The last 5 are -10 ... -3,
    # gaps 1, 2, 3, 1 → sorted 1, 1, 2, 3 → median (1 + 2) / 2 = 1.5.
    # The old 80-day and 10-day gaps (before the last 5) don't count.
    sync(db_conn, repo_id)
    for release_id, days_ago in enumerate([100, 90, 10, 9, 7, 4, 3], start=1):
        add_release(db_conn, repo_id, release_id, f"v{release_id}", AS_OF - days_ago * DAY)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert (result.median_gap_days, result.gaps_counted) == (1.5, 4)
    assert result.recent_release_tags == ["v3", "v4", "v5", "v6", "v7"]
    assert result.releases_counted == 7


def test_median_of_odd_gaps_is_the_middle_one(db_conn, repo_id):
    # 4 releases at -20, -10, -8, -1 days: gaps 10, 2, 7 → sorted 2, 7, 10 → median 7.
    sync(db_conn, repo_id)
    for release_id, days_ago in enumerate([20, 10, 8, 1], start=1):
        add_release(db_conn, repo_id, release_id, f"v{release_id}", AS_OF - days_ago * DAY)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert (result.median_gap_days, result.gaps_counted) == (7.0, 3)


def test_order_is_by_published_at_not_tag_or_id(db_conn, repo_id):
    # Ids and tags run the other way to the dates: v10 (id 3) was published first.
    sync(db_conn, repo_id)
    add_release(db_conn, repo_id, 1, "v8", AS_OF - 1 * DAY)
    add_release(db_conn, repo_id, 2, "v9", AS_OF - 5 * DAY)
    add_release(db_conn, repo_id, 3, "v10", AS_OF - 9 * DAY)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert result.recent_release_tags == ["v10", "v9", "v8"]
    assert result.latest_release_tag == "v8"


def test_releases_published_at_the_same_moment_are_ordered_by_id(db_conn, repo_id):
    # v1.0.1 (id 2) and v1.0.0 (id 1) at the same time: id 1 comes first, gap 0.
    # The latest is the one with the higher id.
    sync(db_conn, repo_id)
    add_release(db_conn, repo_id, 2, "v1.0.1", AS_OF - DAY)
    add_release(db_conn, repo_id, 1, "v1.0.0", AS_OF - DAY)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert result.recent_release_tags == ["v1.0.0", "v1.0.1"]
    assert result.latest_release_tag == "v1.0.1"
    assert (result.median_gap_days, result.gaps_counted) == (0.0, 1)


def test_releases_last_365_days_window(db_conn, repo_id):
    # Window (AS_OF - 365 days, AS_OF]: exactly 365 days ago is out, 364 days ago is in.
    sync(db_conn, repo_id)
    add_release(db_conn, repo_id, 1, "v1", AS_OF - 365 * DAY)
    add_release(db_conn, repo_id, 2, "v2", AS_OF - 364 * DAY)
    add_release(db_conn, repo_id, 3, "v3", AS_OF)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert (result.releases_last_365_days, result.releases_counted) == (2, 3)


def test_name_matches_ignoring_case(db_conn, repo_id):
    sync(db_conn, repo_id)
    add_release(db_conn, repo_id, 1, "v1", AS_OF - DAY)

    result = get_release_cadence(db_conn, "ENCODE/Httpx")

    assert (result.full_name, result.releases_counted) == ("encode/httpx", 1)


def test_other_repos_releases_are_ignored(db_conn, repo_id, load_fixture):
    # The other repo (id 1) has a newer release; ours has only v1.
    sync(db_conn, repo_id)
    other = parse_repo(load_fixture("repo.json"), load_fixture("community_profile.json"))
    upsert_repo(db_conn, other | {"id": 1, "full_name": "other/repo"})
    add_release(db_conn, repo_id, 1, "v1", AS_OF - 10 * DAY)
    add_release(db_conn, 1, 2, "other-v2", AS_OF - DAY)

    result = get_release_cadence(db_conn, "encode/httpx")

    assert (result.releases_counted, result.latest_release_tag) == (1, "v1")
    assert result.recent_release_tags == ["v1"]
