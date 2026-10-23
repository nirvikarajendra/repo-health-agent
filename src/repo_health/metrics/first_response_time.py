"""get_first_response_time: how fast maintainers first reply to outside issues."""

import psycopg
from psycopg.rows import dict_row

from repo_health.metrics.models import FirstResponseTime

ISSUES_ONLY = "Only issues are counted; Discussions are not included."

# Rules: .claude/skills/add-metric/definitions.md. Window is (data_as_of - days, data_as_of].
# A NULL login is a person (not a bot, not a maintainer), so the bot checks use coalesce and
# the "not the issue's author" check uses IS DISTINCT FROM. `%%` is a literal % for psycopg.
FIRST_RESPONSE_TIME = """
WITH repo AS (
    SELECT r.id, r.full_name, d.data_as_of
    FROM repos r
    JOIN repo_data_as_of d ON d.repo_id = r.id
    WHERE lower(r.full_name) = lower(%(repo)s)
    ORDER BY r.snapshot_at DESC
    LIMIT 1
)
SELECT r.full_name, r.data_as_of,
       percentile_cont(0.5) WITHIN GROUP (
           ORDER BY extract(epoch FROM f.first_at - i.created_at)::float8 / 3600
       ) AS median_hours,
       count(i.number) AS issues_counted,
       count(i.number) FILTER (WHERE f.first_at IS NULL) AS issues_without_response,
       coalesce(
           (array_agg(i.number ORDER BY i.created_at, i.number)
               FILTER (WHERE f.first_at IS NULL AND i.number IS NOT NULL))[1:10],
           '{}'
       ) AS unanswered_issue_numbers,
       count(i.number) FILTER (WHERE f.first_at IS NULL AND s.outcome = 'completed')
           AS unanswered_closed_completed,
       count(i.number) FILTER (WHERE f.first_at IS NULL AND s.outcome = 'not_planned')
           AS unanswered_closed_not_planned,
       count(i.number) FILTER (WHERE f.first_at IS NULL AND s.outcome = 'open')
           AS unanswered_still_open
FROM repo r
LEFT JOIN issues i
       ON i.repo_id = r.id
      AND NOT i.is_pull_request
      AND i.created_at > r.data_as_of - %(days)s * interval '1 day'
      AND i.created_at <= r.data_as_of
      AND i.author_association NOT IN ('OWNER', 'MEMBER', 'COLLABORATOR')
      AND i.author_login IS DISTINCT FROM 'Copilot'
      AND coalesce(i.author_login NOT LIKE '%%[bot]', true)
LEFT JOIN LATERAL (
    SELECT min(c.created_at) AS first_at
    FROM comments c
    WHERE c.repo_id = r.id
      AND c.issue_number = i.number
      AND c.created_at <= r.data_as_of
      AND c.author_association IN ('OWNER', 'MEMBER', 'COLLABORATOR')
      AND c.author_login IS NOT NULL
      AND c.author_login NOT LIKE '%%[bot]'
      AND c.author_login <> 'Copilot'
      AND c.author_login IS DISTINCT FROM i.author_login
) f ON true
-- The issue's state at data_as_of: closing after data_as_of still counts as open.
LEFT JOIN LATERAL (
    SELECT CASE
        WHEN i.state <> 'closed' OR i.closed_at > r.data_as_of THEN 'open'
        WHEN i.state_reason IN ('not_planned', 'duplicate') THEN 'not_planned'
        ELSE 'completed'
    END AS outcome
) s ON true
GROUP BY r.full_name, r.data_as_of
"""


def get_first_response_time(
    conn: psycopg.Connection, repo: str, days: int = 90
) -> FirstResponseTime | None:
    """Return first response time for `repo` over the last `days`, or None if it isn't tracked."""
    # bool is a subclass of int in Python, so True would otherwise pass as 1.
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        raise ValueError(f"days must be 1-365, got {days}")
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(FIRST_RESPONSE_TIME, {"repo": repo, "days": days}).fetchone()
    if row is None:
        return None
    if row["data_as_of"] is None:
        return FirstResponseTime(
            full_name=row["full_name"],
            days=days,
            median_hours=None,
            issues_counted=None,
            issues_without_response=None,
            unanswered_issue_numbers=None,
            unanswered_closed_completed=None,
            unanswered_closed_not_planned=None,
            unanswered_still_open=None,
            data_as_of=None,
            note="no complete snapshot",
        )
    return FirstResponseTime(**row, days=days, note=ISSUES_ONLY)
