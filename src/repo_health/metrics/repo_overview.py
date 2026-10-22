"""get_repo_overview: general stats for one repo, from its latest snapshot."""

import psycopg
from psycopg.rows import dict_row

from repo_health.metrics.models import RepoOverview

# Name matched ignoring case; if two rows differ only by case, the newest snapshot wins.
REPO_OVERVIEW = """
SELECT r.full_name, r.description, r.stars, r.forks, r.open_issues, r.language,
       r.license, r.archived, r.created_at, r.pushed_at, r.has_readme,
       r.has_contributing, r.has_code_of_conduct, r.snapshot_at, d.data_as_of
FROM repos r
JOIN repo_data_as_of d ON d.repo_id = r.id
WHERE lower(r.full_name) = lower(%(repo)s)
ORDER BY r.snapshot_at DESC
LIMIT 1
"""


def get_repo_overview(conn: psycopg.Connection, repo: str) -> RepoOverview | None:
    """Return the overview for `repo` (OWNER/NAME, any case), or None if it isn't tracked."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(REPO_OVERVIEW, {"repo": repo}).fetchone()
    return RepoOverview(**row) if row else None
