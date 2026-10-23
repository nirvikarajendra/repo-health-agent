"""The agent's tools: thin wrappers around the metric functions.

ADK sends each docstring to the model as the tool's description, so they're written for it.
Every wrapper opens its own read-only connection and returns a JSON-ready dict.
"""

import psycopg

from repo_health.db import connect
from repo_health.metrics.list_repos import list_repos as fetch_repos
from repo_health.metrics.repo_overview import get_repo_overview as fetch_overview

NOT_TRACKED = {"status": "error", "error_message": "repo not tracked"}


def read_only_connection() -> psycopg.Connection:
    """A connection on which Postgres refuses any write (until the read-only role exists)."""
    conn = connect()
    conn.read_only = True
    return conn


def list_repos() -> dict:
    """List every GitHub repository the agent has data for.

    Returns:
        {"status": "success", "repos": [...]}, one entry per repo with "full_name"
        (OWNER/NAME) and "data_as_of": when that repo's data was last fully collected
        (ISO 8601, UTC), or null if it never was.
    """
    with read_only_connection() as conn:
        repos = fetch_repos(conn)
    return {"status": "success", "repos": [repo.model_dump(mode="json") for repo in repos]}


def get_repo_overview(repo: str) -> dict:
    """Get general stats for one tracked GitHub repository.

    Args:
        repo: The repository as OWNER/NAME, for example "encode/httpx" (any letter case).

    Returns:
        {"status": "success", ...} with full_name, description, stars, forks, open_issues
        (open issues plus open pull requests), language, license, archived, created_at,
        pushed_at, has_readme, has_contributing, has_code_of_conduct, snapshot_at (when
        these stats were fetched) and data_as_of (when the repo's data was last fully
        collected, ISO 8601 UTC). If the repo isn't tracked:
        {"status": "error", "error_message": "repo not tracked"}.
    """
    with read_only_connection() as conn:
        overview = fetch_overview(conn, repo)
    if overview is None:
        return dict(NOT_TRACKED)
    return {"status": "success", **overview.model_dump(mode="json")}
