"""Agent tools against the real test database, and the agent's setup. No Gemini calls."""

import json
from datetime import UTC, datetime

import psycopg
import pytest

from repo_health.agent import tools
from repo_health.agent.build import INSTRUCTION, build_agent

AS_OF = datetime(2026, 10, 20, tzinfo=UTC)


@pytest.fixture
def tools_db(monkeypatch, migrated_db_url):
    """Point the wrappers' connect() at the test database instead of DATABASE_URL."""
    monkeypatch.setattr(tools, "connect", lambda: psycopg.connect(migrated_db_url))


@pytest.fixture
def tracked(db_conn, repo_id, tools_db) -> int:
    """encode/httpx with a successful sync at AS_OF, committed so the wrappers can see it."""
    db_conn.execute(
        "INSERT INTO sync_runs (repo_full_name, repo_id, status, finished_at)"
        " VALUES ('encode/httpx', %s, 'success', %s)",
        (repo_id, AS_OF),
    )
    db_conn.commit()
    return repo_id


def test_list_repos_returns_repos_with_iso_dates(tracked):
    result = tools.list_repos()

    assert result == {
        "status": "success",
        "repos": [{"full_name": "encode/httpx", "data_as_of": "2026-10-20T00:00:00Z"}],
    }


def test_list_repos_with_no_repos(db_conn, tools_db):
    assert tools.list_repos() == {"status": "success", "repos": []}


def test_get_repo_overview_returns_a_json_ready_dict(tracked, load_fixture):
    repo = load_fixture("repo.json")

    result = tools.get_repo_overview("ENCODE/httpx")

    assert result["status"] == "success"
    assert result["full_name"] == "encode/httpx"
    assert result["stars"] == repo["stargazers_count"]
    assert result["data_as_of"] == "2026-10-20T00:00:00Z"
    json.dumps(result)  # Only plain JSON types: no datetime objects left.


def test_get_repo_overview_unknown_repo_returns_error(tracked):
    assert tools.get_repo_overview("nobody/nothing") == {
        "status": "error",
        "error_message": "repo not tracked",
    }


def test_wrapper_connections_refuse_writes(db_conn, tools_db):
    with tools.read_only_connection() as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM repos")


def test_build_agent_has_only_the_two_tools(monkeypatch):
    # No API key is needed: building the agent makes no Gemini call.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    agent = build_agent("test-model")

    assert agent.model == "test-model"
    assert [tool.__name__ for tool in agent.tools] == ["list_repos", "get_repo_overview"]
    assert agent.instruction == INSTRUCTION


def test_instruction_keeps_the_rules():
    assert "only from tool results" in INSTRUCTION
    assert "data_as_of" in INSTRUCTION
    assert "I don't know" in INSTRUCTION


@pytest.mark.parametrize("model", [None, ""])
def test_build_agent_without_a_model_names_the_setting(model):
    with pytest.raises(ValueError, match="GEMINI_MODEL"):
        build_agent(model)
