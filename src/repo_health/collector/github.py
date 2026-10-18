"""Minimal read-only GitHub REST API client."""

import httpx

from repo_health.config import get_settings

API_URL = "https://api.github.com"
API_VERSION = "2026-03-10"


def make_client() -> httpx.Client:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    }
    token = get_settings().github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=API_URL, headers=headers, timeout=30)


def get_json(client: httpx.Client, path: str) -> dict:
    response = client.get(path)
    response.raise_for_status()
    return response.json()
