import json
from pathlib import Path

from repo_health.collector.issues import parse_comment, parse_issue

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
