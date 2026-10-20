"""Apply SQL migrations from sql/migrations/ that haven't been applied yet.

Run with: uv run python -m repo_health.migrate
"""

import logging
from pathlib import Path

import psycopg

from repo_health.db import connect
from repo_health.logs import setup_logging

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "sql" / "migrations"

log = logging.getLogger(__name__)


def pending_migrations(files: list[Path], applied: set[str]) -> list[Path]:
    """Return migration files not yet applied, in filename order (001, 002, ...)."""
    return sorted((f for f in files if f.name not in applied), key=lambda f: f.name)


def apply_migrations(conn: psycopg.Connection) -> None:
    """Apply every migration file not yet recorded in schema_migrations."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   text PRIMARY KEY,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    rows = conn.execute("SELECT filename FROM schema_migrations")
    applied = {row[0] for row in rows}
    conn.commit()  # End the implicit transaction, so each file below gets its own.
    todo = pending_migrations(list(MIGRATIONS_DIR.glob("*.sql")), applied)
    if not todo:
        log.info("Database is up to date.")
        return
    for path in todo:
        # One transaction per file.
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (path.name,),
            )
        log.info("Applied %s", path.name)


def main() -> None:
    setup_logging()
    with connect() as conn:
        apply_migrations(conn)


if __name__ == "__main__":
    main()
