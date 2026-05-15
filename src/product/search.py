from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import httpx

from src.core.settings import Settings
from src.product.models import SearchDigest, SearchDigestItem
from src.utils.text_utils import compact_text, truncate_text


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[SearchDigestItem] = []
        self._current_href: str | None = None
        self._current_title: list[str] = []
        self._current_snippet: list[str] = []
        self._capture_title = False
        self._capture_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key: (value or "") for key, value in attrs}
        classes = attrs_map.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._current_href = attrs_map.get("href")
            self._current_title = []
            self._capture_title = True
            return
        if tag == "a" and "result__snippet" in classes:
            self._current_snippet = []
            self._capture_snippet = True
            return
        if tag == "div" and "result__snippet" in classes:
            self._current_snippet = []
            self._capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title:
            self._capture_title = False
            return
        if tag in {"a", "div"} and self._capture_snippet:
            self._capture_snippet = False
            title = compact_text(unescape("".join(self._current_title)))
            snippet = compact_text(unescape("".join(self._current_snippet)))
            url = _resolve_duckduckgo_href(self._current_href)
            if title and url:
                self.items.append(
                    SearchDigestItem(
                        title=truncate_text(title, 120),
                        snippet=truncate_text(snippet or title, 220),
                        url=url,
                    )
                )
            self._current_href = None
            self._current_title = []
            self._current_snippet = []

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._current_title.append(data)
        if self._capture_snippet:
            self._current_snippet.append(data)


def _resolve_duckduckgo_href(value: str | None) -> str:
    if not value:
        return ""
    resolved = unescape(value).strip()
    if resolved.startswith("//"):
        resolved = f"https:{resolved}"
    parsed = urlparse(resolved)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return target or resolved
    return resolved


class SearchService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings
        timeout_seconds = settings.search_timeout_seconds if settings else 8
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ZhiweiSearchBot/1.0)"},
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str) -> SearchDigest:
        normalized = compact_text(query)
        if not normalized:
            return SearchDigest(query="", items=[], mode="duckduckgo_html", note="查询为空，未发起检索。")
        if self.settings is None:
            return SearchDigest(query=normalized, items=[], mode="duckduckgo_html", note="搜索未配置。")
        try:
            response = await self._client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": normalized},
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return SearchDigest(
                query=normalized,
                items=[],
                mode="duckduckgo_html",
                note=f"外部检索暂时失败：{type(exc).__name__}",
            )

        parser = _DuckDuckGoHTMLParser()
        parser.feed(response.text)
        items = parser.items[: self.settings.search_max_results]
        note = (
            f"已抓取 {len(items)} 条外部结果，回复时应尽量综合来源并避免暴露工具痕迹。"
            if items
            else "没有抓到可用的外部结果，请基于现有上下文谨慎回答。"
        )
        return SearchDigest(
            query=normalized,
            items=items,
            mode="duckduckgo_html",
            note=note,
        )
