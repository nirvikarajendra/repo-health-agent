import httpx
import pytest

from repo_health.collector.github import (
    API_VERSION,
    get_all_pages,
    get_json,
    make_client,
)
from repo_health.config import get_settings


@pytest.fixture
def settings_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def fake_client(handler) -> httpx.Client:
    return httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))


def test_make_client_sends_token_and_api_version(settings_env):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={})

    with make_client(transport=httpx.MockTransport(handler)) as client:
        get_json(client, "/repos/encode/httpx")

    assert seen["authorization"] == "Bearer test-token"
    assert seen["x-github-api-version"] == API_VERSION


def test_get_json_raises_on_error_status():
    client = fake_client(lambda request: httpx.Response(403, json={"message": "rate limit"}))
    with pytest.raises(httpx.HTTPStatusError):
        get_json(client, "/repos/encode/httpx")


def test_get_all_pages_follows_next_links():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"n": 3}])
        next_link = '<https://api.github.com/items?page=2>; rel="next"'
        return httpx.Response(200, json=[{"n": 1}, {"n": 2}], headers={"Link": next_link})

    assert get_all_pages(fake_client(handler), "/items", {}) == [
        {"n": 1},
        {"n": 2},
        {"n": 3},
    ]


def test_get_all_pages_asks_for_100_per_page():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json=[])

    get_all_pages(fake_client(handler), "/items", {"state": "all"})

    assert seen == {"state": "all", "per_page": "100"}
