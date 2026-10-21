"""list_repos: which repos are tracked, and how fresh their data is."""

import psycopg

from repo_health.metrics.models import TrackedRepo

# The success filter is in the JOIN, not a WHERE, so a repo with no successful
# run is still listed (data_as_of NULL): it may hold partial data from failed runs.
LIST_REPOS = """
SELECT r.full_name, max(s.finished_at) AS data_as_of
FROM repos r
LEFT JOIN sync_runs s ON s.repo_id = r.id AND s.status = 'success'
GROUP BY r.id, r.full_name
ORDER BY r.full_name
"""


def list_repos(conn: psycopg.Connection) -> list[TrackedRepo]:
    rows = conn.execute(LIST_REPOS).fetchall()
    return [TrackedRepo(full_name=name, data_as_of=as_of) for name, as_of in rows]
