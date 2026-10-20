from repo_health.collector.pulls import collect_pulls, parse_pull

SINCE = "2025-10-20T00:00:00Z"
CLOSED = {"state": "closed", "sort": "updated", "direction": "desc"}


def test_parse_pull_reads_every_fixture_item(load_fixture):
    for item in load_fixture("pulls.json"):
        row = parse_pull(item)
        assert row["number"] == item["number"]
        assert row["base_ref"] == item["base"]["ref"]
        assert row["is_draft"] is item["draft"]
        assert row["merged_at"] == item["merged_at"]


def test_parse_pull_handles_null_draft_and_merged_pr(load_fixture):
    item = load_fixture("pulls.json")[0] | {
        "draft": None,
        "merged_at": "2026-09-18T22:02:14Z",
    }

    row = parse_pull(item)

    assert row["is_draft"] is False  # NOT NULL in the schema.
    assert row["merged_at"] == "2026-09-18T22:02:14Z"


def test_collect_pulls_stops_paging_at_first_old_closed_pr(load_fixture, fake_conn, fake_github):
    pulls = load_fixture("pulls.json")
    open_prs = [pr for pr in pulls if pr["state"] == "open"]
    closed = next(pr for pr in pulls if pr["state"] == "closed")
    merged = closed | {"number": 1, "merged_at": "2026-09-18T22:00:00Z"}
    too_old = closed | {"number": 2, "updated_at": "2024-01-01T00:00:00Z"}
    recent_on_page_2 = closed | {"number": 3}
    client = fake_github(
        [
            ("/repos/o/r/pulls", {"state": "open"}, open_prs),
            # Page 1 contains an old PR, so page 2 must not be requested.
            ("/repos/o/r/pulls", CLOSED, [closed, merged, too_old], [recent_on_page_2]),
        ]
    )

    n = collect_pulls(fake_conn, client, repo_id=42, full_name="o/r", since=SINCE)

    saved = {row["number"] for row in fake_conn.rows}
    assert saved == {3796, 3785, 3783, 1}
    assert 2 not in saved  # Older than `since`.
    assert 3 not in saved  # On page 2, which is never fetched.
    assert n == 4
    assert all(row["repo_id"] == 42 for row in fake_conn.rows)
    assert all(
        row["base_ref"] is not None and row["is_draft"] is not None for row in fake_conn.rows
    )  # NOT NULL in the schema.
