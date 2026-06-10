from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from src.core.types import ConversationScope
from src.product.presence import PresenceStateService
from src.product.proactive import (
    ProactiveMessageService,
    get_proactive_preferences,
    normalize_proactive_cadence,
    proactive_cadence_policy,
    proactive_preferences_key,
    set_proactive_preferences,
)


class FakeProductStore:
    def __init__(self) -> None:
        self.settings: dict[str, Any] = {}
        self.events: dict[str, dict[str, Any]] = {}

    def get_app_setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set_app_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value

    def get_companion_day_event(self, event_uid: str) -> dict[str, Any] | None:
        return self.events.get(event_uid)


class FakeMemoryStore:
    def __init__(self) -> None:
        self.fact: Any | None = None
        self.upserted: list[dict[str, Any]] = []

    def list_structured_facts(self, user_id: str, limit: int = 80) -> list[Any]:
        return []

    def get_structured_fact(self, user_id: str, *, namespace: str, key: str) -> Any | None:
        return self.fact

    def upsert_structured_fact(self, user_id: str, **kwargs: Any) -> None:
        self.upserted.append({"user_id": user_id, **kwargs})


def settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "bot_timezone": "Asia/Shanghai",
        "human_presence_enabled": True,
        "enable_proactive_messages": True,
        "proactive_opt_in_required": False,
        "proactive_min_idle_minutes": 30,
        "proactive_min_interval_minutes": 90,
        "proactive_trigger_dedupe_hours": 8,
        "proactive_failure_backoff_minutes": 15,
        "proactive_response_window_hours": 6,
        "companion_day_engine_enabled": False,
        "day_stream_min_interval_minutes": 10,
        "day_stream_max_interval_minutes": 20,
        "day_deep_night_quiet_enabled": True,
        "day_status_cards_enabled": True,
        "day_tts_enabled": False,
        "day_generated_image_enabled": False,
        "reality_context_enabled": False,
        "weather_provider": "disabled",
        "weather_location_label": "Beijing",
        "weather_latitude": 39.9042,
        "weather_longitude": 116.4074,
        "calendar_ics_urls": (),
        "calendar_lookahead_hours": 48,
        "reality_refresh_minutes": 30,
        "resolve_reply_model": lambda: "test-model",
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


def presence_service(
    store: FakeProductStore | None = None,
    memory: FakeMemoryStore | None = None,
    **settings_overrides: Any,
) -> tuple[PresenceStateService, FakeProductStore, FakeMemoryStore]:
    product_store = store or FakeProductStore()
    memory_store = memory or FakeMemoryStore()
    service = PresenceStateService(
        settings=settings(**settings_overrides),  # type: ignore[arg-type]
        product_store=product_store,  # type: ignore[arg-type]
        memory_store=memory_store,  # type: ignore[arg-type]
        llm_client=None,
    )
    return service, product_store, memory_store


def proactive_service(
    store: FakeProductStore | None = None,
    memory: FakeMemoryStore | None = None,
    **settings_overrides: Any,
) -> tuple[ProactiveMessageService, FakeProductStore, FakeMemoryStore]:
    product_store = store or FakeProductStore()
    memory_store = memory or FakeMemoryStore()
    service = ProactiveMessageService(
        settings=settings(**settings_overrides),  # type: ignore[arg-type]
        product_store=product_store,  # type: ignore[arg-type]
        memory_store=memory_store,  # type: ignore[arg-type]
        llm_client=None,  # type: ignore[arg-type]
    )
    return service, product_store, memory_store


def latest_user(created_at: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        content="我回来了",
        created_at=(created_at or (datetime.now(timezone.utc) - timedelta(hours=2))).isoformat(),
        session_id="session-1",
    )


