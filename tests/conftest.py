"""Shared test fixtures: fixture loading, a fake database connection, a fake GitHub."""

import json
import re
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "github"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")


@pytest.fixture
def load_fixture():
    """Return a function that loads tests/fixtures/github/<name> as JSON."""

    def load(name: str):
        return json.loads((FIXTURES / name).read_text())

    return load


class FakeConnection:
    """Record executemany calls instead of writing to Postgres.

    Fails if a row has no key for a `%(name)s` placeholder in the SQL.
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
    """Return a builder for an httpx client that serves canned GitHub responses.

    Each route is (path, params, page1, page2, ...). A request matches when its path and
    query params, excluding `per_page` and `page`, equal the route's. Param values must
    be strings, e.g. {"since": SINCE, "direction": "desc"}.

    Routes with several pages return a `Link: rel="next"` header, as GitHub does.
    Unmatched requests return a 404 that lists the known routes.
    """

    def build(routes: list[tuple]) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            params.pop("per_page", None)
            page = int(params.pop("page", "1"))
            for path, expected, *pages in routes:
                if request.url.path == path and params == expected:
                    if page > len(pages):
                        break
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
