"""Shared test fixtures: fixture loading, fake and real database connections, a fake GitHub."""

import json
import re
from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from repo_health.config import get_settings
from repo_health.migrate import apply_migrations

FIXTURES = Path(__file__).parent / "fixtures" / "github"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
# Every data table; schema_migrations is kept so migrations aren't re-applied.
TRUNCATE_ALL = """
TRUNCATE repos, issues, comments, pull_requests, reviews, releases, commits, sync_runs
RESTART IDENTITY CASCADE
"""


@pytest.fixture
def load_fixture():
    """Return a function that loads tests/fixtures/github/<name> as JSON."""

    def load(name: str):
        return json.loads((FIXTURES / name).read_text())

    return load


class FakeConnection:
    """Records each executemany call instead of writing to Postgres.

    It also checks that every `%(name)s` placeholder in the SQL has a matching key in
    each row, which is the mistake real Postgres would otherwise catch first.
    """

    def __init__(self):
        self.calls: list[tuple[str, list[dict]]] = []

    @property
    def rows(self) -> list[dict]:
        return [row for _, rows in self.calls for row in rows]

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, row):
        self.executemany(sql, [row])

    def executemany(self, sql, rows):
        rows = list(rows)
        needed = set(PLACEHOLDER.findall(sql))
        for row in rows:
            missing = needed - row.keys()
            assert not missing, f"row is missing SQL parameters {sorted(missing)}"
        self.calls.append((sql, rows))


@pytest.fixture
def fake_conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def fake_github():
    """Build a fake GitHub client from routes: (path, params, page1, page2, ...).

    Params must match exactly (ignoring per_page and page), with string values.
    Extra pages get a `next` link; an unknown request gets a 404."""

    def build(routes: list[tuple]) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            params.pop("per_page", None)
            page = int(params.pop("page", "1"))
            for path, expected, *pages in routes:
                if request.url.path == path and params == expected:
                    pages = pages or [[]]  # no pages given: one empty page
                    if page > len(pages):
                        message = f"{path} has only {len(pages)} page(s), got page={page}"
                        return httpx.Response(404, json={"message": message})
                    headers = {}
                    if page < len(pages):
                        next_url = request.url.copy_set_param("page", page + 1)
                        headers["Link"] = f'<{next_url}>; rel="next"'
                    return httpx.Response(200, json=pages[page - 1], headers=headers)
            known = "\n".join(f"  {path} {expected}" for path, expected, *_ in routes)
            message = f"Unexpected request: {request.url.path} {params} page={page}"
            return httpx.Response(404, json={"message": f"{message}\nKnown:\n{known}"})

        return httpx.Client(
            base_url="https://api.github.com", transport=httpx.MockTransport(handler)
        )

    return build


@pytest.fixture(scope="session")
def migrated_db_url() -> str:
    """TEST_DATABASE_URL, checked and migrated once per test run. Skips if it isn't set.

    Never DATABASE_URL: every test wipes this database, so its name must end in _test.
    """
    url = get_settings().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    dbname = conninfo_to_dict(url).get("dbname", "")
    if not dbname.endswith("_test"):
        pytest.fail(f"TEST_DATABASE_URL must name a database ending in _test, not {dbname!r}")
    with psycopg.connect(url) as conn:
        apply_migrations(conn)
    return url


@pytest.fixture
def db_conn(migrated_db_url):
    """A connection to the real test database, emptied before each test."""
    with psycopg.connect(migrated_db_url) as conn:
        conn.execute(TRUNCATE_ALL)
        conn.commit()
        yield conn
        conn.rollback()  # Discard anything the test didn't commit itself.
