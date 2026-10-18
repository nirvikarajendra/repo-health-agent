"""Collect one repo's overview into the `repos` table."""

import psycopg

from repo_health.collector.github import get_json, make_client


def parse_repo(repo: dict, community: dict) -> dict:
    """Turn the /repos and /community/profile responses into one `repos` row."""
    files = community.get("files") or {}
    license_ = repo.get("license")
    return {
        "id": repo["id"],
        "full_name": repo["full_name"],
        "description": repo.get("description"),
        "topics": repo.get("topics") or [],
        "homepage": repo.get("homepage") or None,
        "html_url": repo["html_url"],
        "stars": repo["stargazers_count"],
        "forks": repo["forks_count"],
        "open_issues": repo["open_issues_count"],
        "language": repo.get("language"),
        "license": license_["spdx_id"] if license_ else None,
        "archived": repo["archived"],
        "created_at": repo["created_at"],
        "pushed_at": repo.get("pushed_at"),
        "has_readme": files.get("readme") is not None,
        "has_contributing": files.get("contributing") is not None,
        "has_code_of_conduct": files.get("code_of_conduct") is not None,
    }


UPSERT_REPO = """
INSERT INTO repos (
    id, full_name, description, topics, homepage, html_url, stars, forks,
    open_issues, language, license, archived, created_at, pushed_at,
    has_readme, has_contributing, has_code_of_conduct, snapshot_at
) VALUES (
    %(id)s, %(full_name)s, %(description)s, %(topics)s, %(homepage)s, %(html_url)s,
    %(stars)s, %(forks)s, %(open_issues)s, %(language)s, %(license)s, %(archived)s,
    %(created_at)s, %(pushed_at)s, %(has_readme)s, %(has_contributing)s,
    %(has_code_of_conduct)s, now()
)
ON CONFLICT (id) DO UPDATE SET
    full_name = EXCLUDED.full_name,
    description = EXCLUDED.description,
    topics = EXCLUDED.topics,
    homepage = EXCLUDED.homepage,
    html_url = EXCLUDED.html_url,
    stars = EXCLUDED.stars,
    forks = EXCLUDED.forks,
    open_issues = EXCLUDED.open_issues,
    language = EXCLUDED.language,
    license = EXCLUDED.license,
    archived = EXCLUDED.archived,
    created_at = EXCLUDED.created_at,
    pushed_at = EXCLUDED.pushed_at,
    has_readme = EXCLUDED.has_readme,
    has_contributing = EXCLUDED.has_contributing,
    has_code_of_conduct = EXCLUDED.has_code_of_conduct,
    snapshot_at = EXCLUDED.snapshot_at
"""


def upsert_repo(conn: psycopg.Connection, row: dict) -> None:
    conn.execute(UPSERT_REPO, row)


def collect_repo(conn: psycopg.Connection, full_name: str) -> dict:
    """Fetch one repo from GitHub and save it. Returns the saved row."""
    with make_client() as client:
        repo = get_json(client, f"/repos/{full_name}")
        community = get_json(client, f"/repos/{full_name}/community/profile")
    row = parse_repo(repo, community)
    upsert_repo(conn, row)
    return row
