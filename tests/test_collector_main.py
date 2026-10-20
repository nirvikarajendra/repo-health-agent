import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from repo_health.collector import __main__ as collector_main


@pytest.fixture
def fake_runs(monkeypatch):
    """Patch out Postgres, GitHub, sync_runs and log files; record run starts and finishes."""
    connect = MagicMock()
    runs = SimpleNamespace(
        conn=connect.return_value.__enter__.return_value, started=[], finished={}
    )
    run_ids = {"o/broken": 1, "O/OK": 2}

    def fake_start_run(conn, full_name):
        runs.started.append(full_name)
        return run_ids[full_name]

    def fake_finish_run(conn, run_id, status, requests_used, error=None, full_name=None):
        if status == "failed":
            assert conn.rollback.called  # Rollback must come before recording the failure.
        runs.finished[run_id] = (status, requests_used, error, full_name)

    github = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    monkeypatch.setattr(collector_main, "connect", connect)
    monkeypatch.setattr(collector_main, "make_client", lambda: github)
    monkeypatch.setattr(collector_main, "start_run", fake_start_run)
    monkeypatch.setattr(collector_main, "finish_run", fake_finish_run)
    monkeypatch.setattr(collector_main, "setup_logging", lambda: None)  # No logs/ file in tests.
    monkeypatch.setattr("sys.argv", ["collector", "o/broken", "O/OK"])
    return runs


def test_failing_repo_does_not_stop_the_next_one(monkeypatch, caplog, fake_runs):
    attempted = []

    def fake_collect_one(conn, client, full_name, since):
        attempted.append(full_name)
        client.get(f"https://api.github.com/repos/{full_name}")
        if full_name == "o/broken":
            raise RuntimeError("boom")
        client.get(f"https://api.github.com/repos/{full_name}/issues")
        return full_name.lower()  # GitHub's spelling of the name.

    monkeypatch.setattr(collector_main, "collect_one", fake_collect_one)

    with pytest.raises(SystemExit) as exit_info:
        collector_main.main()

    assert attempted == ["o/broken", "O/OK"]
    assert exit_info.value.code == 1
    # Requests restart per repo; only the successful run gets GitHub's name.
    assert fake_runs.finished == {
        1: ("failed", 1, "RuntimeError: boom", None),
        2: ("success", 2, None, "o/ok"),
    }
    failure = next(r for r in caplog.records if r.getMessage() == "Failed o/broken")
    assert failure.levelno == logging.ERROR
    assert str(failure.exc_info[1]) == "boom"  # log.exception keeps the error.
    fake_runs.conn.rollback.assert_called_once()


def test_ctrl_c_records_interrupted_run_and_stops(monkeypatch, caplog, fake_runs):
    def interrupted(conn, client, full_name, since):
        raise KeyboardInterrupt

    monkeypatch.setattr(collector_main, "collect_one", interrupted)

    with pytest.raises(KeyboardInterrupt):  # Re-raised, so the program still stops.
        collector_main.main()

    assert fake_runs.started == ["o/broken"]  # O/OK never started.
    assert fake_runs.finished == {1: ("failed", 0, "Interrupted", None)}
    assert "Interrupted o/broken" in caplog.text
    fake_runs.conn.rollback.assert_called_once()
