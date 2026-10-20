from repo_health.collector.reviews import collect_reviews, parse_review


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
    assert fake_conn.commits == 3  # PR 1: two pages, PR 2: one.
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
