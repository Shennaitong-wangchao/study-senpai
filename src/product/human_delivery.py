from __future__ import annotations

import asyncio
import random
import re
from typing import Any

from src.core.settings import Settings
from src.product.streaming import split_markdown_chunks


CODE_OR_TABLE_RE = re.compile(r"```|\n\s*\|.+\|\s*\n|^\s*[-*]\s+", re.MULTILINE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])")


def split_human_message_parts(text: str, *, max_parts: int = 3, limit: int = 1800) -> list[str]:
    normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not normalized:
        return ["..."]
    if len(normalized) > limit or CODE_OR_TABLE_RE.search(normalized):
        return split_markdown_chunks(normalized, limit=limit) or [normalized[:limit]]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    if 1 < len(paragraphs) <= max_parts:
        return paragraphs

    sentences = [part.strip() for part in SENTENCE_SPLIT_RE.split(normalized) if part.strip()]
    if len(sentences) <= 1:
        return [normalized]

    target_parts = min(max_parts, 2 if len(normalized) < 220 else max_parts)
    buckets = _pack_sentences(sentences, target_parts)
    return [part for part in buckets if part] or [normalized]


def _pack_sentences(sentences: list[str], target_parts: int) -> list[str]:
    if target_parts <= 1:
        return ["".join(sentences)]
    total_chars = sum(len(sentence) for sentence in sentences)
    target_chars = max(total_chars // target_parts, 80)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(parts) < target_parts - 1 and len(current) + len(sentence) > target_chars:
            parts.append(current.strip())
            current = sentence
        else:
            current += sentence
    if current.strip():
        parts.append(current.strip())
    return parts


def _typing_delay_seconds(part: str, settings: Settings) -> float:
    min_ms = max(settings.human_typing_min_ms, 0)
    max_ms = max(settings.human_typing_max_ms, min_ms)
    per_char_ms = 18
    estimated = min(max(len(part) * per_char_ms, min_ms), max_ms)
    jitter = random.uniform(0.88, 1.12)
    return estimated * jitter / 1000.0


def _part_delay_seconds(settings: Settings) -> float:
    min_ms = max(settings.human_part_delay_min_ms, 0)
    max_ms = max(settings.human_part_delay_max_ms, min_ms)
    return random.uniform(min_ms, max_ms) / 1000.0


async def send_human_message_parts(
    channel: Any,
    text: str,
    *,
    settings: Settings,
    reference: Any | None = None,
    mention_author: bool = False,
    limit: int = 1800,
) -> list[Any]:
    parts = split_human_message_parts(
        text,
        max_parts=max(settings.human_message_max_parts, 1),
        limit=limit,
    )
    sent_messages: list[Any] = []
    for index, part in enumerate(parts):
        if settings.human_presence_enabled:
            async with channel.typing():
                await asyncio.sleep(_typing_delay_seconds(part, settings))
        sent = await channel.send(
            part,
            reference=reference if index == 0 else None,
            mention_author=mention_author,
        )
        sent_messages.append(sent)
        if settings.human_presence_enabled and index < len(parts) - 1:
            await asyncio.sleep(_part_delay_seconds(settings))
    return sent_messages
