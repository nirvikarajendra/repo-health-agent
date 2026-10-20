from repo_health.collector.repos import parse_repo


def test_parse_repo_from_real_fixtures(load_fixture):
    row = parse_repo(load_fixture("repo.json"), load_fixture("community_profile.json"))

    assert row["full_name"] == "encode/httpx"
    assert row["html_url"] == "https://github.com/encode/httpx"  # Repo URL, not the owner URL.
    assert row["license"] == "BSD-3-Clause"
    assert isinstance(row["topics"], list)
    assert row["stars"] > 0
    assert row["has_readme"] is True
    assert row["has_contributing"] is True
    assert row["has_code_of_conduct"] is True


def test_missing_license_and_files_become_none_and_false(load_fixture):
    repo = load_fixture("repo.json") | {"license": None, "homepage": ""}
    community = {"files": {"readme": None, "contributing": None}}

    row = parse_repo(repo, community)

    assert row["license"] is None
    assert row["homepage"] is None
    assert row["has_readme"] is False
    assert row["has_contributing"] is False
    assert row["has_code_of_conduct"] is False
