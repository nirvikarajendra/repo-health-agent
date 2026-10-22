"""list_repos: which repos are tracked, and how fresh their data is."""

import psycopg

from repo_health.metrics.models import TrackedRepo

# data_as_of comes from the repo_data_as_of view (migration 003), shared by every tool.
# A repo with no successful run is still listed, with data_as_of NULL.
LIST_REPOS = """
SELECT r.full_name, d.data_as_of
FROM repos r
JOIN repo_data_as_of d ON d.repo_id = r.id
ORDER BY r.full_name
"""


def list_repos(conn: psycopg.Connection) -> list[TrackedRepo]:
    rows = conn.execute(LIST_REPOS).fetchall()
    return [TrackedRepo(full_name=name, data_as_of=as_of) for name, as_of in rows]
