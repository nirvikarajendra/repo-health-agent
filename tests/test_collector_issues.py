from repo_health.collector.issues import (
    collect_comments,
    collect_issues,
    parse_comment,
    parse_issue,
)

SINCE = "2025-10-19T00:00:00Z"


def test_parse_issue_marks_pull_requests(load_fixture):
    for item in load_fixture("issues.json"):
        row = parse_issue(item)
        assert row["is_pull_request"] == ("pull_request" in item)
        assert all(isinstance(name, str) for name in row["labels"])


def test_parse_comment_takes_issue_number_from_url(load_fixture):
    for item in load_fixture("issue_comments.json"):
        row = parse_comment(item)
        assert item["issue_url"].endswith(f"/issues/{row['issue_number']}")


def test_parse_issue_handles_deleted_user(load_fixture):
    item = load_fixture("issues.json")[0] | {"user": None}
    assert parse_issue(item)["author_login"] is None


def test_collect_issues_includes_old_open_issues_and_counts_each_once(
    fake_conn, fake_github, load_fixture
):
    old_open = load_fixture("issues.json")[0] | {"number": 1, "state": "open"}
    recent = load_fixture("issues.json")[0] | {"number": 2}
    client = fake_github(
        [
            # Open issues are fetched without `since`, so stale ones are included.
            ("/repos/o/r/issues", {"state": "open"}, [old_open]),
            # Two pages; issue 1 appears in both queries.
            (
                "/repos/o/r/issues",
                {"state": "all", "since": SINCE},
                [old_open],
                [recent],
            ),
        ]
    )

    n = collect_issues(fake_conn, client, repo_id=42, full_name="o/r", since=SINCE)

    assert n == 2  # Issue 1 is counted once.
    assert fake_conn.commits == 3  # One per page with rows.
    assert {row["number"] for row in fake_conn.rows} == {1, 2}
    assert all(row["repo_id"] == 42 for row in fake_conn.rows)
    assert all(row["state"] is not None for row in fake_conn.rows)  # NOT NULL in the schema.


def test_collect_comments_saves_parsed_rows(fake_conn, fake_github, load_fixture):
    comments = load_fixture("issue_comments.json")
    client = fake_github(
        [("/repos/o/r/issues/comments", {"since": SINCE}, comments[:2], comments[2:])]
    )

    n = collect_comments(fake_conn, client, repo_id=42, full_name="o/r", since=SINCE)

    assert n == len(comments)
    assert fake_conn.commits == 2  # One per page with rows.
    assert all(row["repo_id"] == 42 and "issue_number" in row for row in fake_conn.rows)
