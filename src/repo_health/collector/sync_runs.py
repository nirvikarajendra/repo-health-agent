"""Record each repo's collector run in sync_runs (status, requests used, error)."""

import psycopg

INSERT_RUN = """
INSERT INTO sync_runs (repo_full_name, status)
VALUES (%(full_name)s, 'running')
RETURNING id
"""

FINISH_RUN = """
UPDATE sync_runs
SET status = %(status)s,
    finished_at = now(),
    requests_used = %(requests_used)s,
    error = %(error)s,
    repo_full_name = COALESCE(%(full_name)s, repo_full_name)
WHERE id = %(run_id)s
"""


def start_run(conn: psycopg.Connection, full_name: str) -> int:
    """Insert a 'running' row and commit it, so a crashed run is still visible."""
    run_id = conn.execute(INSERT_RUN, {"full_name": full_name}).fetchone()[0]
    conn.commit()
    return run_id


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    status: str,
    requests_used: int,
    error: str | None = None,
    full_name: str | None = None,
) -> None:
    """Record how the run ended. `full_name`, if given, replaces the name as typed."""
    params = {
        "run_id": run_id,
        "status": status,
        "requests_used": requests_used,
        "error": error,
        "full_name": full_name,
    }
    conn.execute(FINISH_RUN, params)
    conn.commit()
