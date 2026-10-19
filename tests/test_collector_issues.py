import json
from pathlib import Path

import httpx

from repo_health.collector.issues import (
    collect_comments,
    collect_issues,
    parse_comment,
    parse_issue,
)

FIXTURES = Path(__file__).parent / "fixtures" / "github"


def load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


def test_parse_issue_marks_pull_requests():
    for item in load("issues.json"):
        row = parse_issue(item)
        assert row["is_pull_request"] == ("pull_request" in item)
        assert all(isinstance(name, str) for name in row["labels"])


def test_parse_comment_takes_issue_number_from_url():
    for item in load("issue_comments.json"):
        row = parse_comment(item)
        assert item["issue_url"].endswith(f"/issues/{row['issue_number']}")


def test_parse_issue_handles_deleted_user():
    item = load("issues.json")[0] | {"user": None}
    assert parse_issue(item)["author_login"] is None


class FakeConnection:
    """Records the rows passed to executemany instead of writing to Postgres."""

    def __init__(self):
        self.rows: list[dict] = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def executemany(self, sql, rows):
        self.rows.extend(rows)


def fake_github(routes: dict) -> httpx.Client:
    """routes maps a (path, state) pair to the JSON list GitHub would return."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.url.path, request.url.params.get("state"))
        return httpx.Response(200, json=routes[key])

    return httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))


def test_collect_issues_includes_old_open_issues_and_counts_each_once():
    old_open = load("issues.json")[0] | {"number": 1, "state": "open"}
    recent = load("issues.json")[0] | {"number": 2}
    client = fake_github(
        {
            ("/repos/o/r/issues", "open"): [old_open],  # no `since`: stale open issue
            ("/repos/o/r/issues", "all"): [old_open, recent],  # also seen here
        }
    )
    conn = FakeConnection()

    n = collect_issues(conn, client, repo_id=42, full_name="o/r", since="2025-10-19T00:00:00Z")

    assert n == 2  # issue 1 was fetched twice but counted once
    assert {row["number"] for row in conn.rows} == {1, 2}
    assert all(row["repo_id"] == 42 for row in conn.rows)


def test_collect_comments_saves_parsed_rows():
    client = fake_github({("/repos/o/r/issues/comments", None): load("issue_comments.json")})
    conn = FakeConnection()

    n = collect_comments(conn, client, repo_id=42, full_name="o/r", since="2025-10-19T00:00:00Z")

    assert n == len(load("issue_comments.json"))
    assert all(row["repo_id"] == 42 and "issue_number" in row for row in conn.rows)
