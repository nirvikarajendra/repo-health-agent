"""Minimal read-only GitHub REST API client."""

import logging
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import httpx

from repo_health.config import get_settings

API_URL = "https://api.github.com"
API_VERSION = "2026-03-10"
MAX_RETRIES = 3
SECONDARY_LIMIT_WAIT = 60  # seconds

log = logging.getLogger(__name__)


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


def rate_limit_wait(response: httpx.Response) -> tuple[float, str] | None:
    """Return (seconds to wait, reason) if GitHub rate-limited this request, else None."""
    if response.status_code not in (403, 429):
        return None
    if "Retry-After" in response.headers:
        return float(response.headers["Retry-After"]), "Retry-After header"
    if response.headers.get("X-RateLimit-Remaining") == "0":
        reset = int(response.headers.get("X-RateLimit-Reset", "0"))
        return max(reset - time.time(), 0) + 1, "hourly limit used up"
    # GitHub's docs: a secondary limit without either header means wait at least a minute.
    if "secondary rate limit" in response.text.lower():
        return SECONDARY_LIMIT_WAIT, "secondary rate limit"
    return None  # A plain 403, e.g. no permission: not worth retrying.


def check_response(response: httpx.Response) -> None:
    """Raise a clear RateLimitError when rate-limited, otherwise any HTTP error."""
    if rate_limit_wait(response) is not None:
        message = "GitHub rate limit reached."
        if response.headers.get("X-RateLimit-Remaining") == "0":
            reset = int(response.headers.get("X-RateLimit-Reset", "0"))
            message += f" It resets at {datetime.fromtimestamp(reset, UTC):%H:%M UTC}."
        raise RateLimitError(message)
    response.raise_for_status()


def get(
    client: httpx.Client,
    url: str,
    params: dict | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """GET, retrying up to MAX_RETRIES times on rate limits. `sleep` lets tests skip real waits."""
    for attempt in range(MAX_RETRIES + 1):
        response = client.get(url, params=params)
        wait = rate_limit_wait(response)
        if wait is None or attempt == MAX_RETRIES:
            break
        seconds, reason = wait
        log.warning(
            "Rate limited (%s): waiting %.0fs before retry %d/%d",
            reason,
            seconds,
            attempt + 1,
            MAX_RETRIES,
        )
        sleep(seconds)
    check_response(response)
    return response


def get_json(client: httpx.Client, path: str) -> dict:
    """Fetch a single object (e.g. /repos/{o}/{r}). For lists, use iter_pages."""
    return get(client, path).json()


def iter_pages(client: httpx.Client, path: str, params: dict) -> Iterator[list[dict]]:
    """Yield one page (list of items) at a time, following `Link: rel="next"`.

    Yielding page by page lets the caller save each page before fetching the next.
    """
    response = get(client, path, {"per_page": 100, **params})
    while True:
        yield response.json()
        next_url = response.links.get("next", {}).get("url")
        if not next_url:
            return
        response = get(client, next_url)
