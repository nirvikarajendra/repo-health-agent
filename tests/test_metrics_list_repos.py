"""list_repos against a real Postgres (TEST_DATABASE_URL). Skipped when it isn't set."""

from repo_health.collector.repos import parse_repo, upsert_repo
from repo_health.collector.sync_runs import finish_run, start_run
from repo_health.metrics.list_repos import list_repos
from repo_health.metrics.models import TrackedRepo


def test_data_as_of_is_the_latest_success_not_a_later_failure(db_conn, repo_id):
    ok = start_run(db_conn, "encode/httpx")
    finish_run(db_conn, ok, "success", 42, full_name="encode/httpx")
    failed = start_run(db_conn, "encode/httpx")
    finish_run(db_conn, failed, "failed", 1, error="RuntimeError: boom")
    success_at, failed_at = (
        row[0]
        for row in db_conn.execute(
            "SELECT finished_at FROM sync_runs WHERE id IN (%s, %s) ORDER BY id", (ok, failed)
        )
    )
    assert failed_at > success_at  # The failure really is later.

    assert list_repos(db_conn) == [TrackedRepo(full_name="encode/httpx", data_as_of=success_at)]


def test_repo_without_a_successful_run_is_listed_with_no_date(db_conn, repo_id):
    failed = start_run(db_conn, "encode/httpx")
    finish_run(db_conn, failed, "failed", 1, error="RuntimeError: boom")

    assert list_repos(db_conn) == [TrackedRepo(full_name="encode/httpx", data_as_of=None)]


def test_repos_are_sorted_by_name_and_one_with_no_runs_is_listed(db_conn, repo_id, load_fixture):
    # A second repo with no sync_runs rows at all, e.g. collected before sync_runs existed.
    other = parse_repo(load_fixture("repo.json"), load_fixture("community_profile.json"))
    upsert_repo(db_conn, other | {"id": 2, "full_name": "aaa/first"})
    ok = start_run(db_conn, "encode/httpx")
    finish_run(db_conn, ok, "success", 42, full_name="encode/httpx")
    success_at = db_conn.execute(
        "SELECT finished_at FROM sync_runs WHERE id = %s", (ok,)
    ).fetchone()[0]

    assert list_repos(db_conn) == [
        TrackedRepo(full_name="aaa/first", data_as_of=None),
        TrackedRepo(full_name="encode/httpx", data_as_of=success_at),
    ]
