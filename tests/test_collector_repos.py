import json
from pathlib import Path

from repo_health.collector.repos import parse_repo

FIXTURES = Path(__file__).parent / "fixtures" / "github"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_parse_repo_from_real_fixtures():
    row = parse_repo(load("repo.json"), load("community_profile.json"))

    assert row["full_name"] == "encode/httpx"
    assert row["html_url"] == "https://github.com/encode/httpx"
    assert row["license"] == "BSD-3-Clause"
    assert isinstance(row["topics"], list)
    assert row["stars"] > 0
    assert row["has_readme"] is True
    assert row["has_contributing"] is True
    assert row["has_code_of_conduct"] is True


def test_missing_license_and_files_become_none_and_false():
    repo = load("repo.json") | {"license": None, "homepage": ""}
    community = {"files": {"readme": None, "contributing": None}}

    row = parse_repo(repo, community)

    assert row["license"] is None
    assert row["homepage"] is None
    assert row["has_readme"] is False
    assert row["has_contributing"] is False
    assert row["has_code_of_conduct"] is False
