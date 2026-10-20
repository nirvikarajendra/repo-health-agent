"""Database connection helper."""

import psycopg

from repo_health.config import get_settings


def connect() -> psycopg.Connection:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set.")
    return psycopg.connect(url)
