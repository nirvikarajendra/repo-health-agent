"""Collect GitHub data for one or more repos.

Run with: uv run python -m repo_health.collector encode/httpx [OWNER/REPO ...]
"""

import logging
import sys
from datetime import UTC, datetime, timedelta

import httpx
import psycopg

from repo_health.collector.commits import collect_commits
from repo_health.collector.github import make_client
from repo_health.collector.issues import collect_comments, collect_issues
from repo_health.collector.pulls import collect_pulls
from repo_health.collector.releases import collect_releases
from repo_health.collector.repos import collect_repo
from repo_health.collector.reviews import SELECT_PR_NUMBERS, collect_reviews
from repo_health.collector.sync_runs import finish_run, start_run
from repo_health.db import connect
from repo_health.logs import setup_logging

WINDOW_DAYS = 365

log = logging.getLogger(__name__)


def collect_one(conn: psycopg.Connection, client: httpx.Client, full_name: str, since: str) -> str:
    """Run every collector step for one repo. Returns GitHub's name for it."""
    # Commit after each step so a failure later (e.g. rate limit) keeps finished work.
    repo = collect_repo(conn, client, full_name)
    conn.commit()
    log.info("Saved %s: %d stars", repo["full_name"], repo["stars"])

    n = collect_issues(conn, client, repo["id"], full_name, since)
    conn.commit()
    log.info("Saved %d issues and PRs (all open + updated in the last %d days)", n, WINDOW_DAYS)

    n = collect_comments(conn, client, repo["id"], full_name, since)
    conn.commit()
    log.info("Saved %d comments", n)

    n = collect_pulls(conn, client, repo["id"], full_name, since)
    conn.commit()
    log.info(
        "Saved %d pull requests (all open + closed updated in the last %d days)", n, WINDOW_DAYS
    )

    params = {"repo_id": repo["id"], "since": since}
    pr_numbers = [row[0] for row in conn.execute(SELECT_PR_NUMBERS, params)]
    n = collect_reviews(conn, client, repo["id"], full_name, pr_numbers)
    conn.commit()
    log.info("Saved %d reviews on %d pull requests", n, len(pr_numbers))

    n = collect_releases(conn, client, repo["id"], full_name)
    conn.commit()
    log.info("Saved %d releases", n)

    n = collect_commits(conn, client, repo["id"], full_name, since)
    conn.commit()
    log.info("Saved %d commits from the last %d days", n, WINDOW_DAYS)
    return repo["full_name"]


def main() -> None:
    setup_logging()
    full_names = sys.argv[1:]
    if not full_names:
        sys.exit("Usage: python -m repo_health.collector OWNER/REPO [OWNER/REPO ...]")
    since = (datetime.now(UTC) - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    failed: list[str] = []
    requests_used = 0

    def count_request(request: httpx.Request) -> None:
        nonlocal requests_used
        requests_used += 1

    with connect() as conn, make_client() as client:
        client.event_hooks["request"].append(count_request)
        for full_name in full_names:
            log.info("Collecting %s", full_name)
            requests_used = 0
            run_id = start_run(conn, full_name)
            try:
                github_name = collect_one(conn, client, full_name, since)
            except KeyboardInterrupt:
                # Ctrl+C: record the run as failed instead of leaving it 'running', then stop.
                conn.rollback()
                finish_run(conn, run_id, "failed", requests_used, error="Interrupted")
                log.warning("Interrupted %s", full_name)
                raise
            except Exception as error:
                # Drop the failed step's uncommitted rows so the next repo starts clean.
                conn.rollback()
                log.exception("Failed %s", full_name)
                finish_run(
                    conn, run_id, "failed", requests_used, error=f"{type(error).__name__}: {error}"
                )
                failed.append(full_name)
            else:
                finish_run(conn, run_id, "success", requests_used, full_name=github_name)

    if failed:
        log.error("%d of %d repos failed: %s", len(failed), len(full_names), ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
