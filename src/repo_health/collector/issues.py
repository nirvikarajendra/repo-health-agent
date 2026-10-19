"""Collect issues (and PRs, which GitHub returns from the same endpoint) and comments."""

import httpx
import psycopg

from repo_health.collector.github import get_all_pages


def parse_issue(item: dict) -> dict:
    return {
        "number": item["number"],
        "is_pull_request": "pull_request" in item,
        "state": item["state"],
        "state_reason": item.get("state_reason"),
        "author_login": (item.get("user") or {}).get("login"),
        "author_association": item["author_association"],
        "labels": [label["name"] for label in item.get("labels", [])],
        "created_at": item["created_at"],
        "closed_at": item.get("closed_at"),
        "updated_at": item["updated_at"],
    }


def parse_comment(item: dict) -> dict:
    return {
        "id": item["id"],
        # issue_url ends with the issue number: .../repos/encode/httpx/issues/3456
        "issue_number": int(item["issue_url"].rsplit("/", 1)[-1]),
        "author_login": (item.get("user") or {}).get("login"),
        "author_association": item["author_association"],
        "created_at": item["created_at"],
    }


UPSERT_ISSUE = """
INSERT INTO issues (
    repo_id, number, is_pull_request, state, state_reason, author_login,
    author_association, labels, created_at, closed_at, updated_at
) VALUES (
    %(repo_id)s, %(number)s, %(is_pull_request)s, %(state)s, %(state_reason)s,
    %(author_login)s, %(author_association)s, %(labels)s, %(created_at)s,
    %(closed_at)s, %(updated_at)s
)
ON CONFLICT (repo_id, number) DO UPDATE SET
    is_pull_request = EXCLUDED.is_pull_request,
    state = EXCLUDED.state,
    state_reason = EXCLUDED.state_reason,
    author_login = EXCLUDED.author_login,
    author_association = EXCLUDED.author_association,
    labels = EXCLUDED.labels,
    closed_at = EXCLUDED.closed_at,
    updated_at = EXCLUDED.updated_at
"""

UPSERT_COMMENT = """
INSERT INTO comments (
    id, repo_id, issue_number, author_login, author_association, created_at
) VALUES (
    %(id)s, %(repo_id)s, %(issue_number)s, %(author_login)s,
    %(author_association)s, %(created_at)s
)
ON CONFLICT (id) DO UPDATE SET
    author_login = EXCLUDED.author_login,
    author_association = EXCLUDED.author_association
"""


def collect_issues(
    conn: psycopg.Connection,
    client: httpx.Client,
    repo_id: int,
    full_name: str,
    since: str,
) -> int:
    items = get_all_pages(client, f"/repos/{full_name}/issues", {"state": "all", "since": since})
    rows = [parse_issue(item) | {"repo_id": repo_id} for item in items]
    with conn.cursor() as cur:
        cur.executemany(UPSERT_ISSUE, rows)
    return len(rows)


def collect_comments(
    conn: psycopg.Connection,
    client: httpx.Client,
    repo_id: int,
    full_name: str,
    since: str,
) -> int:
    items = get_all_pages(client, f"/repos/{full_name}/issues/comments", {"since": since})
    rows = [parse_comment(item) | {"repo_id": repo_id} for item in items]
    with conn.cursor() as cur:
        cur.executemany(UPSERT_COMMENT, rows)
    return len(rows)
