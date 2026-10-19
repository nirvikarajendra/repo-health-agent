import httpx
import pytest

from repo_health.collector.github import (
    API_VERSION,
    RateLimitError,
    get_json,
    iter_pages,
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
    client = fake_client(lambda request: httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(httpx.HTTPStatusError):
        get_json(client, "/repos/encode/httpx")


def test_rate_limit_raises_clear_error():
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1760000000"}
        return httpx.Response(403, json={"message": "rate limit"}, headers=headers)

    with pytest.raises(RateLimitError, match="resets at"):
        get_json(fake_client(handler), "/repos/encode/httpx")


def test_redirects_are_followed(settings_env):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/old/name":
            new_url = "https://api.github.com/repos/new/name"
            return httpx.Response(301, headers={"Location": new_url})
        return httpx.Response(200, json={"full_name": "new/name"})

    with make_client(transport=httpx.MockTransport(handler)) as client:
        assert get_json(client, "/repos/old/name") == {"full_name": "new/name"}


def test_iter_pages_follows_next_links():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"n": 3}])
        next_link = '<https://api.github.com/items?page=2>; rel="next"'
        return httpx.Response(200, json=[{"n": 1}, {"n": 2}], headers={"Link": next_link})

    pages = list(iter_pages(fake_client(handler), "/items", {}))

    assert pages == [[{"n": 1}, {"n": 2}], [{"n": 3}]]


def test_iter_pages_defaults_to_100_per_page_but_caller_can_override():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=[])

    list(iter_pages(fake_client(handler), "/items", {"state": "all"}))
    list(iter_pages(fake_client(handler), "/items", {"per_page": 10}))

    assert seen == [{"state": "all", "per_page": "100"}, {"per_page": "10"}]
