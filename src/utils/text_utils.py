from __future__ import annotations

import re
from collections import Counter


WHITESPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def compact_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip()


def truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def tokenize(value: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(value)]


def overlap_score(query: str, candidate: str) -> float:
    query_tokens = tokenize(query)
    candidate_tokens = tokenize(candidate)
    if not query_tokens or not candidate_tokens:
        return 0.0
    query_counts = Counter(query_tokens)
    candidate_counts = Counter(candidate_tokens)
    shared = sum(min(query_counts[token], candidate_counts[token]) for token in query_counts)
    return shared / max(len(query_tokens), 1)


def strip_discord_mentions(content: str, bot_user_id: int | None) -> str:
    if bot_user_id is None:
        return compact_text(content)
    patterns = [f"<@{bot_user_id}>", f"<@!{bot_user_id}>"]
    for pattern in patterns:
        content = content.replace(pattern, "")
    return compact_text(content)
