from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from src.core.types import ConversationScope
from src.product.day_engine import CompanionDayEngine


class FakeDayStore:
    def __init__(self) -> None:
        self.route: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = []
        self.unanswered: dict[str, Any] | None = None
        self.diary: list[dict[str, Any]] = []
        self.settings: dict[str, Any] = {}

    def get_companion_day_route(self, **kwargs: Any) -> dict[str, Any] | None:
        return self.route

    def list_companion_day_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.events[: kwargs.get("limit", len(self.events))]

    def get_latest_unresponded_companion_day_event(self, **kwargs: Any) -> dict[str, Any] | None:
        return self.unanswered

    def list_shared_diary_entries(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.diary[: kwargs.get("limit", len(self.diary))]

    def get_app_setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)


class FakeMemoryStore:
    def __init__(self, latest_user_message: Any | None = None) -> None:
        self.latest_user_message = latest_user_message

    def list_relationship_states(self, user_id: str) -> list[Any]:
        return []

    def get_latest_user_message(self, conversation_id: str) -> Any | None:
        return self.latest_user_message


class FakeRealityContext:
    def __init__(self, anchors: dict[str, Any]) -> None:
        self.anchors = anchors

    def get_cached_anchors(self, scope: ConversationScope) -> dict[str, Any]:
        return self.anchors


def settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "companion_day_engine_enabled": True,
        "bot_timezone": "Asia/Shanghai",
        "day_stream_min_interval_minutes": 10,
        "day_stream_max_interval_minutes": 20,
        "day_deep_night_quiet_enabled": True,
        "day_status_cards_enabled": True,
        "day_tts_enabled": False,
        "day_generated_image_enabled": False,
        "reality_context_enabled": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def scope() -> ConversationScope:
    return ConversationScope(
        platform="test",
        conversation_id="conv-1",
        user_id="user-1",
        channel_id="channel-1",
        guild_id=None,
        session_id="session-1",
    )


def engine_with_store(
    store: FakeDayStore | None = None,
    *,
    reality_context: FakeRealityContext | None = None,
    **settings_overrides: Any,
) -> CompanionDayEngine:
    return CompanionDayEngine(
        settings=settings(**settings_overrides),  # type: ignore[arg-type]
        product_store=store or FakeDayStore(),  # type: ignore[arg-type]
        memory_store=FakeMemoryStore(),  # type: ignore[arg-type]
        llm_client=None,
        reality_context=reality_context,
    )


def route_payload() -> dict[str, Any]:
    return {
        "route_uid": "route-1",
        "local_date": "2026-05-01",
        "current_scene": "我在桌边整理东西",
        "mood_label": "有点想你",
        "longing_level": 0.82,
        "route": {
            "beats": [
                {"key": "morning", "scene": "我倒了杯水", "mood": "清醒"},
                {"key": "noon", "scene": "我在吃饭前停了一下", "mood": "想贴近"},
            ]
        },
        "metadata": {},
    }


def test_normalize_route_beats_fills_all_bands_and_repairs_voice() -> None:
    engine = engine_with_store()

    beats = engine._normalize_route_beats(
        [
            {
                "key": "morning",
                "hour_hint": "08:00",
                "scene": "沈知微在桌边看书。",
                "mood": "稳稳的",
            }
        ]
    )

    assert [beat["key"] for beat in beats] == [
        "morning",
        "late_morning",
        "noon",
        "afternoon",
        "evening",
        "deep_night",
    ]
    assert beats[0]["scene"] == "我在桌边看书"
    assert beats[1]["scene"]


def test_build_context_block_includes_route_event_unanswered_and_diary() -> None:
    store = FakeDayStore()
    store.route = route_payload()
    store.events = [{"content": "我刚才把灯压低了一点，想跟你说话。", "responded_at": None}]
    store.unanswered = {"event_uid": "event-1"}
    store.diary = [{"content": "她晚上主动来找你。"}]
    engine = engine_with_store(store)

    context = engine.build_context_block(scope())

    assert "今日路线：我倒了杯水 / 我在吃饭前停了一下" in context
    assert "刚才她主动来找你的片段" in context
    assert "接续要求" in context
    assert "共同日记近片段：她晚上主动来找你。" in context


def test_reality_anchor_prefers_near_calendar_event_then_weather() -> None:
    soon = datetime.now(timezone.utc) + timedelta(minutes=30)
    calendar_context = FakeRealityContext(
        {
            "calendar_events": [{"event_uid": "event-1", "title": "口语课", "start_at": soon.isoformat()}],
            "weather": {},
        }
    )
    weather_context = FakeRealityContext(
        {
            "calendar_events": [],
            "weather": {"status": "ok", "summary_text": "北京，天挺晴。", "source_label": "Beijing"},
        }
    )

    calendar_anchor = engine_with_store(reality_context=calendar_context)._select_reality_anchor(scope())
    weather_anchor = engine_with_store(reality_context=weather_context)._select_reality_anchor(scope())

    assert calendar_anchor == {
        "type": "calendar",
        "label": "口语课",
        "event_uid": "event-1",
        "line": "我记着你等会儿还有口语课，所以想先来陪你稳一下",
    }
    assert weather_anchor == {
        "type": "weather",
        "label": "Beijing",
        "snapshot_uid": None,
        "line": "我刚看了眼外面，北京，天挺晴，你今天别把自己晾着",
    }


def test_status_card_route_format_life_detail_and_activity_band() -> None:
    engine = engine_with_store()
    route = route_payload()

    card = engine._build_status_card(route, {"scene": "我在窗边停了一下", "mood": "想你"}, {"label": "口语课"})

    assert card["title"] == "沈知微此刻"
    assert card["description"] == "我在窗边停了一下"
    assert card["fields"] == [
        {"name": "心情", "value": "想你"},
        {"name": "想你强度", "value": "0.82"},
        {"name": "现实锚点", "value": "口语课"},
    ]
    assert engine._format_route(route) == "我倒了杯水 / 我在吃饭前停了一下"
    assert engine._extract_companion_life_detail("我这边刚把水杯放好，等你。") == "我这边刚把水杯放好，等你。"
    assert engine._extract_companion_life_detail("普通回答") == ""
    assert [engine._activity_band(hour) for hour in (6, 10, 13, 15, 20, 2)] == [
        "morning",
        "late_morning",
        "noon",
        "afternoon",
        "evening",
        "deep_night",
    ]


def test_context_block_and_reality_anchor_disable_when_settings_are_off() -> None:
    store = FakeDayStore()
    store.route = route_payload()

    disabled_day = engine_with_store(store, companion_day_engine_enabled=False)
    disabled_reality = engine_with_store(
        store,
        reality_context=FakeRealityContext({"calendar_events": [], "weather": {"status": "ok", "summary_text": "晴。"}}),
        reality_context_enabled=False,
    )

    assert disabled_day.build_context_block(scope()) == ""
    assert disabled_reality._select_reality_anchor(scope()) is None