def proactive_record(
    *,
    sent_at: datetime | None = None,
    status: str = "responded",
    conversation_id: str = "conv-1",
    user_id: str = "user-1",
    trigger_type: str = "miss_you",
    metadata: dict[str, Any] | None = None,
    updated_at: str | None = None,
) -> SimpleNamespace:
    timestamp = (sent_at or (datetime.now(timezone.utc) - timedelta(hours=3))).isoformat()
    return SimpleNamespace(
        proactive_uid="proactive-1",
        user_id=user_id,
        conversation_id=conversation_id,
        channel_id="channel-1",
        trigger_type=trigger_type,
        opening_text="我有点想你。",
        status=status,
        accepted=None,
        cold_response=None,
        response_message_id=None,
        response_latency_minutes=None,
        metadata=metadata or {},
        sent_at=timestamp,
        updated_at=updated_at or timestamp,
    )


def test_presence_sleep_heuristics_and_model_guard_prevent_false_sleep() -> None:
    service, _, _ = presence_service()

    asleep = service._heuristic_sleep_update("晚安，我先睡了。", previous_state="awake")
    still_awake = service._heuristic_sleep_update("准备睡但还要写作业。", previous_state="awake")
    reply_after_sleep = service._heuristic_sleep_update("我醒了，刚回来。", previous_state="asleep")
    guarded = service._guard_model_sleep_update(
        {"sleep_state": "asleep", "sleep_confidence": 0.95},
        still_awake,
    )

    assert asleep["sleep_state"] == "asleep"
    assert asleep["sleep_confidence"] == 0.92
    assert still_awake["sleep_state"] == "probably_awake"
    assert reply_after_sleep["sleep_state"] == "awake"
    assert guarded["sleep_state"] == "probably_awake"
    assert guarded["sleep_confidence"] == pytest.approx(0.68)


