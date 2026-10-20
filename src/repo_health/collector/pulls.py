"""Collect pull request details that the issues endpoint doesn't return."""

import httpx
import psycopg

from repo_health.collector.github import iter_pages


def parse_pull(item: dict) -> dict:
    return {
        "number": item["number"],
        "is_draft": item.get("draft") or False,
        "base_ref": item["base"]["ref"],
        "merged_at": item.get("merged_at"),
    }


UPSERT_PULL = """
INSERT INTO pull_requests (repo_id, number, is_draft, merged_at, base_ref)
VALUES (%(repo_id)s, %(number)s, %(is_draft)s, %(merged_at)s, %(base_ref)s)
ON CONFLICT (repo_id, number) DO UPDATE SET
    is_draft = EXCLUDED.is_draft,
    merged_at = EXCLUDED.merged_at,
    base_ref = EXCLUDED.base_ref
"""


def upsert_pulls(conn: psycopg.Connection, repo_id: int, items: list[dict]) -> set[int]:
    """Save one page of PRs and return their numbers."""
    rows = [parse_pull(item) | {"repo_id": repo_id} for item in items]
    if rows:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_PULL, rows)
        conn.commit()  # Save each page, so a crash loses at most one.
    return {row["number"] for row in rows}


def collect_pulls(
    conn: psycopg.Connection,
    client: httpx.Client,
    repo_id: int,
    full_name: str,
    since: str,
) -> int:
    """Save ALL open PRs plus closed PRs updated since `since`.

    The pulls endpoint has no `since` filter, so closed PRs are sorted by last update
    (newest first) and paging stops at the first PR older than `since`.
    Returns the number of distinct PRs saved.
    """
    path = f"/repos/{full_name}/pulls"
    seen: set[int] = set()

    for page in iter_pages(client, path, {"state": "open"}):
        seen |= upsert_pulls(conn, repo_id, page)

    closed = {"state": "closed", "sort": "updated", "direction": "desc"}
    for page in iter_pages(client, path, closed):
        # Both are UTC timestamps in the same format, so string order is time order.
        recent = [item for item in page if item["updated_at"] >= since]
        seen |= upsert_pulls(conn, repo_id, recent)
        if len(recent) < len(page):
            break

    return len(seen)
