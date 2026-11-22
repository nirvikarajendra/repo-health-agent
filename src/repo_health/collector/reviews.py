"""Collect pull request reviews (who reviewed, the verdict and when)."""

import logging

import httpx
import psycopg

from repo_health.collector.github import iter_pages

log = logging.getLogger(__name__)

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

# Rows of PRs deleted on GitHub, children first. These tables only reference repos (no
# cascade), and each names the PR number differently.
DELETE_DELETED_PR_ROWS = (
    "DELETE FROM reviews WHERE repo_id = %(repo_id)s AND pr_number = ANY(%(numbers)s)",
    "DELETE FROM comments WHERE repo_id = %(repo_id)s AND issue_number = ANY(%(numbers)s)",
    "DELETE FROM pull_requests WHERE repo_id = %(repo_id)s AND number = ANY(%(numbers)s)",
    "DELETE FROM issues WHERE repo_id = %(repo_id)s AND number = ANY(%(numbers)s)",
)


def collect_reviews(
    conn: psycopg.Connection,
    client: httpx.Client,
    repo_id: int,
    full_name: str,
    pr_numbers: list[int],
) -> int:
    """Save every review on each PR in `pr_numbers`. Returns the number of distinct reviews saved.

    GitHub has no repo-wide reviews endpoint, so this makes at least one request per PR.
    A PR deleted on GitHub stays in our issues list but its reviews return 404: its rows
    are removed after the loop (same transaction, so a failed step rolls them back too).
    Any other HTTP error still fails the repo, before anything is removed.
    """
    seen: set[int] = set()
    deleted: list[int] = []
    for done, pr_number in enumerate(pr_numbers, start=1):
        try:
            for page in iter_pages(client, f"/repos/{full_name}/pulls/{pr_number}/reviews", {}):
                rows = [parse_review(item, pr_number) | {"repo_id": repo_id} for item in page]
                if rows:  # A PR with no reviews yields one empty page.
                    with conn.cursor() as cur:
                        cur.executemany(UPSERT_REVIEW, rows)
                seen.update(row["id"] for row in rows)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
            log.warning("reviews: PR #%d returned 404 (deleted on GitHub?), removing", pr_number)
            deleted.append(pr_number)
        if done % 100 == 0:
            log.info("reviews: %d/%d PRs", done, len(pr_numbers))
    if deleted:
        params = {"repo_id": repo_id, "numbers": deleted}
        for statement in DELETE_DELETED_PR_ROWS:
            conn.execute(statement, params)
        numbers = ", ".join(f"#{number}" for number in deleted)
        log.warning("Removed deleted PRs (%d): %s", len(deleted), numbers)
    return len(seen)
