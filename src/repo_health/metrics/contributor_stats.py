"""get_contributor_stats: how many people commit, and how concentrated the work is."""

import psycopg
from psycopg.rows import dict_row

from repo_health.metrics.models import ContributorStats

# Rules: .claude/skills/add-metric/definitions.md. Bot and unattributed (NULL login) commits
# are counted separately, never dropped; `%%` is a literal % for psycopg.
CONTRIBUTOR_STATS = """
WITH repo AS (
    SELECT r.id, r.full_name, d.data_as_of
    FROM repos r
    JOIN repo_data_as_of d ON d.repo_id = r.id
    WHERE lower(r.full_name) = lower(%(repo)s)
    ORDER BY r.snapshot_at DESC
    LIMIT 1
),
window_commits AS (
    SELECT c.author_login
    FROM commits c
    JOIN repo r ON c.repo_id = r.id
    WHERE c.committed_at > r.data_as_of - %(days)s * interval '1 day'
      AND c.committed_at <= r.data_as_of
),
authors AS (
    SELECT author_login, count(*) AS commits
    FROM window_commits
    WHERE author_login IS NOT NULL
      AND author_login NOT LIKE '%%[bot]'
      AND author_login <> 'Copilot'
    GROUP BY author_login
),
-- Most commits first; `running` is the commits made by the top `k` authors together.
ranked AS (
    SELECT row_number() OVER (ORDER BY commits DESC, author_login) AS k,
           sum(commits) OVER (ORDER BY commits DESC, author_login) AS running
    FROM authors
)
SELECT r.full_name, r.data_as_of,
       (SELECT count(*) FROM authors) AS active_contributors,
       (
           SELECT min(k)
           FROM ranked
           WHERE running * 2 >= (SELECT sum(commits) FROM authors)
       ) AS authors_for_half_of_commits,
       (SELECT coalesce(sum(commits), 0)::bigint FROM authors) AS commits_counted,
       (
           SELECT count(*)
           FROM window_commits
           WHERE author_login LIKE '%%[bot]' OR author_login = 'Copilot'
       ) AS bot_commits,
       (SELECT count(*) FROM window_commits WHERE author_login IS NULL) AS unattributed_commits
FROM repo r
"""


def get_contributor_stats(
    conn: psycopg.Connection, repo: str, days: int = 365
) -> ContributorStats | None:
    """Return contributor stats for `repo` over the last `days`, or None if it isn't tracked."""
    # bool is a subclass of int in Python, so True would otherwise pass as 1.
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        raise ValueError(f"days must be 1-365, got {days}")
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(CONTRIBUTOR_STATS, {"repo": repo, "days": days}).fetchone()
    if row is None:
        return None
    if row["data_as_of"] is None:
        return ContributorStats(
            full_name=row["full_name"],
            days=days,
            active_contributors=None,
            authors_for_half_of_commits=None,
            commits_counted=None,
            bot_commits=None,
            unattributed_commits=None,
            data_as_of=None,
            note="no complete snapshot",
        )
    return ContributorStats(**row, days=days, note=None)
