from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import discord

from src.core.settings import Settings
from src.core.types import ConversationScope
from src.llm.client import LLMClient
from src.llm.prompts.proactive import PROACTIVE_PLANNER_SYSTEM_PROMPT, build_proactive_planner_user_prompt
from src.memory.store import MemoryStore
from src.persona.immersion_lint import repair_immersive_voice
from src.product.day_engine import CompanionDayEngine
from src.product.human_delivery import send_human_message_parts
from src.product.presence import PresenceStateService
from src.product.reality import RealityContextService
from src.product.store import ProductStore
from src.utils.text_utils import compact_text, truncate_text
from src.utils.time_utils import iso_utc_now, parse_iso8601


ACTIONABLE_MEMORY_TYPES = {"project_context", "study_context", "routine_pattern"}
CARE_MEMORY_TYPES = {"emotional_context", "care_history", "support_preference"}
RELATIONSHIP_TONE_TYPES = {"commitment_record", "relationship_state", "relationship_preference"}
ABSTRACT_MEMORY_BLOCKLIST = (
    "沈知微承诺",
    "承诺成为",
    "最稳固",
    "后方",
    "确定感",
    "依靠",
    "外部世界",
    "关系底色",
    "用户最",
    "女友",
    "伴侣",
    "亲密",
    "AI",
    "模型",
    "系统",
)
ACTIONABLE_TOPIC_TOKENS = (
    "作业",
    "学习",
    "复习",
    "考试",
    "代码",
    "项目",
    "提交",
    "修",
    "写",
    "看",
    "查",
    "发",
    "做",
    "喝水",
    "吃药",
    "热水",
    "肚子",
    "头疼",
    "疼",
    "休息",
    "睡",
    "吃饭",
    "没收完",
    "回头",
    "待会",
    "明天",
)

PROACTIVE_DEFAULT_CADENCE = "low"
PROACTIVE_CADENCE_POLICIES: dict[str, dict[str, int]] = {
    "low": {
        "min_idle_minutes": 45,
        "min_interval_minutes": 180,
        "max_interval_minutes": 240,
        "daily_max": 4,
        "unanswered_followup_minutes": 180,
    },
    "normal": {
        "min_idle_minutes": 25,
        "min_interval_minutes": 90,
        "max_interval_minutes": 150,
        "daily_max": 8,
        "unanswered_followup_minutes": 120,
    },
    "high": {
        "min_idle_minutes": 12,
        "min_interval_minutes": 35,
        "max_interval_minutes": 70,
        "daily_max": 14,
        "unanswered_followup_minutes": 60,
    },
}
PROACTIVE_CADENCE_ALIASES = {
    "low": "low",
    "低": "low",
    "低频": "low",
    "少一点": "low",
    "normal": "normal",
    "medium": "normal",
    "中": "normal",
    "中频": "normal",
    "默认": "normal",
    "high": "high",
    "高": "high",
    "高频": "high",
    "多一点": "high",
}


def normalize_proactive_cadence(raw: Any) -> str | None:
    normalized = str(raw or "").strip().lower()
    if not normalized:
        return None
    return PROACTIVE_CADENCE_ALIASES.get(normalized)


def proactive_preferences_key(user_id: str, conversation_id: str) -> str:
    return f"proactive_preferences:{user_id}:{conversation_id}"


def proactive_backoff_key(conversation_id: str) -> str:
    return f"proactive_backoff:{conversation_id}"


def get_proactive_preferences(
    *,
    settings: Settings,
    product_store: ProductStore,
    memory_store: MemoryStore,
    user_id: str,
    conversation_id: str,
) -> dict[str, Any]:
    stored = product_store.get_app_setting(proactive_preferences_key(user_id, conversation_id), None)
    if isinstance(stored, dict):
        enabled = stored.get("enabled")
        cadence = normalize_proactive_cadence(stored.get("cadence")) or PROACTIVE_DEFAULT_CADENCE
        if isinstance(enabled, bool):
            return {
                "enabled": enabled,
                "cadence": cadence,
                "source": str(stored.get("source") or "stored"),
                "updated_at": str(stored.get("updated_at") or ""),
                "legacy": False,
            }

    legacy = memory_store.get_structured_fact(
        user_id,
        namespace="support",
        key="proactive_opt_in",
    )
    if legacy is not None:
        raw_value = legacy.value.strip().lower()
        if raw_value in {"off", "false", "no", "disabled"}:
            enabled = False
        elif raw_value in {"on", "true", "yes", "enabled"}:
            enabled = True
        else:
            enabled = not settings.proactive_opt_in_required
        return {
            "enabled": enabled,
            "cadence": PROACTIVE_DEFAULT_CADENCE,
            "source": "legacy_structured_fact",
            "updated_at": legacy.updated_at,
            "legacy": True,
        }

    return {
        "enabled": not settings.proactive_opt_in_required,
        "cadence": PROACTIVE_DEFAULT_CADENCE,
        "source": "default",
        "updated_at": "",
        "legacy": False,
    }


