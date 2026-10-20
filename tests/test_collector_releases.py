from repo_health.collector.releases import collect_releases, parse_release


def test_parse_release_reads_every_fixture_item(load_fixture):
    for item in load_fixture("releases.json"):
        row = parse_release(item)
        assert row["id"] == item["id"]
        assert row["tag"] == item["tag_name"]
        assert row["is_prerelease"] is item["prerelease"]
        assert row["is_draft"] is item["draft"]
        assert row["published_at"] == item["published_at"]


def test_parse_release_handles_prerelease_and_unpublished_draft(load_fixture):
    release = load_fixture("releases.json")[0]
    prerelease = parse_release(release | {"prerelease": True})
    draft = parse_release(release | {"draft": True, "published_at": None})

    assert prerelease["is_prerelease"] is True
    assert draft["is_draft"] is True
    assert draft["published_at"] is None  # Drafts have no publish date.


def test_collect_releases_saves_every_page(load_fixture, fake_conn, fake_github):
    releases = load_fixture("releases.json")
    client = fake_github([("/repos/o/r/releases", {}, releases[:2], releases[2:])])

    n = collect_releases(fake_conn, client, repo_id=42, full_name="o/r")

    assert {row["id"] for row in fake_conn.rows} == {r["id"] for r in releases}
    assert n == len(releases)
    assert fake_conn.commits == 2  # One per page with rows.
    assert all(row["repo_id"] == 42 for row in fake_conn.rows)
    assert all(
        row["tag"] is not None and row["is_prerelease"] is not None and row["is_draft"] is not None
        for row in fake_conn.rows
    )  # NOT NULL in the schema.
