"""get_pr_review_time: how long outside PRs wait for a first maintainer review."""

import psycopg
from psycopg.rows import dict_row

from repo_health.metrics.models import PrReviewTime

# Rules: .claude/skills/add-metric/definitions.md. A NULL login is a person (not a bot, not a
# maintainer), hence coalesce and IS DISTINCT FROM; `%%` is a literal % for psycopg.
PR_REVIEW_TIME = """
WITH repo AS (
    SELECT r.id, r.full_name, d.data_as_of
    FROM repos r
    JOIN repo_data_as_of d ON d.repo_id = r.id
    WHERE lower(r.full_name) = lower(%(repo)s)
    ORDER BY r.snapshot_at DESC
    LIMIT 1
),
prs AS (
    SELECT i.number, i.created_at, i.author_login, i.state, i.closed_at, p.merged_at
    FROM issues i
    JOIN repo r ON i.repo_id = r.id
    JOIN pull_requests p ON p.repo_id = i.repo_id AND p.number = i.number
    WHERE i.is_pull_request
      AND NOT p.is_draft
      AND i.created_at > r.data_as_of - %(days)s * interval '1 day'
      AND i.created_at <= r.data_as_of
      AND i.author_association NOT IN ('OWNER', 'MEMBER', 'COLLABORATOR')
      AND i.author_login IS DISTINCT FROM 'Copilot'
      AND coalesce(i.author_login NOT LIKE '%%[bot]', true)
),
firsts AS (
    SELECT p.number, p.created_at,
           (
               SELECT min(v.submitted_at)
               FROM reviews v
               WHERE v.repo_id = r.id
                 AND v.pr_number = p.number
                 AND v.submitted_at <= r.data_as_of
                 AND v.author_association IN ('OWNER', 'MEMBER', 'COLLABORATOR')
                 AND v.reviewer_login IS NOT NULL
                 AND v.reviewer_login NOT LIKE '%%[bot]'
                 AND v.reviewer_login <> 'Copilot'
                 AND v.reviewer_login IS DISTINCT FROM p.author_login
           ) AS first_at,
           -- The PR's state at data_as_of: merging or closing later still counts as open.
           CASE
               WHEN p.merged_at <= r.data_as_of THEN 'merged'
               WHEN p.state = 'closed' AND p.closed_at <= r.data_as_of THEN 'closed_unmerged'
               ELSE 'open'
           END AS outcome
    FROM prs p
    CROSS JOIN repo r
)
SELECT r.full_name, r.data_as_of,
       (
           SELECT percentile_cont(0.5) WITHIN GROUP (
               ORDER BY extract(epoch FROM first_at - created_at)::float8 / 3600
           )
           FROM firsts
       ) AS median_hours,
       (SELECT count(*) FROM firsts) AS prs_counted,
       (SELECT count(*) FROM firsts WHERE first_at IS NULL) AS prs_without_review,
       (
           SELECT coalesce((array_agg(number ORDER BY created_at, number))[1:10], '{}')
           FROM firsts
           WHERE first_at IS NULL
       ) AS unreviewed_pr_numbers,
       (SELECT count(*) FROM firsts WHERE first_at IS NULL AND outcome = 'merged')
           AS unreviewed_merged,
       (SELECT count(*) FROM firsts WHERE first_at IS NULL AND outcome = 'closed_unmerged')
           AS unreviewed_closed_unmerged,
       (SELECT count(*) FROM firsts WHERE first_at IS NULL AND outcome = 'open')
           AS unreviewed_still_open
FROM repo r
"""


def get_pr_review_time(conn: psycopg.Connection, repo: str, days: int = 90) -> PrReviewTime | None:
    """Return PR review time for `repo` over the last `days`, or None if it isn't tracked."""
    # bool is a subclass of int in Python, so True would otherwise pass as 1.
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        raise ValueError(f"days must be 1-365, got {days}")
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(PR_REVIEW_TIME, {"repo": repo, "days": days}).fetchone()
    if row is None:
        return None
    if row["data_as_of"] is None:
        return PrReviewTime(
            full_name=row["full_name"],
            days=days,
            median_hours=None,
            prs_counted=None,
            prs_without_review=None,
            unreviewed_pr_numbers=None,
            unreviewed_merged=None,
            unreviewed_closed_unmerged=None,
            unreviewed_still_open=None,
            data_as_of=None,
            note="no complete snapshot",
        )
    return PrReviewTime(**row, days=days, note=None)
