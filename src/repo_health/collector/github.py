"""Minimal read-only GitHub REST API client."""

from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from repo_health.config import get_settings

API_URL = "https://api.github.com"
API_VERSION = "2026-03-10"


class RateLimitError(RuntimeError):
    """GitHub refused the request because the hourly request budget is used up."""


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """`transport` lets tests swap in a fake GitHub (httpx.MockTransport)."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    }
    token = get_settings().github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(
        base_url=API_URL,
        headers=headers,
        timeout=30,
        follow_redirects=True,  # renamed/moved repos answer with a redirect
        transport=transport,
    )


def check_response(response: httpx.Response) -> None:
    """Raise a clear RateLimitError when out of requests, otherwise any HTTP error."""
    if response.status_code in (403, 429) and response.headers.get("X-RateLimit-Remaining") == "0":
        reset = int(response.headers.get("X-RateLimit-Reset", "0"))
        reset_at = datetime.fromtimestamp(reset, UTC).strftime("%H:%M UTC")
        raise RateLimitError(f"GitHub rate limit reached. It resets at {reset_at}.")
    response.raise_for_status()


def get_json(client: httpx.Client, path: str) -> dict:
    """Fetch a single object (e.g. /repos/{o}/{r}). For lists, use iter_pages."""
    response = client.get(path)
    check_response(response)
    return response.json()


def iter_pages(client: httpx.Client, path: str, params: dict) -> Iterator[list[dict]]:
    """Yield one page (list of items) at a time, following `Link: rel="next"`.

    Yielding page by page lets the caller save each page before fetching the next.
    """
    response = client.get(path, params={"per_page": 100, **params})
    while True:
        check_response(response)
        yield response.json()
        next_url = response.links.get("next", {}).get("url")
        if not next_url:
            return
        response = client.get(next_url)
