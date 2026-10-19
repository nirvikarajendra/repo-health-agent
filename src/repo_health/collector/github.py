"""Minimal read-only GitHub REST API client."""

import httpx

from repo_health.config import get_settings

API_URL = "https://api.github.com"
API_VERSION = "2026-03-10"


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """`transport` lets tests swap in a fake GitHub (httpx.MockTransport)."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    }
    token = get_settings().github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=API_URL, headers=headers, timeout=30, transport=transport)


def get_json(client: httpx.Client, path: str) -> dict:
    """Fetch a single object (e.g. /repos/{o}/{r}). For lists, use get_all_pages."""
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def get_all_pages(client: httpx.Client, path: str, params: dict) -> list[dict]:
    """Fetch every page of a list endpoint by following the `Link: rel="next"` header."""
    items: list[dict] = []
    response = client.get(path, params={**params, "per_page": 100})
    while True:
        response.raise_for_status()
        items.extend(response.json())
        next_url = response.links.get("next", {}).get("url")
        if not next_url:
            return items
        response = client.get(next_url)
