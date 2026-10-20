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
    """Records each executemany call and counts commits instead of writing to Postgres.

    It also checks that every `%(name)s` placeholder in the SQL has a matching key in
    each row, which is the mistake real Postgres would otherwise catch first.
    """

    def __init__(self):
        self.calls: list[tuple[str, list[dict]]] = []
        self.commits = 0

    @property
    def rows(self) -> list[dict]:
        return [row for _, rows in self.calls for row in rows]

    def commit(self):
        self.commits += 1

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