def set_proactive_preferences(
    *,
    settings: Settings,
    product_store: ProductStore,
    memory_store: MemoryStore,
    user_id: str,
    conversation_id: str,
    enabled: bool | None = None,
    cadence: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    current = get_proactive_preferences(
        settings=settings,
        product_store=product_store,
        memory_store=memory_store,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    selected_cadence = normalize_proactive_cadence(cadence) if cadence is not None else str(current["cadence"])
    if selected_cadence is None:
        raise ValueError("cadence must be low, normal, or high")
    selected_enabled = bool(current["enabled"]) if enabled is None else bool(enabled)
    now = iso_utc_now()
    payload = {
        "enabled": selected_enabled,
        "cadence": selected_cadence,
        "source": source,
        "updated_at": now,
    }
    product_store.set_app_setting(proactive_preferences_key(user_id, conversation_id), payload)
    if enabled is not None:
        memory_store.upsert_structured_fact(
            user_id,
            namespace="support",
            key="proactive_opt_in",
            value="on" if selected_enabled else "off",
            confidence=1.0,
            source_message_ids=[],
            metadata={"source": source, "conversation_id": conversation_id},
        )
    return {**payload, "legacy": False}


def proactive_cadence_policy(cadence: str | None) -> dict[str, int]:
    normalized = normalize_proactive_cadence(cadence) or PROACTIVE_DEFAULT_CADENCE
    return dict(PROACTIVE_CADENCE_POLICIES[normalized])


class ProactiveMessageService:
    def __init__(
        self,
        *,
        settings: Settings,
        memory_store: MemoryStore,
        product_store: ProductStore,
        llm_client: LLMClient,
    ) -> None:
        self.settings = settings
        self.memory_store = memory_store
        self.product_store = product_store
        self.llm_client = llm_client
        self.presence_state = PresenceStateService(
            settings=settings,
            product_store=product_store,
            memory_store=memory_store,
            llm_client=llm_client,
        )
        self.reality_context = RealityContextService(
            settings=settings,
            product_store=product_store,
        )
        self.day_engine = CompanionDayEngine(
            settings=settings,
            product_store=product_store,
            memory_store=memory_store,
            llm_client=llm_client,
            reality_context=self.reality_context,
        )

    async def scan_and_send(self, client: discord.Client) -> dict[str, Any]:
        expiring_items = self._list_expiring_proactive_messages(
            idle_hours=self.settings.proactive_response_window_hours,
        )
        expired = self.product_store.mark_stale_proactive_messages(
            idle_hours=self.settings.proactive_response_window_hours,
        )
        for item in expiring_items:
            self.presence_state.record_proactive_expired(
                ConversationScope(
                    platform="discord",
                    conversation_id=item.conversation_id,
                    user_id=item.user_id,
                    channel_id=item.channel_id,
                    guild_id=None,
                    session_id="proactive-expiry",
                ),
                proactive_uid=item.proactive_uid,
                trigger_type=item.trigger_type,
                opening_text=item.opening_text,
            )
        sent = 0
        skipped_sleep = 0
        skipped_interval = 0
        skipped_disabled = 0
        skipped_idle = 0
        skipped_daily_limit = 0
        skipped_backoff = 0
        skipped_unanswered = 0
        if not self.settings.enable_proactive_messages:
            return {
                "expired": expired,
                "sent": sent,
                "skipped_sleep": skipped_sleep,
                "skipped_interval": skipped_interval,
                "skipped_disabled": skipped_disabled,
                "skipped_idle": skipped_idle,
                "skipped_daily_limit": skipped_daily_limit,
                "skipped_backoff": skipped_backoff,
                "skipped_unanswered": skipped_unanswered,
            }
        if not client.is_ready():
            return {
                "expired": expired,
                "sent": sent,
                "skipped_sleep": skipped_sleep,
                "skipped_interval": skipped_interval,
                "skipped_client_not_ready": 1,
            }

        recent_conversations = self.memory_store.list_recent_conversations(limit=12)
        recent_proactive = self.product_store.list_proactive_messages(limit=200)
        for conversation in recent_conversations:
            conversation_id = conversation["conversation_id"]
            latest_user = self.memory_store.get_latest_user_message(conversation_id)
            scope = ConversationScope(
                platform="discord",
                conversation_id=conversation_id,
                user_id=conversation["user_id"],
                channel_id=conversation["channel_id"],
                guild_id=conversation["guild_id"],
                session_id=latest_user.session_id if latest_user is not None else "proactive-scan",
            )
            preferences = get_proactive_preferences(
                settings=self.settings,
                product_store=self.product_store,
                memory_store=self.memory_store,
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
            )
            gate = self._evaluate_send_gate(
                scope,
                latest_user=latest_user,
                recent_proactive=recent_proactive,
                preferences=preferences,
            )
            if not gate["allowed"]:
                reason = str(gate.get("reason") or "skipped")
                if reason == "disabled":
                    skipped_disabled += 1
                elif reason == "sleep":
                    skipped_sleep += 1
                elif reason == "idle":
                    skipped_idle += 1
                elif reason == "daily_limit":
                    skipped_daily_limit += 1
                elif reason == "backoff":
                    skipped_backoff += 1
                elif reason.startswith("unanswered"):
                    skipped_unanswered += 1
                else:
                    skipped_interval += 1
                continue
            policy = gate["policy"]
            channel_id = conversation["channel_id"]
            try:
                channel = client.get_channel(int(channel_id))
                if channel is None:
                    channel = await client.fetch_channel(int(channel_id))
            except Exception as exc:  # noqa: BLE001
                self._set_backoff(conversation_id, f"channel resolve failed: {exc}")
                continue
            if channel is None:
                continue
            context_pack = self.build_proactive_context_pack(scope, latest_user=latest_user)
            if self.settings.companion_day_engine_enabled:
                if self.settings.reality_context_enabled:
                    await self.reality_context.refresh_if_stale(scope)
                try:
                    plan = await self.day_engine.plan_next_event(
                        scope,
                        proactive_context=context_pack,
                        cadence_policy=policy,
                    )
                except Exception as exc:  # noqa: BLE001
                    self._record_model_failure(conversation_id, "day_engine_plan", exc)
                    continue
                if plan is None:
                    skipped_interval += 1
                    continue
                self.presence_state.record_trigger_plan(scope, plan)
                trigger_type = str(plan["trigger_type"])
            else:
                if not self._spacing_allows(conversation_id, recent_proactive, policy=policy):
                    skipped_interval += 1
                    continue
                try:
                    plan = await self._plan_trigger(scope, recent_proactive, context_pack=context_pack)
                except Exception as exc:  # noqa: BLE001
                    self._record_model_failure(conversation_id, "proactive_plan", exc)
                    continue
                self.presence_state.record_trigger_plan(scope, plan)
                if not plan.get("should_send", True):
                    skipped_interval += 1
                    continue
                trigger_type = str(plan["trigger_type"])
                if self._recent_same_trigger(conversation_id, trigger_type, recent_proactive):
                    skipped_interval += 1
                    continue
            content = str(plan.get("content") or plan.get("draft_text") or "")
            if not content.strip():
                self._record_model_failure(conversation_id, "empty_proactive_content", RuntimeError("empty model content"))
                continue
            try:
                await self._send_planned_message(channel, content, plan)
            except Exception as exc:  # noqa: BLE001
                self._set_backoff(conversation_id, str(exc))
                continue
            proactive_uid = self.product_store.create_proactive_message(
                user_id=conversation["user_id"],
                conversation_id=conversation_id,
                channel_id=channel_id,
                trigger_type=trigger_type,
                opening_text=content,
                metadata={
                    "latest_user_message_id": latest_user.id,
                    "presence_state": self.presence_state.get_state(scope),
                    "proactive_preferences": preferences,
                    "cadence_policy": policy,
                    "context_pack_counts": self._context_pack_counts(context_pack),
                    "trigger_plan": plan,
                    "reality_anchor": plan.get("reality_anchor") or {},
                },
            )
            if plan.get("source") == "companion_day_engine":
                event = self.day_engine.record_event_sent(
                    scope,
                    plan=plan,
                    proactive_uid=proactive_uid,
                )
                self.product_store.update_proactive_metadata(
                    proactive_uid,
                    {"companion_day_event_uid": event["event_uid"], "companion_day_route_uid": event["route_uid"]},
                )
            elif trigger_type == "life_share":
                self.presence_state.mark_life_shared(scope, content)
            self.presence_state.record_proactive_sent(
                scope,
                proactive_uid=proactive_uid,
                trigger_type=trigger_type,
                opening_text=content,
                emotion_delta=plan.get("emotion_delta") or {},
                safety_note=str(plan.get("safety_note") or ""),
            )
            if plan.get("open_loop_uid"):
                self.presence_state.mark_open_loop_prompted(
                    scope,
                    str(plan["open_loop_uid"]),
                    proactive_uid=proactive_uid,
                )
            sent += 1
        return {
            "expired": expired,
            "sent": sent,
            "skipped_sleep": skipped_sleep,
            "skipped_interval": skipped_interval,
            "skipped_disabled": skipped_disabled,
            "skipped_idle": skipped_idle,
            "skipped_daily_limit": skipped_daily_limit,
            "skipped_backoff": skipped_backoff,
            "skipped_unanswered": skipped_unanswered,
        }

    def _idle_enough(self, created_at: str) -> bool:
        timestamp = parse_iso8601(created_at)
        if timestamp is None:
            return False
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        idle_minutes = (
            self.settings.day_stream_min_interval_minutes
            if self.settings.companion_day_engine_enabled
            else self.settings.proactive_min_idle_minutes
        )
        return timestamp + timedelta(minutes=max(idle_minutes, 0)) <= datetime.now(timezone.utc)

    def _evaluate_send_gate(
        self,
        scope: ConversationScope,
        *,
        latest_user: Any | None,
        recent_proactive: list[Any],
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        policy = proactive_cadence_policy(str(preferences.get("cadence") or PROACTIVE_DEFAULT_CADENCE))
        if not bool(preferences.get("enabled", True)):
            return {"allowed": False, "reason": "disabled", "policy": policy, "preferences": preferences}
        if latest_user is None:
            return {"allowed": False, "reason": "idle", "policy": policy, "preferences": preferences}
        now = datetime.now(timezone.utc)
        latest_user_at = parse_iso8601(latest_user.created_at)
        if latest_user_at is None:
            return {"allowed": False, "reason": "idle", "policy": policy, "preferences": preferences}
        if latest_user_at.tzinfo is None:
            latest_user_at = latest_user_at.replace(tzinfo=timezone.utc)
        idle_eligible_at = latest_user_at + timedelta(minutes=int(policy["min_idle_minutes"]))
        if idle_eligible_at > now:
            return {
                "allowed": False,
                "reason": "idle",
                "next_eligible_at": idle_eligible_at.isoformat(),
                "policy": policy,
                "preferences": preferences,
            }
        if self.presence_state.proactive_paused_for_sleep(scope):
            return {"allowed": False, "reason": "sleep", "policy": policy, "preferences": preferences}
        backoff_until = self._backoff_until(scope.conversation_id) or self._recent_too_frequent_feedback_until(
            scope.conversation_id,
            recent_proactive,
        )
        if backoff_until is not None and backoff_until > now:
            return {
                "allowed": False,
                "reason": "backoff",
                "next_eligible_at": backoff_until.isoformat(),
                "policy": policy,
                "preferences": preferences,
            }
        if self._daily_sent_count(scope, recent_proactive) >= int(policy["daily_max"]):
            return {"allowed": False, "reason": "daily_limit", "policy": policy, "preferences": preferences}

        latest = self._latest_conversation_proactive(scope.conversation_id, recent_proactive)
        if latest is None:
            return {"allowed": True, "reason": "eligible", "policy": policy, "preferences": preferences}
        sent_at = parse_iso8601(latest.sent_at)
        if sent_at is None:
            return {"allowed": True, "reason": "eligible", "policy": policy, "preferences": preferences}
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        if latest.status == "sent":
            followup_at = sent_at + timedelta(minutes=int(policy["unanswered_followup_minutes"]))
            if followup_at > now:
                return {
                    "allowed": False,
                    "reason": "unanswered_wait",
                    "next_eligible_at": followup_at.isoformat(),
                    "policy": policy,
                    "preferences": preferences,
                }
            if not self._latest_supports_unanswered_followup(latest):
                return {
                    "allowed": False,
                    "reason": "unanswered_followup_used",
                    "policy": policy,
                    "preferences": preferences,
                }
            return {
                "allowed": True,
                "reason": "eligible_unanswered_followup",
                "policy": policy,
                "preferences": preferences,
            }

        spacing_at = sent_at + timedelta(minutes=int(policy["min_interval_minutes"]))
        if spacing_at > now:
            return {
                "allowed": False,
                "reason": "interval",
                "next_eligible_at": spacing_at.isoformat(),
                "policy": policy,
                "preferences": preferences,
            }
        return {"allowed": True, "reason": "eligible", "policy": policy, "preferences": preferences}

    def build_proactive_context_pack(self, scope: ConversationScope, *, latest_user: Any | None = None) -> dict[str, Any]:
        local_now = self._local_now()
        local_date = local_now.strftime("%Y-%m-%d")
        route = self.product_store.get_companion_day_route(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            local_date=local_date,
        )
        events = self.product_store.list_companion_day_events(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            route_uid=str(route["route_uid"]) if route else None,
            limit=8,
        )
        diary = self.product_store.list_shared_diary_entries(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            limit=8,
        )
        recent_proactive = [
            {
                "proactive_uid": item.proactive_uid,
                "trigger_type": item.trigger_type,
                "status": item.status,
                "accepted": item.accepted,
                "cold_response": item.cold_response,
                "sent_at": item.sent_at,
                "opening_text": truncate_text(item.opening_text, 180),
                "feedback": item.metadata.get("dashboard_feedback") if isinstance(item.metadata, dict) else None,
            }
            for item in self.product_store.list_proactive_messages(limit=30)
            if item.user_id == scope.user_id and item.conversation_id == scope.conversation_id
        ][:12]
        latest_summary = self.memory_store.get_latest_summary(scope.conversation_id)
        recent_messages = [
            {
                "id": message.id,
                "sender_type": message.sender_type,
                "content": truncate_text(message.content, 360),
                "created_at": message.created_at,
            }
            for message in self.memory_store.list_recent_messages(scope.conversation_id, limit=24)
        ]
        return {
            "local_time": local_now.isoformat(),
            "latest_user_message": None
            if latest_user is None
            else {
                "id": latest_user.id,
                "content": truncate_text(latest_user.content, 360),
                "created_at": latest_user.created_at,
            },
            "recent_messages": recent_messages,
            "summary": None
            if latest_summary is None
            else {
                "content": truncate_text(latest_summary.content, 700),
                "message_end_id": latest_summary.message_end_id,
                "version": latest_summary.version,
            },
            "session_memories": [
                {
                    "memory_type": memory.memory_type,
                    "content": truncate_text(memory.content, 240),
                    "priority": memory.priority,
                    "updated_at": memory.updated_at,
                }
                for memory in self.memory_store.list_recent_active_session_memories_for_conversation(
                    scope.conversation_id,
                    limit=12,
                )
            ],
            "long_term_memories": [
                {
                    "memory_uid": memory.memory_uid,
                    "memory_type": memory.memory_type,
                    "category": memory.category,
                    "content": truncate_text(memory.content, 260),
                    "importance": memory.importance,
                    "updated_at": memory.updated_at,
                }
                for memory in self.memory_store.list_active_long_term_memories(scope.user_id)[:14]
            ],
            "structured_facts": [
                {
                    "namespace": fact.namespace,
                    "key": fact.key,
                    "value": truncate_text(fact.value, 180),
                    "confidence": fact.confidence,
                }
                for fact in self.memory_store.list_structured_facts(scope.user_id, limit=24)
            ],
            "relationship_states": [
                {
                    "dimension": state.dimension,
                    "value": truncate_text(state.value, 220),
                    "weight": state.weight,
                    "confidence": state.confidence,
                }
                for state in self.memory_store.list_relationship_states(scope.user_id)[:12]
            ],
            "presence_state": self.presence_state.get_state(scope),
            "companion_day": {
                "route": route or {},
                "events": [
                    {
                        "event_uid": event.get("event_uid"),
                        "event_type": event.get("event_type"),
                        "status": event.get("status"),
                        "content": truncate_text(str(event.get("content") or ""), 220),
                        "sent_at": event.get("sent_at"),
                        "responded_at": event.get("responded_at"),
                        "follow_up_sent_at": event.get("follow_up_sent_at"),
                    }
                    for event in events
                ],
                "diary": [
                    {
                        "entry_type": item.get("entry_type"),
                        "role_scope": item.get("role_scope"),
                        "content": truncate_text(str(item.get("content") or ""), 220),
                        "created_at": item.get("created_at"),
                    }
                    for item in diary
                ],
                "unanswered_event": self.product_store.get_latest_unresponded_companion_day_event(
                    user_id=scope.user_id,
                    conversation_id=scope.conversation_id,
                )
                or {},
            },
            "recent_proactive": recent_proactive,
        }

    def _context_pack_counts(self, context_pack: dict[str, Any]) -> dict[str, int]:
        return {
            "recent_messages": len(context_pack.get("recent_messages") or []),
            "session_memories": len(context_pack.get("session_memories") or []),
            "long_term_memories": len(context_pack.get("long_term_memories") or []),
            "structured_facts": len(context_pack.get("structured_facts") or []),
            "relationship_states": len(context_pack.get("relationship_states") or []),
            "companion_day_events": len((context_pack.get("companion_day") or {}).get("events") or []),
            "diary": len((context_pack.get("companion_day") or {}).get("diary") or []),
            "recent_proactive": len(context_pack.get("recent_proactive") or []),
        }

    def _list_expiring_proactive_messages(self, *, idle_hours: int) -> list[Any]:
        expiring: list[Any] = []
        for item in self.product_store.list_proactive_messages(limit=300):
            if item.status != "sent":
                continue
            sent_at = parse_iso8601(item.sent_at)
            if sent_at is None:
                continue
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            if sent_at + timedelta(hours=idle_hours) <= datetime.now(timezone.utc):
                expiring.append(item)
        return expiring

    def _latest_conversation_proactive(self, conversation_id: str, proactive_messages: list[Any]) -> Any | None:
        return next((item for item in proactive_messages if item.conversation_id == conversation_id), None)

    def _latest_supports_unanswered_followup(self, item: Any) -> bool:
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        event_uid = metadata.get("companion_day_event_uid")
        if not event_uid:
            return False
        event = self.product_store.get_companion_day_event(str(event_uid))
        if event is None:
            return False
        if event.get("event_type") == "unanswered_followup":
            return False
        if event.get("follow_up_sent_at"):
            return False
        return True

    def _daily_sent_count(self, scope: ConversationScope, proactive_messages: list[Any]) -> int:
        start = self._local_day_start_utc()
        count = 0
        for item in proactive_messages:
            if item.user_id != scope.user_id or item.conversation_id != scope.conversation_id:
                continue
            sent_at = parse_iso8601(item.sent_at)
            if sent_at is None:
                continue
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            if sent_at >= start:
                count += 1
        return count

    def _local_day_start_utc(self) -> datetime:
        local_now = self._local_now()
        return local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    def _local_now(self) -> datetime:
        try:
            return datetime.now(ZoneInfo(self.settings.bot_timezone))
        except Exception:  # noqa: BLE001
            return datetime.now().astimezone()

    def _recent_too_frequent_feedback_until(self, conversation_id: str, proactive_messages: list[Any]) -> datetime | None:
        for item in proactive_messages:
            if item.conversation_id != conversation_id:
                continue
            metadata = item.metadata if isinstance(item.metadata, dict) else {}
            feedback = metadata.get("dashboard_feedback")
            if not isinstance(feedback, dict) or feedback.get("feedback") != "too_frequent":
                continue
            feedback_at = parse_iso8601(str(feedback.get("at") or item.updated_at or item.sent_at))
            if feedback_at is None:
                continue
            if feedback_at.tzinfo is None:
                feedback_at = feedback_at.replace(tzinfo=timezone.utc)
            until = feedback_at + timedelta(hours=6)
            if until > datetime.now(timezone.utc):
                return until
        return None

    async def _send_planned_message(self, channel: Any, content: str, plan: dict[str, Any]) -> list[Any]:
        if plan.get("source") != "companion_day_engine" or not self.settings.day_status_cards_enabled:
            return await send_human_message_parts(
                channel,
                content,
                settings=self.settings,
                reference=None,
                mention_author=False,
            )
        card = plan.get("status_card")
        if not isinstance(card, dict):
            return await send_human_message_parts(
                channel,
                content,
                settings=self.settings,
                reference=None,
                mention_author=False,
            )
        try:
            embed = discord.Embed(
                title=str(card.get("title") or "沈知微此刻"),
                description=str(card.get("description") or ""),
                color=0xC05A7B,
            )
            for field in card.get("fields", []):
                if not isinstance(field, dict):
                    continue
                embed.add_field(
                    name=str(field.get("name") or "状态"),
                    value=str(field.get("value") or "-"),
                    inline=True,
                )
            if card.get("footer"):
                embed.set_footer(text=str(card["footer"]))
            async with channel.typing():
                sent = await channel.send(content, embed=embed)
            return [sent]
        except Exception:  # noqa: BLE001
            return await send_human_message_parts(
                channel,
                content,
                settings=self.settings,
                reference=None,
                mention_author=False,
            )

    def _spacing_allows(
        self,
        conversation_id: str,
        proactive_messages: list[Any],
        *,
        policy: dict[str, int] | None = None,
    ) -> bool:
        latest = next((item for item in proactive_messages if item.conversation_id == conversation_id), None)
        if latest is None:
            return True
        sent_at = parse_iso8601(latest.sent_at)
        if sent_at is None:
            return True
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        min_interval = int((policy or {}).get("min_interval_minutes") or self.settings.proactive_min_interval_minutes)
        return sent_at + timedelta(minutes=min_interval) <= datetime.now(timezone.utc)

    def _recent_same_trigger(self, conversation_id: str, trigger_type: str, proactive_messages: list[Any]) -> bool:
        threshold = datetime.now(timezone.utc) - timedelta(hours=self.settings.proactive_trigger_dedupe_hours)
        for item in proactive_messages:
            if item.conversation_id != conversation_id or item.trigger_type != trigger_type:
                continue
            sent_at = parse_iso8601(item.sent_at)
            if sent_at is None:
                continue
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            if sent_at >= threshold:
                return True
        return False

    async def _plan_trigger(
        self,
        scope: ConversationScope,
        proactive_messages: list[Any],
        *,
        context_pack: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.presence_state.get_state(scope)
        memories = self.product_store.list_top_memory_hits(scope.user_id, limit=8)
        session_memories = self.memory_store.list_recent_active_session_memories_for_conversation(
            scope.conversation_id,
            limit=8,
        )
        candidates: list[dict[str, Any]] = []
        for loop in self.presence_state.list_open_loops(scope, status="open", limit=6):
            topic = self._sanitize_topic(str(loop.get("content") or ""))
            if not self._is_actionable_topic(topic):
                continue
            prompt_count = int(loop.get("prompt_count") or 0)
            candidates.append(
                {
                    "trigger_type": "open_loop_follow_up",
                    "score": max(0.58, 0.94 - prompt_count * 0.08),
                    "reason": "presence_open_loop",
                    "selected_detail": topic,
                    "open_loop_uid": loop.get("loop_uid"),
                    "memory_uids": [],
                }
            )
        for memory in session_memories:
            if memory.memory_type != "open_loop":
                continue
            topic = self._sanitize_topic(memory.content)
            if self._is_actionable_topic(topic):
                candidates.append(
                    {
                        "trigger_type": "open_loop_follow_up",
                        "score": 0.82,
                        "reason": "session_open_loop",
                        "selected_detail": topic,
                        "memory_uids": [f"session:{memory.id}"],
                    }
                )
        for memory in memories:
            memory_type = str(memory.get("memory_type") or "")
            topic = self._sanitize_topic(str(memory.get("content") or ""))
            memory_uid = str(memory.get("memory_uid") or "")
            if memory_type in ACTIONABLE_MEMORY_TYPES and self._is_actionable_topic(topic):
                candidates.append(
                    {
                        "trigger_type": "study_or_routine_nudge" if memory_type in {"study_context", "routine_pattern"} else "open_loop_follow_up",
                        "score": 0.74,
                        "reason": f"actionable_memory:{memory_type}",
                        "selected_detail": topic,
                        "memory_uids": [memory_uid] if memory_uid else [],
                    }
                )
            elif memory_type in CARE_MEMORY_TYPES:
                candidates.append(
                    {
                        "trigger_type": "care_afterglow",
                        "score": 0.68,
                        "reason": f"care_memory:{memory_type}",
                        "selected_detail": topic if self._is_safe_care_detail(topic) else "",
                        "memory_uids": [memory_uid] if memory_uid else [],
                    }
                )
            elif memory_type in RELATIONSHIP_TONE_TYPES:
                candidates.append(
                    {
                        "trigger_type": "miss_you",
                        "score": 0.48,
                        "reason": f"relationship_tone_only:{memory_type}",
                        "selected_detail": "",
                        "memory_uids": [memory_uid] if memory_uid else [],
                    }
                )
        last_life_share = parse_iso8601(str(state.get("last_life_share_at") or ""))
        if last_life_share is None:
            candidates.append(
                {
                    "trigger_type": "life_share",
                    "score": 0.72,
                    "reason": "no_life_share_yet",
                    "selected_detail": self._sanitize_topic(str(state.get("daily_detail") or "")),
                    "memory_uids": [],
                }
            )
        elif last_life_share.tzinfo is None:
            last_life_share = last_life_share.replace(tzinfo=timezone.utc)
        if last_life_share is not None and last_life_share + timedelta(hours=2) <= datetime.now(timezone.utc):
            candidates.append(
                {
                    "trigger_type": "life_share",
                    "score": 0.66,
                    "reason": "life_share_spacing_elapsed",
                    "selected_detail": self._sanitize_topic(str(state.get("daily_detail") or "")),
                    "memory_uids": [],
                }
            )
        candidates.append(
            {
                "trigger_type": "miss_you",
                "score": 0.42,
                "reason": "default_warm_presence",
                "selected_detail": "",
                "memory_uids": [],
            }
        )
        candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
        trigger_candidates = [
            {
                "trigger_type": item.get("trigger_type"),
                "score": item.get("score"),
                "reason": item.get("reason"),
                "selected_detail": truncate_text(str(item.get("selected_detail") or ""), 90),
                "open_loop_uid": item.get("open_loop_uid"),
                "memory_uids": item.get("memory_uids", []),
            }
            for item in candidates[:6]
        ]
        recent_messages = [
            {
                "sender_type": message.sender_type,
                "content": truncate_text(message.content, 260),
                "created_at": message.created_at,
            }
            for message in self.memory_store.list_recent_messages(scope.conversation_id, limit=10)
        ]
        recent_proactive = [
            {
                "trigger_type": item.trigger_type,
                "status": item.status,
                "accepted": item.accepted,
                "cold_response": item.cold_response,
                "sent_at": item.sent_at,
                "opening_text": truncate_text(item.opening_text, 160),
            }
            for item in proactive_messages
            if item.conversation_id == scope.conversation_id
        ][:8]
        payload = await self.llm_client.json_completion(
            system_prompt=PROACTIVE_PLANNER_SYSTEM_PROMPT,
            user_prompt=build_proactive_planner_user_prompt(
                scope={
                    "platform": scope.platform,
                    "conversation_id": scope.conversation_id,
                    "user_id": scope.user_id,
                    "channel_id": scope.channel_id,
                },
                presence_state=state,
                trigger_candidates=trigger_candidates,
                recent_messages=recent_messages,
                recent_proactive=recent_proactive,
                context_pack=context_pack or self.build_proactive_context_pack(scope),
                local_time=datetime.now(timezone.utc).astimezone().isoformat(),
            ),
            model=self.settings.resolve_reply_model(),
            temperature=0.65,
            max_tokens=850,
        )
        plan = self._validate_model_plan(payload, state=state, trigger_candidates=trigger_candidates)
        plan["presence_snapshot"] = {
            "user_sleep_state": state.get("user_sleep_state"),
            "user_sleep_state_confidence": state.get("user_sleep_state_confidence"),
            "current_scene_label": state.get("current_scene_label"),
            "daily_detail": state.get("daily_detail"),
            "last_life_share_at": state.get("last_life_share_at"),
            "assistant_emotion_state": state.get("assistant_emotion_state"),
        }
        plan["candidates"] = trigger_candidates
        return plan

    def _validate_model_plan(
        self,
        payload: dict[str, Any],
        *,
        state: dict[str, Any],
        trigger_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("proactive model returned non-object payload")
        trigger_type = str(payload.get("trigger_type") or "").strip()
        allowed = {
            "life_share",
            "open_loop_follow_up",
            "study_or_routine_nudge",
            "care_afterglow",
            "miss_you",
            "day_life_share",
            "day_reality_anchor",
            "day_unanswered_followup",
        }
        if trigger_type not in allowed:
            trigger_type = str((trigger_candidates[0] if trigger_candidates else {}).get("trigger_type") or "miss_you")
        should_send = bool(payload.get("should_send", True))
        try:
            confidence = max(0.0, min(1.0, float(payload.get("confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0
        sleep_state = str(state.get("user_sleep_state") or "unknown")
        sleep_confidence = float(state.get("user_sleep_state_confidence") or 0)
        if sleep_state == "asleep" or (sleep_state == "probably_asleep" and sleep_confidence >= 0.78):
            should_send = False
        content = str(payload.get("draft_text") or "").strip()
        if should_send and confidence < 0.45:
            should_send = False
        if should_send and not content:
            raise RuntimeError("proactive model returned empty draft_text")
        if any(token in content for token in ("模型", "系统提示", "工具调用", "JSON", "prompt")):
            raise RuntimeError("proactive model leaked backend vocabulary")
        return {
            "trigger_type": trigger_type,
            "should_send": should_send,
            "reason": truncate_text(compact_text(str(payload.get("reason") or "")), 180),
            "confidence": confidence,
            "draft_text": content,
            "content": content,
            "response_expected": bool(payload.get("response_expected", True)),
            "expectation_level": str(payload.get("expectation_level") or "clear"),
            "selected_detail": truncate_text(compact_text(str(payload.get("selected_detail") or "")), 120),
            "next_eligible_at": str(payload.get("next_eligible_at") or ""),
            "emotion_delta": payload.get("emotion_delta") if isinstance(payload.get("emotion_delta"), dict) else {},
            "safety_note": truncate_text(compact_text(str(payload.get("safety_note") or "")), 180),
            "source": "llm_proactive_planner",
            "model": self.settings.resolve_reply_model(),
        }

    def _sanitize_topic(self, text: str) -> str:
        normalized = compact_text(text)
        normalized = normalized.replace("。。", "。")
        normalized = normalized.replace("..", ".")
        normalized = normalized.strip(" 　，,。")
        if any(token in normalized for token in ABSTRACT_MEMORY_BLOCKLIST):
            return ""
        normalized = normalized.removeprefix("用户表示").removeprefix("用户说").removeprefix("用户")
        normalized = normalized.removeprefix("沈知微表示").removeprefix("沈知微说").removeprefix("沈知微")
        return truncate_text(compact_text(normalized), 58)

    def _is_actionable_topic(self, text: str) -> bool:
        normalized = compact_text(text)
        if not normalized:
            return False
        if any(token in normalized for token in ABSTRACT_MEMORY_BLOCKLIST):
            return False
        if len(normalized) > 120 and not any(token in normalized for token in ("回来", "告诉", "提醒", "检查", "报")):
            return False
        return any(token in normalized for token in ACTIONABLE_TOPIC_TOKENS)

    def _is_safe_care_detail(self, text: str) -> bool:
        normalized = compact_text(text)
        if not normalized:
            return False
        if any(token in normalized for token in ABSTRACT_MEMORY_BLOCKLIST):
            return False
        return len(normalized) <= 80

    def _polish_message(self, text: str) -> str:
        polished = repair_immersive_voice(compact_text(text)).replace("。 。", "。").replace("。。", "。")
        polished = polished.replace("  ", " ")
        polished = polished.replace("。 ", "。\n", 1) if "\n" not in polished else polished
        return polished.strip()

    def _in_backoff(self, conversation_id: str) -> bool:
        until = self._backoff_until(conversation_id)
        return until is not None and until > datetime.now(timezone.utc)

    def _backoff_until(self, conversation_id: str) -> datetime | None:
        value = self.product_store.get_app_setting(proactive_backoff_key(conversation_id), {})
        if not isinstance(value, dict):
            return None
        until = parse_iso8601(str(value.get("until") or ""))
        if until is None:
            return None
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return until

    def _set_backoff(self, conversation_id: str, error: str) -> None:
        until = datetime.now(timezone.utc) + timedelta(minutes=self.settings.proactive_failure_backoff_minutes)
        self.product_store.set_app_setting(
            proactive_backoff_key(conversation_id),
            {"until": until.isoformat(), "error": truncate_text(error, 160), "updated_at": iso_utc_now()},
        )

    def _record_model_failure(self, conversation_id: str, stage: str, exc: Exception) -> None:
        message = f"{stage}: {type(exc).__name__}: {exc}"
        self._set_backoff(conversation_id, message)
        self.product_store.set_app_setting(
            f"proactive_model_failure:{conversation_id}",
            {
                "stage": stage,
                "error": truncate_text(str(exc), 240),
                "error_type": type(exc).__name__,
                "model": self.settings.resolve_reply_model(),
                "at": iso_utc_now(),
            },
        )

    def _has_proactive_opt_in(self, user_id: str) -> bool:
        fact = self.memory_store.get_structured_fact(
            user_id,
            namespace="support",
            key="proactive_opt_in",
        )
        if fact is None:
            return False
        return fact.value.strip().lower() in {"on", "true", "yes", "enabled"}
