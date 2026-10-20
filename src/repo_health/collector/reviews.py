"""Collect pull request reviews (who reviewed, the verdict and when)."""

import httpx
import psycopg

from repo_health.collector.github import iter_pages

# PRs the pulls step fetched in this run: all open, plus those updated since `since`.
# Rows from earlier runs stay in `pull_requests`, so filter on this run's window.
SELECT_PR_NUMBERS = """
SELECT p.number
FROM pull_requests p
JOIN issues i ON i.repo_id = p.repo_id AND i.number = p.number
WHERE p.repo_id = %(repo_id)s
  AND (i.state = 'open' OR i.updated_at >= %(since)s)
ORDER BY p.number
"""


def parse_review(item: dict, pr_number: int) -> dict:
    return {
        "id": item["id"],
        "pr_number": pr_number,
        # `user` is null when the reviewer's account was deleted.
        "reviewer_login": (item.get("user") or {}).get("login"),
        "author_association": item["author_association"],
        "state": item["state"],
        "submitted_at": item.get("submitted_at"),
    }


UPSERT_REVIEW = """
INSERT INTO reviews (
    id, repo_id, pr_number, reviewer_login, author_association, state, submitted_at
)
VALUES (
    %(id)s, %(repo_id)s, %(pr_number)s, %(reviewer_login)s, %(author_association)s,
    %(state)s, %(submitted_at)s
)
ON CONFLICT (id) DO UPDATE SET
    reviewer_login = EXCLUDED.reviewer_login,
    author_association = EXCLUDED.author_association,
    state = EXCLUDED.state,
    submitted_at = EXCLUDED.submitted_at
"""


def collect_reviews(
    conn: psycopg.Connection,
    client: httpx.Client,
    repo_id: int,
    full_name: str,
    pr_numbers: list[int],
) -> int:
    """Save every review on each PR in `pr_numbers`. Returns the number of distinct reviews saved.

    GitHub has no repo-wide reviews endpoint, so this makes at least one request per PR.
    """
    seen: set[int] = set()
    for pr_number in pr_numbers:
        for page in iter_pages(client, f"/repos/{full_name}/pulls/{pr_number}/reviews", {}):
            rows = [parse_review(item, pr_number) | {"repo_id": repo_id} for item in page]
            if rows:  # A PR with no reviews yields one empty page.
                with conn.cursor() as cur:
                    cur.executemany(UPSERT_REVIEW, rows)
            seen.update(row["id"] for row in rows)
    return len(seen)
