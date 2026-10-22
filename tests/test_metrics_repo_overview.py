"""get_repo_overview against a real Postgres (TEST_DATABASE_URL). Skipped when it isn't set."""

from repo_health.collector.repos import parse_repo, upsert_repo
from repo_health.collector.sync_runs import finish_run, start_run
from repo_health.metrics.repo_overview import get_repo_overview


def test_known_repo_matches_ignoring_case(db_conn, repo_id, load_fixture):
    repo = load_fixture("repo.json")

    overview = get_repo_overview(db_conn, "ENCODE/HTTPX")

    assert overview.full_name == "encode/httpx"
    assert overview.stars == repo["stargazers_count"]
    assert overview.forks == repo["forks_count"]
    assert overview.open_issues == repo["open_issues_count"]
    assert overview.license == repo["license"]["spdx_id"]
    assert overview.archived is repo["archived"]
    assert overview.data_as_of is None


def test_snapshot_at_is_when_the_repo_row_was_saved(db_conn, repo_id):
    saved_at = db_conn.execute(
        "SELECT snapshot_at FROM repos WHERE id = %s", (repo_id,)
    ).fetchone()[0]

    assert get_repo_overview(db_conn, "encode/httpx").snapshot_at == saved_at


def test_unknown_repo_returns_none(db_conn, repo_id):
    assert get_repo_overview(db_conn, "nobody/nothing") is None


def test_newest_snapshot_wins_when_names_differ_only_by_case(db_conn, repo_id, load_fixture):
    stale = parse_repo(load_fixture("repo.json"), load_fixture("community_profile.json"))
    upsert_repo(db_conn, stale | {"id": 1, "full_name": "ENCODE/HTTPX"})
    # UPSERT_REPO always stores now(), so make the stale row older by hand.
    db_conn.execute("UPDATE repos SET snapshot_at = '2020-01-01T00:00:00Z' WHERE id = 1")

    overview = get_repo_overview(db_conn, "Encode/Httpx")

    assert overview.full_name == "encode/httpx"


def test_data_as_of_comes_from_the_success_run(db_conn, repo_id):
    ok = start_run(db_conn, "encode/httpx")
    finish_run(db_conn, ok, "success", 42, full_name="encode/httpx")
    success_at = db_conn.execute(
        "SELECT finished_at FROM sync_runs WHERE id = %s", (ok,)
    ).fetchone()[0]

    assert get_repo_overview(db_conn, "encode/httpx").data_as_of == success_at
