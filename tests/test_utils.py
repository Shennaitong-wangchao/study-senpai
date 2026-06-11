from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.utils.json_utils import extract_json_object, get_json_extraction_stats, json_dumps, json_loads
from src.utils.text_utils import compact_text, overlap_score, strip_discord_mentions, tokenize, truncate_text
from src.utils.time_utils import add_minutes, build_current_time_context, current_local_time, parse_iso8601


def test_json_helpers_preserve_unicode_and_return_defaults() -> None:
    assert json_dumps({"text": "学习"}) == '{"text":"学习"}'
    assert json_loads('{"ok": true}', {}) == {"ok": True}
    assert json_loads("", {"fallback": True}) == {"fallback": True}
    assert json_loads("{bad", {"fallback": True}) == {"fallback": True}


def test_extract_json_object_accepts_exact_fenced_and_wrapped_json() -> None:
    assert extract_json_object('{"scene":"study"}') == {"scene": "study"}
    assert extract_json_object('```json\n{"scene":"focus"}\n```') == {"scene": "focus"}
    assert extract_json_object('prefix {"scene":"review"} suffix') == {"scene": "review"}

    stats = get_json_extraction_stats()
    assert stats["counters"]["success"] >= 3
    assert stats["recent"]


def test_extract_json_object_raises_when_object_is_missing() -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json_object("plain text only")


def test_text_helpers_compact_truncate_tokenize_and_score() -> None:
    assert compact_text("  今天\n\n  学习\t复盘  ") == "今天 学习 复盘"
    assert truncate_text("abcdef", 4) == "abc…"
    assert tokenize("Study 学习 study!") == ["study", "学习", "study"]
    assert overlap_score("学习 复盘", "今天学习之后复盘") == 0.0
    assert overlap_score("study review", "study plan") == 0.5


def test_strip_discord_mentions_handles_both_mention_forms() -> None:
    assert strip_discord_mentions("<@123> 你好 <@!123>", 123) == "你好"
    assert strip_discord_mentions("<@123> 你好", None) == "<@123> 你好"


def test_time_helpers_parse_add_and_build_context() -> None:
    parsed = parse_iso8601("2026-04-28T10:00:00+00:00")
    assert parsed == datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc)
    assert add_minutes(parsed, 45).isoformat() == "2026-04-28T10:45:00+00:00"

    context = build_current_time_context("Asia/Shanghai")
    assert "当前本地时间" in context
    assert "相对时间" in context


def test_current_local_time_falls_back_to_utc_for_unknown_timezone() -> None:
    current = current_local_time("Not/A_Zone")
    assert current.tzinfo is timezone.utc
