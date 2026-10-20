"""Collect commits on the default branch (who committed and when)."""

import httpx
import psycopg

from repo_health.collector.github import iter_pages


def parse_commit(item: dict) -> dict:
    return {
        "sha": item["sha"],
        # `author` is the GitHub account, null when the commit email isn't linked to one.
        "author_login": (item.get("author") or {}).get("login"),
        "committed_at": item["commit"]["committer"]["date"],
    }


UPSERT_COMMIT = """
INSERT INTO commits (repo_id, sha, author_login, committed_at)
VALUES (%(repo_id)s, %(sha)s, %(author_login)s, %(committed_at)s)
ON CONFLICT (repo_id, sha) DO UPDATE SET
    author_login = EXCLUDED.author_login,
    committed_at = EXCLUDED.committed_at
"""


def collect_commits(
    conn: psycopg.Connection,
    client: httpx.Client,
    repo_id: int,
    full_name: str,
    since: str,
) -> int:
    """Save commits since `since`. Returns the number of distinct commits saved.

    GitHub's `since` for commits filters on the committer date, the same date stored.
    """
    seen: set[str] = set()
    for page in iter_pages(client, f"/repos/{full_name}/commits", {"since": since}):
        rows = [parse_commit(item) | {"repo_id": repo_id} for item in page]
        if rows:
            with conn.cursor() as cur:
                cur.executemany(UPSERT_COMMIT, rows)
            conn.commit()  # Save each page, so a crash loses at most one.
        seen.update(row["sha"] for row in rows)
    return len(seen)
