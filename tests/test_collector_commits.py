from repo_health.collector.commits import collect_commits, parse_commit

SINCE = "2025-10-20T00:00:00Z"


def test_parse_commit_reads_every_fixture_item(load_fixture):
    for item in load_fixture("commits.json"):
        row = parse_commit(item)
        assert row["sha"] == item["sha"]
        assert row["author_login"] == item["author"]["login"]
        assert row["committed_at"] == item["commit"]["committer"]["date"]


def test_parse_commit_handles_unlinked_author(load_fixture):
    item = load_fixture("commits.json")[0] | {"author": None}
    assert parse_commit(item)["author_login"] is None


def test_collect_commits_saves_every_page(load_fixture, fake_conn, fake_github):
    commits = load_fixture("commits.json")
    client = fake_github([("/repos/o/r/commits", {"since": SINCE}, commits[:3], commits[3:])])

    n = collect_commits(fake_conn, client, repo_id=42, full_name="o/r", since=SINCE)

    assert {row["sha"] for row in fake_conn.rows} == {c["sha"] for c in commits}
    assert n == len(commits)
    assert all(row["repo_id"] == 42 for row in fake_conn.rows)
    assert all(
        row["sha"] is not None and row["committed_at"] is not None for row in fake_conn.rows
    )  # NOT NULL in the schema.
