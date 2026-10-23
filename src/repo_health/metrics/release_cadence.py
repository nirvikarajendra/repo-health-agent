"""get_release_cadence: how recently and how often a repo publishes GitHub releases."""

import psycopg
from psycopg.rows import dict_row

from repo_health.metrics.models import ReleaseCadence

# Rules: .claude/skills/add-metric/definitions.md. Releases are ordered by published_at, then
# id (so ties have a fixed order), never by tag; gaps are taken over the last 5 only.
RELEASE_CADENCE = """
WITH repo AS (
    SELECT r.id, r.full_name, d.data_as_of
    FROM repos r
    JOIN repo_data_as_of d ON d.repo_id = r.id
    WHERE lower(r.full_name) = lower(%(repo)s)
    ORDER BY r.snapshot_at DESC
    LIMIT 1
),
releases_counted AS (
    SELECT x.id, x.tag, x.published_at
    FROM releases x
    JOIN repo r ON x.repo_id = r.id
    WHERE x.published_at <= r.data_as_of
      AND NOT x.is_draft
      AND NOT x.is_prerelease
),
last5 AS (
    SELECT id, tag, published_at,
           published_at - lag(published_at) OVER (ORDER BY published_at, id) AS gap
    FROM (
        SELECT * FROM releases_counted ORDER BY published_at DESC, id DESC LIMIT 5
    ) newest
)
SELECT r.full_name, r.data_as_of,
       (SELECT tag FROM last5 ORDER BY published_at DESC, id DESC LIMIT 1) AS latest_release_tag,
       (SELECT max(published_at) FROM last5) AS latest_release_at,
       (
           SELECT extract(epoch FROM r.data_as_of - max(published_at))::float8 / 86400
           FROM last5
       ) AS days_since_latest_release,
       (
           SELECT count(*)
           FROM releases_counted
           WHERE published_at > r.data_as_of - interval '365 days'
       ) AS releases_last_365_days,
       (
           SELECT percentile_cont(0.5) WITHIN GROUP (
               ORDER BY extract(epoch FROM gap)::float8 / 86400
           )
           FROM last5
       ) AS median_gap_days,
       (SELECT count(gap) FROM last5) AS gaps_counted,
       (
           SELECT coalesce(array_agg(tag ORDER BY published_at, id), '{}')
           FROM last5
       ) AS recent_release_tags,
       (SELECT count(*) FROM releases_counted) AS releases_counted
FROM repo r
"""


def get_release_cadence(conn: psycopg.Connection, repo: str) -> ReleaseCadence | None:
    """Return the release cadence for `repo`, or None if it isn't tracked."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(RELEASE_CADENCE, {"repo": repo}).fetchone()
    if row is None:
        return None
    if row["data_as_of"] is None:
        return ReleaseCadence(
            full_name=row["full_name"],
            latest_release_tag=None,
            latest_release_at=None,
            days_since_latest_release=None,
            releases_last_365_days=None,
            median_gap_days=None,
            gaps_counted=None,
            recent_release_tags=None,
            releases_counted=None,
            data_as_of=None,
            note="no complete snapshot",
        )
    note = "no GitHub releases" if row["releases_counted"] == 0 else None
    return ReleaseCadence(**row, note=note)
