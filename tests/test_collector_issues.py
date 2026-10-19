from conftest import load_fixture

from repo_health.collector.issues import (
    collect_comments,
    collect_issues,
    parse_comment,
    parse_issue,
)

SINCE = "2025-10-19T00:00:00Z"


def test_parse_issue_marks_pull_requests():
    for item in load_fixture("issues.json"):
        row = parse_issue(item)
        assert row["is_pull_request"] == ("pull_request" in item)
        assert all(isinstance(name, str) for name in row["labels"])


def test_parse_comment_takes_issue_number_from_url():
    for item in load_fixture("issue_comments.json"):
        row = parse_comment(item)
        assert item["issue_url"].endswith(f"/issues/{row['issue_number']}")


def test_parse_issue_handles_deleted_user():
    item = load_fixture("issues.json")[0] | {"user": None}
    assert parse_issue(item)["author_login"] is None


def test_collect_issues_includes_old_open_issues_and_counts_each_once(fake_conn, fake_github):
    old_open = load_fixture("issues.json")[0] | {"number": 1, "state": "open"}
    recent = load_fixture("issues.json")[0] | {"number": 2}
    client = fake_github(
        {
            ("/repos/o/r/issues", "open"): [old_open],  # no `since`: stale open issue
            ("/repos/o/r/issues", "all"): [old_open, recent],  # also seen here
        }
    )

    n = collect_issues(fake_conn, client, repo_id=42, full_name="o/r", since=SINCE)

    assert n == 2  # issue 1 was fetched twice but counted once
    assert {row["number"] for row in fake_conn.rows} == {1, 2}
    assert all(row["repo_id"] == 42 for row in fake_conn.rows)


def test_collect_comments_saves_parsed_rows(fake_conn, fake_github):
    comments = load_fixture("issue_comments.json")
    client = fake_github({("/repos/o/r/issues/comments", None): comments})

    n = collect_comments(fake_conn, client, repo_id=42, full_name="o/r", since=SINCE)

    assert n == len(comments)
    assert all(row["repo_id"] == 42 and "issue_number" in row for row in fake_conn.rows)
