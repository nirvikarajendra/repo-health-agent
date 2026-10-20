"""Collect releases (tags, pre-release/draft flags and publish dates)."""

import httpx
import psycopg

from repo_health.collector.github import iter_pages


def parse_release(item: dict) -> dict:
    return {
        "id": item["id"],
        "tag": item["tag_name"],
        "is_prerelease": item.get("prerelease") or False,
        "is_draft": item.get("draft") or False,
        "published_at": item.get("published_at"),
    }


UPSERT_RELEASE = """
INSERT INTO releases (id, repo_id, tag, is_prerelease, is_draft, published_at)
VALUES (
    %(id)s, %(repo_id)s, %(tag)s, %(is_prerelease)s, %(is_draft)s, %(published_at)s
)
ON CONFLICT (id) DO UPDATE SET
    tag = EXCLUDED.tag,
    is_prerelease = EXCLUDED.is_prerelease,
    is_draft = EXCLUDED.is_draft,
    published_at = EXCLUDED.published_at
"""


def collect_releases(
    conn: psycopg.Connection,
    client: httpx.Client,
    repo_id: int,
    full_name: str,
) -> int:
    """Save every release. Returns the number of distinct releases saved.

    The endpoint has no `since` filter, and release cadence needs the full history.
    """
    seen: set[int] = set()
    for page in iter_pages(client, f"/repos/{full_name}/releases", {}):
        rows = [parse_release(item) | {"repo_id": repo_id} for item in page]
        with conn.cursor() as cur:
            cur.executemany(UPSERT_RELEASE, rows)
        seen.update(row["id"] for row in rows)
    return len(seen)
