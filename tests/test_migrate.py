from pathlib import Path

from repo_health.migrate import pending_migrations


def test_returns_unapplied_files_in_order():
    files = [Path("003_c.sql"), Path("001_a.sql"), Path("002_b.sql")]
    pending = pending_migrations(files, applied={"001_a.sql"})
    assert pending == [Path("002_b.sql"), Path("003_c.sql")]


def test_nothing_pending_when_all_applied():
    files = [Path("001_a.sql")]
    assert pending_migrations(files, applied={"001_a.sql"}) == []
