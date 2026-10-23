"""get_bug_close_rate: share of bugs closed as completed within 30 days."""

import psycopg
from psycopg.rows import dict_row

from repo_health.metrics.models import BugCloseRate

# Rules: .claude/skills/add-metric/definitions.md. coalesce() keeps a NULL state_reason
# from silently dropping a closed bug; `%%` is a literal % for psycopg.
BUG_CLOSE_RATE = r"""
WITH repo AS (
    SELECT r.id, r.full_name, d.data_as_of
    FROM repos r
    JOIN repo_data_as_of d ON d.repo_id = r.id
    WHERE lower(r.full_name) = lower(%(repo)s)
    ORDER BY r.snapshot_at DESC
    LIMIT 1
),
bugs AS (
    SELECT i.*
    FROM issues i
    JOIN repo r ON i.repo_id = r.id
    WHERE NOT i.is_pull_request
      AND i.created_at <= r.data_as_of
      AND EXISTS (
          SELECT 1 FROM unnest(i.labels) AS label
          WHERE label ~* '\mbug\M' AND label !~* '\mnot[\s_-]+a[\s_-]+bug\M'
      )
),
counted AS (
    SELECT b.number, b.created_at,
           b.state = 'closed'
           AND coalesce(b.state_reason, 'completed') = 'completed'
           AND b.closed_at <= b.created_at + interval '30 days'
           AND b.closed_at <= r.data_as_of AS fixed
    FROM bugs b
    CROSS JOIN repo r
    WHERE b.author_login IS DISTINCT FROM 'Copilot'
      AND coalesce(b.author_login NOT LIKE '%%[bot]', true)
      AND b.created_at > r.data_as_of - %(days)s * interval '1 day'
      AND b.created_at <= r.data_as_of - interval '30 days'
      AND NOT (
          b.state = 'closed'
          AND b.closed_at <= r.data_as_of
          AND coalesce(b.state_reason IN ('not_planned', 'duplicate'), false)
      )
)
SELECT r.full_name, r.data_as_of,
       (SELECT count(*) FROM bugs) AS labelled_bug_issues,
       (SELECT count(*) FROM counted) AS bugs_counted,
       (SELECT count(*) FROM counted WHERE fixed) AS bugs_fixed,
       (
           SELECT coalesce((array_agg(number ORDER BY created_at, number))[1:10], '{}')
           FROM counted
           WHERE NOT fixed
       ) AS unfixed_bug_numbers
FROM repo r
"""


def get_bug_close_rate(conn: psycopg.Connection, repo: str, days: int = 365) -> BugCloseRate | None:
    """Return the bug close rate for `repo` over the last `days`, or None if it isn't tracked."""
    # bool is a subclass of int in Python, so True would otherwise pass as 1.
    if isinstance(days, bool) or not isinstance(days, int) or not 31 <= days <= 365:
        raise ValueError(f"days must be 31-365, got {days}")
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(BUG_CLOSE_RATE, {"repo": repo, "days": days}).fetchone()
    if row is None:
        return None
    if row["data_as_of"] is None or row["labelled_bug_issues"] == 0:
        return BugCloseRate(
            full_name=row["full_name"],
            days=days,
            rate=None,
            bugs_counted=None,
            bugs_fixed=None,
            unfixed_bug_numbers=None,
            # 0 explains "not labelled"; no snapshot means no numbers at all.
            labelled_bug_issues=None if row["data_as_of"] is None else 0,
            data_as_of=row["data_as_of"],
            note="no complete snapshot" if row["data_as_of"] is None else "not labelled",
        )
    counted = row["bugs_counted"]
    rate = row["bugs_fixed"] / counted if counted else None
    return BugCloseRate(**row, days=days, rate=rate, note=None)
