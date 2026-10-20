"""Collect GitHub data for one repo.

Run with: uv run python -m repo_health.collector encode/httpx
"""

import sys
from datetime import UTC, datetime, timedelta

from repo_health.collector.commits import collect_commits
from repo_health.collector.github import make_client
from repo_health.collector.issues import collect_comments, collect_issues
from repo_health.collector.pulls import collect_pulls
from repo_health.collector.releases import collect_releases
from repo_health.collector.repos import collect_repo
from repo_health.collector.reviews import SELECT_PR_NUMBERS, collect_reviews
from repo_health.db import connect

WINDOW_DAYS = 365


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m repo_health.collector OWNER/REPO")
    full_name = sys.argv[1]
    since = (datetime.now(UTC) - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with connect() as conn, make_client() as client:
        # Commit after each step so a failure later (e.g. rate limit) keeps finished work.
        repo = collect_repo(conn, client, full_name)
        conn.commit()
        print(f"Saved {repo['full_name']}: {repo['stars']} stars")

        n = collect_issues(conn, client, repo["id"], full_name, since)
        conn.commit()
        print(f"Saved {n} issues and PRs (all open + updated in the last {WINDOW_DAYS} days)")

        n = collect_comments(conn, client, repo["id"], full_name, since)
        conn.commit()
        print(f"Saved {n} comments")

        n = collect_pulls(conn, client, repo["id"], full_name, since)
        conn.commit()
        print(f"Saved {n} pull requests (all open + closed updated in the last {WINDOW_DAYS} days)")

        params = {"repo_id": repo["id"], "since": since}
        pr_numbers = [row[0] for row in conn.execute(SELECT_PR_NUMBERS, params)]
        n = collect_reviews(conn, client, repo["id"], full_name, pr_numbers)
        conn.commit()
        print(f"Saved {n} reviews on {len(pr_numbers)} pull requests")

        n = collect_releases(conn, client, repo["id"], full_name)
        conn.commit()
        print(f"Saved {n} releases")

        n = collect_commits(conn, client, repo["id"], full_name, since)
        conn.commit()
        print(f"Saved {n} commits from the last {WINDOW_DAYS} days")


if __name__ == "__main__":
    main()
