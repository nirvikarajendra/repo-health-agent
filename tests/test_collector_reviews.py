import logging

import httpx
import pytest

from repo_health.collector.repos import parse_repo, upsert_repo
from repo_health.collector.reviews import collect_reviews, parse_review

TABLES = ("reviews", "comments", "pull_requests", "issues")
# Each table names the PR number differently.
COUNT_ROWS = {
    "reviews": "SELECT count(*) FROM reviews WHERE repo_id = %s AND pr_number = %s",
    "comments": "SELECT count(*) FROM comments WHERE repo_id = %s AND issue_number = %s",
    "pull_requests": "SELECT count(*) FROM pull_requests WHERE repo_id = %s AND number = %s",
    "issues": "SELECT count(*) FROM issues WHERE repo_id = %s AND number = %s",
}


def save_pr(conn, repo_id: int, number: int) -> None:
    """One row per table for PR `number`, as earlier runs would have left it."""
    row_id = repo_id * 1000 + number  # Review and comment ids are unique across repos.
    conn.execute(
        "INSERT INTO issues (repo_id, number, is_pull_request, state, author_association,"
        " created_at, updated_at) VALUES (%s, %s, true, 'open', 'NONE', now(), now())",
        (repo_id, number),
    )
    conn.execute(
        "INSERT INTO pull_requests (repo_id, number, is_draft, base_ref)"
        " VALUES (%s, %s, false, 'main')",
        (repo_id, number),
    )
    conn.execute(
        "INSERT INTO comments (id, repo_id, issue_number, author_association, created_at)"
        " VALUES (%s, %s, %s, 'NONE', now())",
        (row_id, repo_id, number),
    )
    conn.execute(
        "INSERT INTO reviews (id, repo_id, pr_number, author_association, state)"
        " VALUES (%s, %s, %s, 'MEMBER', 'APPROVED')",
        (row_id, repo_id, number),
    )


def row_counts(conn, repo_id: int, number: int) -> dict[str, int]:
    return {
        table: conn.execute(COUNT_ROWS[table], (repo_id, number)).fetchone()[0] for table in TABLES
    }


ONE_ROW_EACH = dict.fromkeys(TABLES, 1)
NO_ROWS = dict.fromkeys(TABLES, 0)


def test_parse_review_reads_every_fixture_item(load_fixture):
    for item in load_fixture("reviews.json"):
        row = parse_review(item, pr_number=7)
        assert row["id"] == item["id"]
        assert row["pr_number"] == 7
        assert row["reviewer_login"] == item["user"]["login"]
        assert row["author_association"] == item["author_association"]
        assert row["state"] == item["state"]
        assert row["submitted_at"] == item["submitted_at"]


def test_parse_review_handles_deleted_reviewer(load_fixture):
    item = load_fixture("reviews.json")[0] | {"user": None}
    assert parse_review(item, pr_number=7)["reviewer_login"] is None


def test_collect_reviews_saves_every_page_with_its_pr_number(load_fixture, fake_conn, fake_github):
    reviews = load_fixture("reviews.json")
    client = fake_github(
        [
            ("/repos/o/r/pulls/1/reviews", {}, reviews[:3], reviews[3:4]),
            ("/repos/o/r/pulls/2/reviews", {}, reviews[4:]),
        ]
    )

    n = collect_reviews(fake_conn, client, repo_id=42, full_name="o/r", pr_numbers=[1, 2])

    pr_of = {row["id"]: row["pr_number"] for row in fake_conn.rows}
    assert pr_of == {r["id"]: 1 for r in reviews[:4]} | {reviews[4]["id"]: 2}
    assert n == len(reviews)
    assert all(row["repo_id"] == 42 for row in fake_conn.rows)
    assert all(
        row["author_association"] is not None and row["state"] is not None for row in fake_conn.rows
    )  # NOT NULL in the schema.


def test_collect_reviews_skips_pr_without_reviews(load_fixture, fake_conn, fake_github):
    reviews = load_fixture("reviews.json")
    client = fake_github(
        [
            ("/repos/o/r/pulls/1/reviews", {}),  # No reviews: one empty page.
            ("/repos/o/r/pulls/2/reviews", {}, reviews),
        ]
    )

    n = collect_reviews(fake_conn, client, repo_id=42, full_name="o/r", pr_numbers=[1, 2])

    assert all(rows for _, rows in fake_conn.calls)  # No executemany with zero rows.
    assert n == len(reviews)


def test_collect_reviews_removes_rows_of_a_deleted_pr(
    db_conn, repo_id, load_fixture, fake_github, caplog
):
    reviews = load_fixture("reviews.json")
    for number in (1, 2):
        save_pr(db_conn, repo_id, number)
    client = fake_github(
        [
            # No route for PR 2: the fake returns 404, like a PR deleted on GitHub.
            ("/repos/o/r/pulls/1/reviews", {}, reviews),
        ]
    )

    with caplog.at_level(logging.WARNING):
        n = collect_reviews(db_conn, client, repo_id, full_name="o/r", pr_numbers=[1, 2])

    assert n == len(reviews)
    assert row_counts(db_conn, repo_id, 2) == NO_ROWS
    # PR 1 keeps its rows, plus the reviews just saved.
    assert row_counts(db_conn, repo_id, 1) == ONE_ROW_EACH | {"reviews": 1 + len(reviews)}
    warnings = [record.getMessage() for record in caplog.records]
    assert warnings == [
        "reviews: PR #2 returned 404 (deleted on GitHub?), removing",
        "Removed deleted PRs (1): #2",
    ]


def test_collect_reviews_leaves_other_repos_alone(db_conn, repo_id, load_fixture, fake_github):
    other = parse_repo(load_fixture("repo.json"), load_fixture("community_profile.json"))
    other |= {"id": repo_id + 1, "full_name": "other/repo"}
    upsert_repo(db_conn, other)
    save_pr(db_conn, repo_id, 2)
    save_pr(db_conn, other["id"], 2)  # Same PR number in another repo.
    client = fake_github([])  # Every request 404s.

    collect_reviews(db_conn, client, repo_id, full_name="o/r", pr_numbers=[2])

    assert row_counts(db_conn, repo_id, 2) == NO_ROWS
    assert row_counts(db_conn, other["id"], 2) == ONE_ROW_EACH


def test_collect_reviews_fails_on_other_http_errors_and_removes_nothing(db_conn, repo_id):
    for number in (1, 2):
        save_pr(db_conn, repo_id, number)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/o/r/pulls/2/reviews":
            return httpx.Response(500, json={"message": "Server Error"})
        return httpx.Response(404, json={"message": "Not Found"})  # PR 1: deleted.

    client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError, match="500"):
        collect_reviews(db_conn, client, repo_id, full_name="o/r", pr_numbers=[1, 2])

    # The 500 stops the step before the deletes run, so even PR 1 (a 404) keeps its rows.
    assert row_counts(db_conn, repo_id, 1) == ONE_ROW_EACH
    assert row_counts(db_conn, repo_id, 2) == ONE_ROW_EACH
