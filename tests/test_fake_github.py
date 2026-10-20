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


def test_fake_github_route_without_pages_returns_empty_list(fake_github):
    client = fake_github([("/items", {})])

    assert list(iter_pages(client, "/items", {})) == [[]]


def test_fake_github_says_when_a_page_is_past_the_end(fake_github):
    client = fake_github([("/items", {}, [1])])

    with pytest.raises(httpx.HTTPStatusError, match="404"):
        client.get("/items", params={"page": "2"}).raise_for_status()


def test_fake_conn_records_single_execute(fake_conn):
    fake_conn.execute("INSERT %(a)s", {"a": 1})

    assert fake_conn.rows == [{"a": 1}]
