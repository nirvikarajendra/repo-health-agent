import logging
from unittest.mock import MagicMock

import pytest

from repo_health.collector import __main__ as collector_main


def test_failing_repo_does_not_stop_the_next_one(monkeypatch, caplog):
    attempted = []

    def fake_collect_one(conn, client, full_name, since):
        attempted.append(full_name)
        if full_name == "o/broken":
            raise RuntimeError("boom")

    connect = MagicMock()
    monkeypatch.setattr(collector_main, "collect_one", fake_collect_one)
    monkeypatch.setattr(collector_main, "connect", connect)
    monkeypatch.setattr(collector_main, "make_client", MagicMock())
    monkeypatch.setattr(collector_main, "setup_logging", lambda: None)  # No logs/ file in tests.
    monkeypatch.setattr("sys.argv", ["collector", "o/broken", "o/ok"])

    with pytest.raises(SystemExit) as exit_info:
        collector_main.main()

    assert attempted == ["o/broken", "o/ok"]
    assert exit_info.value.code == 1
    failure = next(r for r in caplog.records if r.getMessage() == "Failed o/broken")
    assert failure.levelno == logging.ERROR
    assert str(failure.exc_info[1]) == "boom"  # log.exception keeps the error.
    connect.return_value.__enter__.return_value.rollback.assert_called_once()
