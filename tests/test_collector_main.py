import logging
from unittest.mock import MagicMock

import httpx
import pytest

from repo_health.collector import __main__ as collector_main


def test_failing_repo_does_not_stop_the_next_one(monkeypatch, caplog):
    attempted, finished = [], {}
    connect = MagicMock()
    conn = connect.return_value.__enter__.return_value

    def fake_collect_one(conn, client, full_name, since):
        attempted.append(full_name)
        client.get(f"https://api.github.com/repos/{full_name}")
        if full_name == "o/broken":
            raise RuntimeError("boom")
        client.get(f"https://api.github.com/repos/{full_name}/issues")

    def fake_finish_run(conn, run_id, status, requests_used, error=None):
        if status == "failed":
            assert conn.rollback.called  # Rollback must come before recording the failure.
        finished[run_id] = (status, requests_used, error)

    github = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    run_ids = {"o/broken": 1, "o/ok": 2}
    monkeypatch.setattr(collector_main, "collect_one", fake_collect_one)
    monkeypatch.setattr(collector_main, "connect", connect)
    monkeypatch.setattr(collector_main, "make_client", lambda: github)
    monkeypatch.setattr(collector_main, "start_run", lambda conn, full_name: run_ids[full_name])
    monkeypatch.setattr(collector_main, "finish_run", fake_finish_run)
    monkeypatch.setattr(collector_main, "setup_logging", lambda: None)  # No logs/ file in tests.
    monkeypatch.setattr("sys.argv", ["collector", "o/broken", "o/ok"])

    with pytest.raises(SystemExit) as exit_info:
        collector_main.main()

    assert attempted == ["o/broken", "o/ok"]
    assert exit_info.value.code == 1
    # The request counter restarts per repo: 1 request before "boom", then 2.
    assert finished == {1: ("failed", 1, "RuntimeError: boom"), 2: ("success", 2, None)}
    failure = next(r for r in caplog.records if r.getMessage() == "Failed o/broken")
    assert failure.levelno == logging.ERROR
    assert str(failure.exc_info[1]) == "boom"  # log.exception keeps the error.
    conn.rollback.assert_called_once()
