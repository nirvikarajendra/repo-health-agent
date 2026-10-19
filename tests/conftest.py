"""Shared test helpers: a fake GitHub, a fake database connection, fixture loading."""

import json
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "github"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


class FakeConnection:
    """Records the rows passed to executemany instead of writing to Postgres."""

    def __init__(self):
        self.rows: list[dict] = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def executemany(self, sql, rows):
        self.rows.extend(rows)


@pytest.fixture
def fake_conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def fake_github():
    """Build an httpx client whose replies come from `routes`.

    routes maps (path, value of the `state` param or None) to the JSON GitHub would return.
    """

    def build(routes: dict) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            key = (request.url.path, request.url.params.get("state"))
            return httpx.Response(200, json=routes[key])

        return httpx.Client(
            base_url="https://api.github.com", transport=httpx.MockTransport(handler)
        )

    return build
