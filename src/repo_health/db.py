"""Database connection helper."""

import psycopg

from repo_health.config import get_settings


def connect() -> psycopg.Connection:
    return psycopg.connect(get_settings().database_url)
