from __future__ import annotations

import re
import time


CODE_FENCE_RE = re.compile(r"^```([\w+-]*)")


class ProgressiveReleaseState:
    def __init__(self, *, flush_chars: int, max_silence_ms: int) -> None:
        self.flush_chars = flush_chars
        self.max_silence_ms = max_silence_ms
        self.released_chars = 0
        self.last_release_at = time.monotonic()

    def should_release(self, text: str, *, force: bool = False) -> bool:
        if force:
            return len(text) > self.released_chars
        pending = len(text) - self.released_chars
        if pending <= 0:
            return False
        if self._has_paragraph_break(text):
            return True
        if pending >= self.flush_chars:
            return True
        if (time.monotonic() - self.last_release_at) * 1000 >= self.max_silence_ms:
            return True
        return False

    def mark_released(self, text: str) -> None:
        self.released_chars = len(text)
        self.last_release_at = time.monotonic()

    def _has_paragraph_break(self, text: str) -> bool:
        return "\n\n" in text[self.released_chars :]


def split_markdown_chunks(text: str, *, limit: int = 1800) -> list[str]:
    if len(text) <= limit:
        return [text] if text else []

    chunks: list[str] = []
    current = ""
    open_fence_lang: str | None = None

    for segment in _to_segments(text):
        current, open_fence_lang = _append_segment(
            chunks,
            current,
            segment,
            open_fence_lang=open_fence_lang,
            limit=limit,
        )

    if current:
        chunks.append(current)
    return chunks


def _append_segment(
    chunks: list[str],
    current: str,
    segment: str,
    *,
    open_fence_lang: str | None,
    limit: int,
) -> tuple[str, str | None]:
    if len(current) + len(segment) <= limit:
        current += segment
        return current, _update_fence_state(open_fence_lang, segment)

    if current:
        closed_chunk, reopened_prefix = _close_and_reopen_if_needed(current, open_fence_lang)
        chunks.append(closed_chunk.rstrip())
        current = reopened_prefix
    if len(segment) + len(current) <= limit:
        current += segment
        return current, _update_fence_state(open_fence_lang if not current.startswith("```") else open_fence_lang, segment)

    for part in _split_long_segment(segment, limit, prefix=current):
        if len(current) + len(part) <= limit:
            current += part
            open_fence_lang = _update_fence_state(open_fence_lang, part)
            continue
        if current:
            closed_chunk, reopened_prefix = _close_and_reopen_if_needed(current, open_fence_lang)
            chunks.append(closed_chunk.rstrip())
            current = reopened_prefix
        current += part
        open_fence_lang = _update_fence_state(open_fence_lang, part)
    return current, open_fence_lang


def _to_segments(text: str) -> list[str]:
    segments: list[str] = []
    buffer = ""
    for line in text.splitlines(keepends=True):
        if not line:
            continue
        buffer += line
        if line.endswith("\n"):
            segments.append(buffer)
            buffer = ""
    if buffer:
        segments.append(buffer)
    return segments or [text]


def _split_long_segment(segment: str, limit: int, *, prefix: str = "") -> list[str]:
    parts: list[str] = []
    remaining = segment
    while remaining:
        room = max(limit - len(prefix), 80)
        if len(remaining) <= room:
            parts.append(remaining)
            break
        window = remaining[:room]
        cut = _best_breakpoint(window)
        parts.append(remaining[:cut])
        remaining = remaining[cut:]
        prefix = ""
    return parts


def _best_breakpoint(window: str) -> int:
    candidates = [
        window.rfind("\n\n"),
        window.rfind("\n"),
    ]
    punctuation = max(window.rfind(mark) for mark in ("。", "！", "？", ".", "!", "?", "；", ";"))
    if punctuation >= 40:
        candidates.append(punctuation + 1)
    space = window.rfind(" ")
    if space >= 40:
        candidates.append(space + 1)
    cut = max(candidates)
    if cut <= 0:
        return len(window)
    return cut


def _update_fence_state(open_fence_lang: str | None, text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        match = CODE_FENCE_RE.match(stripped)
        if not match:
            continue
        if open_fence_lang is None:
            open_fence_lang = match.group(1) or ""
        else:
            open_fence_lang = None
    return open_fence_lang


def _close_and_reopen_if_needed(current: str, open_fence_lang: str | None) -> tuple[str, str]:
    if open_fence_lang is None:
        return current, ""
    closed = current.rstrip() + "\n```"
    prefix = f"```{open_fence_lang}\n"
    return closed, prefix
