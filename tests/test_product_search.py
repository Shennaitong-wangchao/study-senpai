from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from src.product.search import SearchService, _DuckDuckGoHTMLParser, _resolve_duckduckgo_href


class FakeSearchResponse:
    def __init__(self, text: str, *, error: Exception | None = None) -> None:
        self.text = text
        self.error = error

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error


class FakeSearchClient:
    def __init__(self, response: FakeSearchResponse | Exception) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    async def get(self, url: str, *, params: dict[str, str]) -> FakeSearchResponse:
        self.requests.append({"url": url, "params": params})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def search_service_with_client(client: FakeSearchClient, *, max_results: int = 2) -> SearchService:
    service = SearchService.__new__(SearchService)
    service.settings = SimpleNamespace(search_timeout_seconds=4, search_max_results=max_results)
    service._client = client
    return service


def test_resolve_duckduckgo_href_unwraps_redirect_and_protocol_relative_urls() -> None:
    assert _resolve_duckduckgo_href(None) == ""
    assert _resolve_duckduckgo_href("//example.com/path") == "https://example.com/path"
    assert (
        _resolve_duckduckgo_href("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Farticle")
        == "https://example.com/article"
    )
    assert _resolve_duckduckgo_href("https://direct.example/page") == "https://direct.example/page"


def test_duckduckgo_parser_extracts_titles_snippets_and_urls() -> None:
    parser = _DuckDuckGoHTMLParser()

    parser.feed(
        """
        <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fone">
          第一条 &amp; 标题
        </a>
        <div class="result__snippet"> 摘要 &amp; 重点 </div>
        <a class="result__a" href="https://example.com/two">第二条</a>
        <a class="result__snippet">第二条摘要</a>
        """
    )

    assert [(item.title, item.snippet, item.url) for item in parser.items] == [
        ("第一条 & 标题", "摘要 & 重点", "https://example.com/one"),
        ("第二条", "第二条摘要", "https://example.com/two"),
    ]


def test_search_returns_empty_digest_when_query_or_settings_are_missing() -> None:
    empty_query = asyncio.run(SearchService.__new__(SearchService).search(" \n "))

    assert empty_query.query == ""
    assert empty_query.items == []
    assert empty_query.note == "查询为空，未发起检索。"

    service = SearchService.__new__(SearchService)
    service.settings = None
    unconfigured = asyncio.run(service.search(" 学习 计划 "))

    assert unconfigured.query == "学习 计划"
    assert unconfigured.items == []
    assert unconfigured.note == "搜索未配置。"


def test_search_parses_results_and_respects_max_results() -> None:
    html = """
    <a class="result__a" href="https://example.com/one">One</a>
    <div class="result__snippet">First result</div>
    <a class="result__a" href="https://example.com/two">Two</a>
    <div class="result__snippet">Second result</div>
    """
    client = FakeSearchClient(FakeSearchResponse(html))
    service = search_service_with_client(client, max_results=1)

    digest = asyncio.run(service.search("  spaced\nquery  "))

    assert digest.query == "spaced query"
    assert digest.mode == "duckduckgo_html"
    assert digest.note == "已抓取 1 条外部结果，回复时应尽量综合来源并避免暴露工具痕迹。"
    assert [(item.title, item.snippet, item.url) for item in digest.items] == [
        ("One", "First result", "https://example.com/one")
    ]
    assert client.requests == [
        {"url": "https://html.duckduckgo.com/html/", "params": {"q": "spaced query"}}
    ]


def test_search_returns_degraded_note_on_client_or_status_errors() -> None:
    client_error = FakeSearchClient(RuntimeError("network unavailable"))
    client_error_digest = asyncio.run(search_service_with_client(client_error).search("query"))

    assert client_error_digest.items == []
    assert client_error_digest.note == "外部检索暂时失败：RuntimeError"

    status_error = FakeSearchClient(FakeSearchResponse("", error=ValueError("bad status")))
    status_error_digest = asyncio.run(search_service_with_client(status_error).search("query"))

    assert status_error_digest.items == []
    assert status_error_digest.note == "外部检索暂时失败：ValueError"
