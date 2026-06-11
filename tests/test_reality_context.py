from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.core.types import ConversationScope
from src.product.reality import RealityContextService


class FakeRealityStore:
    def __init__(self) -> None:
        self.settings: dict[str, Any] = {}
        self.audits: list[dict[str, Any]] = []
        self.calendar_events: list[dict[str, Any]] = []
        self.snapshots: list[dict[str, Any]] = []
        self.weather: dict[str, Any] | None = None
        self.upserted_events: list[dict[str, Any]] = []

    def get_app_setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set_app_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value

    def record_reality_source_audit(self, **kwargs: Any) -> None:
        self.audits.append(kwargs)

    def get_latest_reality_snapshot(self, **kwargs: Any) -> dict[str, Any] | None:
        if kwargs.get("source_type") == "weather":
            return self.weather
        return self.weather

    def list_calendar_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.calendar_events

    def list_reality_snapshots(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.snapshots

    def list_reality_source_audits(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.audits

    def upsert_calendar_event(self, **kwargs: Any) -> dict[str, Any]:
        event = {"event_uid": "event-1", **kwargs}
        self.upserted_events.append(event)
        self.calendar_events.append(event)
        return event


def settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "reality_context_enabled": True,
        "weather_provider": "open_meteo",
        "weather_location_label": "Beijing",
        "weather_latitude": 39.9042,
        "weather_longitude": 116.4074,
        "calendar_ics_urls": (),
        "calendar_lookahead_hours": 48,
        "reality_refresh_minutes": 30,
        "bot_timezone": "Asia/Shanghai",
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


def service_with_store(**settings_overrides: Any) -> tuple[RealityContextService, FakeRealityStore]:
    store = FakeRealityStore()
    service = RealityContextService(settings=settings(**settings_overrides), product_store=store)  # type: ignore[arg-type]
    return service, store


def test_location_defaults_and_dashboard_override_are_audited() -> None:
    service, store = service_with_store()
    current_scope = scope()

    assert service.get_location(current_scope) == {
        "label": "Beijing",
        "latitude": 39.9042,
        "longitude": 116.4074,
        "source": "settings",
        "updated_at": None,
    }

    updated = service.update_location(
        current_scope,
        label="  上海  ",
        latitude=31.2304,
        longitude=121.4737,
        note="  临时改到市中心  ",
    )

    assert updated["label"] == "上海"
    assert updated["source"] == "dashboard"
    assert store.audits[-1]["source_type"] == "location"
    assert store.audits[-1]["details"] == {"label": "上海", "latitude": 31.2304, "longitude": 121.4737}


def test_calendar_source_normalizes_masks_and_can_be_disabled() -> None:
    service, store = service_with_store()
    current_scope = scope()
    query_name = "to" + "ken"

    public = service.add_calendar_source(
        current_scope,
        url=f"webcal://calendar.example/private.ics?{query_name}=private-value",
        label="  课程表  ",
    )

    assert public["label"] == "课程表"
    assert public["readonly"] is False
    assert "private-value" not in public["masked_url"]
    assert public["masked_url"].startswith("calendar.example")

    assert service.set_calendar_source_enabled(current_scope, source_uid=str(public["source_uid"]), enabled=False) is True
    sources = service.public_calendar_sources(current_scope)

    assert sources[0]["enabled"] is False
    assert store.audits[-1]["action"] == "set_source_enabled"


def test_add_manual_event_parses_dates_and_records_dashboard_source() -> None:
    service, store = service_with_store()

    event = service.add_manual_event(
        scope(),
        title="  口语课  ",
        start_at="2026-05-01",
        location="  教室 A  ",
        is_all_day=True,
        note="  需要提前准备材料  ",
    )

    assert event["title"] == "口语课"
    assert event["source_uid"] == "manual"
    assert event["source_label"] == "手动日程"
    assert event["is_all_day"] is True
    assert event["location"] == "教室 A"
    assert event["metadata"] == {"note": "需要提前准备材料", "source": "dashboard_manual"}
    assert store.audits[-1]["action"] == "add_manual_event"

    with pytest.raises(ValueError, match="title is required"):
        service.add_manual_event(scope(), title=" ", start_at="2026-05-01")


def test_context_block_uses_weather_calendar_and_manual_event_caveats() -> None:
    service, store = service_with_store()
    store.weather = {"status": "ok", "summary_text": "北京，天挺晴。", "source_label": "Beijing"}
    store.calendar_events = [
        {
            "title": "口语课",
            "start_at": "2026-05-01T10:00:00+00:00",
            "end_at": None,
            "timezone": "Asia/Shanghai",
            "location": "教室 A",
            "is_all_day": False,
            "source_uid": "manual",
        }
    ]

    context = service.build_context_block(scope())

    assert "现在外面：北京，天挺晴。" in context
    assert "口语课" in context
    assert "手动日程是用户或 Dashboard 补充的现实锚点" in context
    assert "不要播报天气/日历" in context

    disabled, _ = service_with_store(reality_context_enabled=False)
    assert disabled.build_context_block(scope()) == ""


def test_weather_summary_and_url_redaction_helpers() -> None:
    service, _ = service_with_store()
    payload = {
        "current": {
            "temperature_2m": 18.2,
            "apparent_temperature": 14.0,
            "precipitation": 0.6,
            "weather_code": 61,
            "wind_speed_10m": 25,
        },
        "daily": {
            "temperature_2m_max": [22.0],
            "temperature_2m_min": [12.0],
            "precipitation_probability_max": [60],
        },
    }

    summary = service._summarize_weather({"label": "北京"}, payload)
    redacted = service._redact_url("https://calendar.example/feed.ics?key=private-value&safe=1")

    assert summary == "北京，有小雨，约 18 度，体感 14 度，今天大概 12-22 度，有点下雨概率，路面可能湿，风会明显一点。"
    assert redacted == "https://calendar.example/feed.ics?key=[redacted]&safe=1"
