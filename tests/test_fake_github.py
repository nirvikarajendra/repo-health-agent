import httpx
import pytest

from repo_health.collector.github import iter_pages


def test_fake_github_serves_several_pages(fake_github):
    client = fake_github([("/items", {"state": "all"}, [1, 2], [3])])

    pages = list(iter_pages(client, "/items", {"state": "all"}))

    assert pages == [[1, 2], [3]]


def test_fake_github_unknown_request_is_a_404(fake_github):
    client = fake_github([("/items", {"state": "all"}, [1])])

    with pytest.raises(httpx.HTTPStatusError, match="404"):
        list(iter_pages(client, "/items", {"state": "open"}))
