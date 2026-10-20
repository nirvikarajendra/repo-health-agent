"""SQL tests against a real Postgres (TEST_DATABASE_URL). Skipped when it isn't set."""

import pytest

from repo_health.collector.issues import UPSERT_ISSUE, parse_issue
from repo_health.collector.pulls import UPSERT_PULL, parse_pull
from repo_health.collector.releases import UPSERT_RELEASE, parse_release
from repo_health.collector.repos import parse_repo, upsert_repo
from repo_health.collector.reviews import SELECT_PR_NUMBERS
from repo_health.collector.sync_runs import finish_run, start_run

SINCE = "2025-10-20T00:00:00Z"


@pytest.fixture
def repo_id(db_conn, load_fixture) -> int:
    """Save the encode/httpx repo row, which every data table references."""
    row = parse_repo(load_fixture("repo.json"), load_fixture("community_profile.json"))
    upsert_repo(db_conn, row)
    return row["id"]


def test_issue_upsert_twice_keeps_one_row_with_the_new_value(db_conn, repo_id, load_fixture):
    issue = parse_issue(load_fixture("issues.json")[0]) | {"repo_id": repo_id}

    db_conn.execute(UPSERT_ISSUE, issue | {"state": "open", "closed_at": None})
    db_conn.execute(UPSERT_ISSUE, issue | {"state": "closed", "closed_at": "2026-10-01T00:00:00Z"})

    rows = db_conn.execute(
        "SELECT state FROM issues WHERE repo_id = %s AND number = %s", (repo_id, issue["number"])
    ).fetchall()
    assert rows == [("closed",)]


def test_review_window_query_skips_old_closed_prs(db_conn, repo_id, load_fixture):
    issue = parse_issue(load_fixture("issues.json")[0]) | {"repo_id": repo_id}
    pull = parse_pull(load_fixture("pulls.json")[0]) | {"repo_id": repo_id}
    prs = {
        1: {"state": "open", "updated_at": "2024-01-01T00:00:00Z"},  # Old, but still open.
        2: {"state": "closed", "updated_at": "2026-09-01T00:00:00Z"},  # Closed recently.
        3: {"state": "closed", "updated_at": "2024-01-01T00:00:00Z"},  # Closed long ago.
    }
    for number, fields in prs.items():
        db_conn.execute(UPSERT_ISSUE, issue | fields | {"number": number, "is_pull_request": True})
        db_conn.execute(UPSERT_PULL, pull | {"number": number})

    rows = db_conn.execute(SELECT_PR_NUMBERS, {"repo_id": repo_id, "since": SINCE}).fetchall()

    assert [number for (number,) in rows] == [1, 2]


def test_sync_runs_record_outcome_and_github_name(db_conn):
    ok = start_run(db_conn, "Encode/HTTPX")
    finish_run(db_conn, ok, "success", 42, full_name="encode/httpx")
    failed = start_run(db_conn, "Encode/HTTPX")
    finish_run(db_conn, failed, "failed", 1, error="RuntimeError: boom")

    rows = db_conn.execute(
        "SELECT id, repo_full_name, status, requests_used, error, finished_at IS NOT NULL"
        " FROM sync_runs ORDER BY id"
    ).fetchall()

    assert rows == [
        (1, "encode/httpx", "success", 42, None, True),  # ids restart at 1 after TRUNCATE.
        (2, "Encode/HTTPX", "failed", 1, "RuntimeError: boom", True),  # No name: kept as typed.
    ]


def test_successful_run_links_to_saved_repo(db_conn, repo_id):
    run = start_run(db_conn, "Encode/HTTPX")
    finish_run(db_conn, run, "success", 42, full_name="encode/httpx")

    row = db_conn.execute(
        "SELECT repo_id, repo_full_name FROM sync_runs WHERE id = %s", (run,)
    ).fetchone()

    assert row == (repo_id, "encode/httpx")


def test_run_links_to_newest_repo_when_names_differ_only_by_case(db_conn, repo_id, load_fixture):
    stale = parse_repo(load_fixture("repo.json"), load_fixture("community_profile.json")) | {
        "id": 1,
        "full_name": "ENCODE/HTTPX",
        "snapshot_at": "2020-01-01T00:00:00Z",
    }
    upsert_repo(db_conn, stale)
    run = start_run(db_conn, "encode/httpx")
    finish_run(db_conn, run, "failed", 1, error="RuntimeError: boom")  # Used to raise here.

    row = db_conn.execute("SELECT repo_id FROM sync_runs WHERE id = %s", (run,)).fetchone()

    assert row == (repo_id,)  # The fixture's row is newer than the stale one.


def test_failed_run_links_to_saved_repo_with_github_name(db_conn, repo_id):
    run = start_run(db_conn, "Encode/HTTPX")
    finish_run(db_conn, run, "failed", 3, error="RateLimitError: GitHub rate limit reached.")

    row = db_conn.execute(
        "SELECT repo_id, repo_full_name FROM sync_runs WHERE id = %s", (run,)
    ).fetchone()

    assert row == (repo_id, "encode/httpx")  # Matched ignoring case; GitHub's spelling stored.


def test_failed_run_without_saved_repo_keeps_typed_name(db_conn):
    run = start_run(db_conn, "encode/does-not-exist")
    finish_run(db_conn, run, "failed", 1, error="HTTPStatusError: 404 Not Found")

    row = db_conn.execute(
        "SELECT repo_id, repo_full_name FROM sync_runs WHERE id = %s", (run,)
    ).fetchone()

    assert row == (None, "encode/does-not-exist")


def test_release_upsert_updates_a_draft_once_published(db_conn, repo_id, load_fixture):
    release = parse_release(load_fixture("releases.json")[0]) | {"repo_id": repo_id}

    db_conn.execute(UPSERT_RELEASE, release | {"is_draft": True, "published_at": None})
    published = {"is_draft": False, "published_at": "2026-10-01T00:00:00Z"}
    db_conn.execute(UPSERT_RELEASE, release | published)

    rows = db_conn.execute(
        "SELECT is_draft, published_at IS NOT NULL FROM releases WHERE id = %s", (release["id"],)
    ).fetchall()
    assert rows == [(False, True)]