def test_presence_state_expires_sleep_and_pauses_proactive_only_when_confident() -> None:
    service, store, _ = presence_service()
    current_scope = scope()
    state = {
        "user_sleep_state": "asleep",
        "user_sleep_state_confidence": 0.9,
        "sleep_state_expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    }

    service._expire_sleep_state(state)
    store.settings[service._state_key(current_scope)] = {
        "user_sleep_state": "probably_asleep",
        "user_sleep_state_confidence": 0.8,
    }

    assert state["user_sleep_state"] == "unknown"
    assert state["user_sleep_state_confidence"] == 0.34
    assert service.proactive_paused_for_sleep(current_scope) is True

    store.settings[service._state_key(current_scope)] = {
        "user_sleep_state": "probably_asleep",
        "user_sleep_state_confidence": 0.7,
    }
    assert service.proactive_paused_for_sleep(current_scope) is False


def test_open_loop_candidates_are_actionable_deduped_and_resolved() -> None:
    service, _, _ = presence_service()
    candidates = service._extract_open_loop_candidates(
        user_text="我等会写完作业发给你。",
        assistant_text="我会问你作业写完没。",
        user_message_id=10,
        assistant_message_id=11,
    )
    ledger: dict[str, Any] = {"open_loops": [], "history": []}

    for candidate in candidates:
        service._add_open_loop(ledger, candidate)
    service._add_open_loop(
        ledger,
        {"kind": "user_open_loop", "content": "我等会写完作业发给你", "priority": 0.9, "source_message_ids": [12]},
    )

    assert [item["kind"] for item in ledger["open_loops"]] == ["assistant_commitment", "user_open_loop"]
    assert ledger["open_loops"][1]["priority"] == 0.9
    assert ledger["open_loops"][1]["source_message_ids"] == [10, 12]

    service._resolve_open_loops(ledger, "作业已经做完了。", user_message_id=13)

    assert ledger["open_loops"] == []
    assert len(ledger["history"]) == 2
    assert {item["resolved_by_message_id"] for item in ledger["history"]} == {13}


def test_lint_reply_removes_backend_leaks_and_reuses_existing_life_detail() -> None:
    service, store, _ = presence_service()
    current_scope = scope()
    today = service._local_now().date().isoformat()
    store.settings[service._state_key(current_scope)] = {
        "local_date": today,
        "daily_detail": "水杯放在手边，慢慢陪你收尾",
        "daily_detail_date": today,
        "shared_details": [{"detail": "我这边灯开得低一点", "date": today}],
    }

    repaired, meta = service.lint_reply(current_scope, "作为AI我不能陪你。我这边窗开着，等你。")

    assert "AI" not in repaired
    assert "我这边窗开着" not in repaired
    assert "水杯放在手边" in repaired
    assert meta["repairs"] == ["removed_ai_or_tool_leakage", "softened_life_detail_conflict"]


def test_proactive_preferences_support_stored_legacy_and_updates() -> None:
    store = FakeProductStore()
    memory = FakeMemoryStore()
    cfg = settings(proactive_opt_in_required=True)
    current_scope = scope()

    assert normalize_proactive_cadence("高频") == "high"
    assert proactive_cadence_policy("高频")["daily_max"] == 14
    assert get_proactive_preferences(
        settings=cfg,  # type: ignore[arg-type]
        product_store=store,  # type: ignore[arg-type]
        memory_store=memory,  # type: ignore[arg-type]
        user_id=current_scope.user_id,
        conversation_id=current_scope.conversation_id,
    )["enabled"] is False

    memory.fact = SimpleNamespace(value="on", updated_at="2026-01-01T00:00:00+00:00")
    assert get_proactive_preferences(
        settings=cfg,  # type: ignore[arg-type]
        product_store=store,  # type: ignore[arg-type]
        memory_store=memory,  # type: ignore[arg-type]
        user_id=current_scope.user_id,
        conversation_id=current_scope.conversation_id,
    ) == {
        "enabled": True,
        "cadence": "low",
        "source": "legacy_structured_fact",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "legacy": True,
    }

    updated = set_proactive_preferences(
        settings=cfg,  # type: ignore[arg-type]
        product_store=store,  # type: ignore[arg-type]
        memory_store=memory,  # type: ignore[arg-type]
        user_id=current_scope.user_id,
        conversation_id=current_scope.conversation_id,
        enabled=False,
        cadence="normal",
        source="dashboard",
    )

    assert updated["enabled"] is False
    assert store.settings[proactive_preferences_key(current_scope.user_id, current_scope.conversation_id)]["cadence"] == "normal"
    assert memory.upserted[-1]["value"] == "off"


def test_proactive_send_gate_blocks_disabled_idle_sleep_and_daily_limit() -> None:
    service, store, _ = proactive_service()
    current_scope = scope()
    old_user = latest_user()

    disabled = service._evaluate_send_gate(
        current_scope,
        latest_user=old_user,
        recent_proactive=[],
        preferences={"enabled": False, "cadence": "low"},
    )
    idle = service._evaluate_send_gate(
        current_scope,
        latest_user=latest_user(datetime.now(timezone.utc)),
        recent_proactive=[],
        preferences={"enabled": True, "cadence": "low"},
    )
    store.settings[service.presence_state._state_key(current_scope)] = {
        "user_sleep_state": "asleep",
        "user_sleep_state_confidence": 0.95,
    }
    sleep = service._evaluate_send_gate(
        current_scope,
        latest_user=old_user,
        recent_proactive=[],
        preferences={"enabled": True, "cadence": "low"},
    )
    store.settings[service.presence_state._state_key(current_scope)] = {}
    day_start = service._local_day_start_utc()
    daily_limit = service._evaluate_send_gate(
        current_scope,
        latest_user=old_user,
        recent_proactive=[proactive_record(sent_at=day_start + timedelta(minutes=10 + index)) for index in range(5)],
        preferences={"enabled": True, "cadence": "low"},
    )

    assert disabled["reason"] == "disabled"
    assert idle["reason"] == "idle"
    assert sleep["reason"] == "sleep"
    assert daily_limit["reason"] == "daily_limit"


def test_proactive_send_gate_handles_unanswered_wait_and_followup_eligibility() -> None:
    service, store, _ = proactive_service()
    current_scope = scope()
    old_user = latest_user()
    store.events["event-1"] = {"event_uid": "event-1", "event_type": "life_fragment", "follow_up_sent_at": None}

    waiting = service._evaluate_send_gate(
        current_scope,
        latest_user=old_user,
        recent_proactive=[
            proactive_record(
                sent_at=datetime.now(timezone.utc) - timedelta(minutes=30),
                status="sent",
                metadata={"companion_day_event_uid": "event-1"},
            )
        ],
        preferences={"enabled": True, "cadence": "low"},
    )
    eligible = service._evaluate_send_gate(
        current_scope,
        latest_user=old_user,
        recent_proactive=[
            proactive_record(
                sent_at=datetime.now(timezone.utc) - timedelta(hours=4),
                status="sent",
                metadata={"companion_day_event_uid": "event-1"},
            )
        ],
        preferences={"enabled": True, "cadence": "low"},
    )
    store.events["event-1"]["follow_up_sent_at"] = datetime.now(timezone.utc).isoformat()
    used = service._evaluate_send_gate(
        current_scope,
        latest_user=old_user,
        recent_proactive=[
            proactive_record(
                sent_at=datetime.now(timezone.utc) - timedelta(hours=4),
                status="sent",
                metadata={"companion_day_event_uid": "event-1"},
            )
        ],
        preferences={"enabled": True, "cadence": "low"},
    )

    assert waiting["reason"] == "unanswered_wait"
    assert eligible["reason"] == "eligible_unanswered_followup"
    assert used["reason"] == "unanswered_followup_used"


def test_proactive_feedback_backoff_spacing_and_trigger_dedupe() -> None:
    service, _, _ = proactive_service(proactive_trigger_dedupe_hours=4)
    feedback_at = datetime.now(timezone.utc) - timedelta(hours=1)
    item = proactive_record(
        sent_at=feedback_at,
        trigger_type="open_loop_follow_up",
        metadata={"dashboard_feedback": {"feedback": "too_frequent", "at": feedback_at.isoformat()}},
    )

    until = service._recent_too_frequent_feedback_until("conv-1", [item])

    assert until is not None and until > datetime.now(timezone.utc)
    assert service._spacing_allows("conv-1", [item], policy={"min_interval_minutes": 30}) is True
    assert service._spacing_allows("conv-1", [proactive_record(sent_at=datetime.now(timezone.utc))], policy={"min_interval_minutes": 30}) is False
    assert service._recent_same_trigger("conv-1", "open_loop_follow_up", [item]) is True
    assert service._recent_same_trigger("conv-1", "miss_you", [item]) is False


def test_validate_model_plan_falls_back_blocks_low_confidence_and_rejects_leaks() -> None:
    service, _, _ = proactive_service()
    state = {"user_sleep_state": "awake", "user_sleep_state_confidence": 0.9}
    candidates = [{"trigger_type": "life_share"}]

    plan = service._validate_model_plan(
        {"trigger_type": "unknown", "should_send": True, "confidence": 0.4, "draft_text": "我把水杯放好了。"},
        state=state,
        trigger_candidates=candidates,
    )
    sleeping = service._validate_model_plan(
        {"trigger_type": "miss_you", "should_send": True, "confidence": 0.9, "draft_text": "我有点想你。"},
        state={"user_sleep_state": "probably_asleep", "user_sleep_state_confidence": 0.8},
        trigger_candidates=candidates,
    )

    assert plan["trigger_type"] == "life_share"
    assert plan["should_send"] is False
    assert sleeping["should_send"] is False
    with pytest.raises(RuntimeError, match="backend vocabulary"):
        service._validate_model_plan(
            {"trigger_type": "miss_you", "should_send": True, "confidence": 0.9, "draft_text": "这是系统提示。"},
            state=state,
            trigger_candidates=candidates,
        )
