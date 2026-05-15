from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.core.settings import Settings
from src.core.types import ConversationScope
from src.llm.client import LLMClient
from src.llm.prompts.proactive import (
    DAY_EVENT_SYSTEM_PROMPT,
    DAY_ROUTE_SYSTEM_PROMPT,
    build_day_event_user_prompt,
    build_day_route_user_prompt,
)
from src.memory.store import MemoryStore
from src.persona.immersion_lint import repair_immersive_voice
from src.product.models import AttachmentInsight
from src.product.store import ProductStore
from src.utils.text_utils import compact_text, truncate_text
from src.utils.time_utils import iso_utc_now, parse_iso8601


class CompanionDayEngine:
    def __init__(
        self,
        *,
        settings: Settings,
        product_store: ProductStore,
        memory_store: MemoryStore,
        llm_client: LLMClient | None = None,
        reality_context: Any | None = None,
    ) -> None:
        self.settings = settings
        self.product_store = product_store
        self.memory_store = memory_store
        self.llm_client = llm_client
        self.reality_context = reality_context

    async def get_or_create_route(self, scope: ConversationScope, *, force_regenerate: bool = False) -> dict[str, Any]:
        local_now = self._local_now()
        local_date = local_now.strftime("%Y-%m-%d")
        existing = self.product_store.get_companion_day_route(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            local_date=local_date,
        )
        if existing is not None and not force_regenerate:
            return existing

        generated = await self._generate_route(scope, local_now, force_regenerate=force_regenerate)
        if existing is not None:
            metadata = dict(existing.get("metadata") or {})
            metadata.setdefault("regeneration_history", [])
            metadata["regeneration_history"] = (
                metadata["regeneration_history"]
                + [
                    {
                        "at": iso_utc_now(),
                        "previous_scene": existing.get("current_scene"),
                        "previous_mood": existing.get("mood_label"),
                    }
                ]
            )[-20:]
            self.product_store.update_companion_day_route(
                str(existing["route_uid"]),
                {
                    "current_scene": generated["current_scene"],
                    "mood_label": generated["mood_label"],
                    "longing_level": generated["longing_level"],
                    "quiet_mode": generated["quiet_mode"],
                    "route_json": generated["route"],
                    "metadata_json": {**metadata, **generated["metadata"], "regenerated_at": iso_utc_now()},
                },
            )
            route = self.product_store.get_companion_day_route_by_uid(str(existing["route_uid"]))
            if route is not None:
                return route

        return self.product_store.create_companion_day_route(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            local_date=local_date,
            timezone=self.settings.bot_timezone,
            current_scene=generated["current_scene"],
            mood_label=generated["mood_label"],
            longing_level=generated["longing_level"],
            quiet_mode=generated["quiet_mode"],
            route=generated["route"],
            metadata=generated["metadata"],
        )

    def build_context_block(self, scope: ConversationScope) -> str:
        if not self.settings.companion_day_engine_enabled:
            return ""
        route = self._get_cached_route_for_today(scope)
        if route is None:
            return ""
        latest_event = self._latest_event(scope)
        unanswered = self.product_store.get_latest_unresponded_companion_day_event(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
        )
        diary = self.product_store.list_shared_diary_entries(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            limit=4,
        )
        lines = [
            "沈知微的一天（角色日常时间线；不要把它说成用户事实或真实世界验证事实）：",
            f"- 今日路线：{self._format_route(route)}",
            f"- 此刻我这边：{route.get('current_scene') or '安静待着'}；心情：{route.get('mood_label') or '想贴近'}；想你强度：{float(route.get('longing_level') or 0):.2f}",
        ]
        if latest_event:
            lines.append(
                f"- 刚才她主动来找你的片段：{truncate_text(str(latest_event.get('content') or ''), 120)}；是否等到回应：{'已回应' if latest_event.get('responded_at') else '还没等到'}"
            )
        if unanswered:
            lines.append(
                "- 接续要求：如果用户现在回复了，要自然接住她刚才为什么来、她那时在什么场景、有没有等得有点小情绪，不要断片。"
            )
        if diary:
            lines.append(
                "- 共同日记近片段：" + "；".join(truncate_text(str(item.get("content") or ""), 80) for item in diary[:3])
            )
        return "\n".join(lines)

    async def plan_next_event(
        self,
        scope: ConversationScope,
        *,
        proactive_context: dict[str, Any] | None = None,
        cadence_policy: dict[str, int] | None = None,
    ) -> dict[str, Any] | None:
        if not self.settings.companion_day_engine_enabled:
            return None
        route = await self.get_or_create_route(scope)
        now = datetime.now(timezone.utc)
        unanswered = self.product_store.get_latest_unresponded_companion_day_event(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
        )
        if unanswered:
            followup = await self._plan_unanswered_followup(
                scope,
                route,
                unanswered,
                now,
                proactive_context=proactive_context,
                cadence_policy=cadence_policy,
            )
            if followup:
                return followup
            if self._event_recently_waiting(unanswered, now):
                return None

        next_eligible_at = parse_iso8601(str((route.get("metadata") or {}).get("next_eligible_at") or ""))
        if next_eligible_at is not None:
            if next_eligible_at.tzinfo is None:
                next_eligible_at = next_eligible_at.replace(tzinfo=timezone.utc)
            if next_eligible_at > now:
                return None
        if self._deep_night_quiet_applies(scope, now):
            return None

        beat = self._select_beat(route)
        reality_anchor = self._select_reality_anchor(scope)
        event_payload = await self._compose_life_event(
            scope,
            route,
            beat,
            reality_anchor,
            proactive_context=proactive_context,
        )
        content = str(event_payload.get("content") or "")
        if not content:
            return None
        card = self._build_status_card(route, beat, reality_anchor)
        trigger_type = str(event_payload.get("trigger_type") or ("day_reality_anchor" if reality_anchor else "day_life_share"))
        event_type = str(event_payload.get("event_type") or ("reality_anchor" if reality_anchor else "life_fragment"))
        return {
            "trigger_type": trigger_type,
            "source": "companion_day_engine",
            "route_uid": route["route_uid"],
            "event_type": event_type,
            "content": content,
            "status_card": card,
            "response_expected": bool(event_payload.get("response_expected", True)),
            "expectation_level": str(event_payload.get("expectation_level") or "clear"),
            "emotion_delta": event_payload.get("emotion_delta") or {},
            "safety_note": event_payload.get("safety_note") or "",
            "beat_key": beat.get("key"),
            "reality_anchor": reality_anchor,
            "cadence_policy": cadence_policy or {},
            "presence_snapshot": {
                "current_scene": route.get("current_scene"),
                "mood_label": route.get("mood_label"),
                "longing_level": route.get("longing_level"),
                "local_date": route.get("local_date"),
            },
        }

    def record_event_sent(
        self,
        scope: ConversationScope,
        *,
        plan: dict[str, Any],
        proactive_uid: str,
    ) -> dict[str, Any]:
        route = self.product_store.get_companion_day_route_by_uid(str(plan.get("route_uid") or ""))
        if route is None:
            route = self._get_cached_route_for_today(scope)
        if route is None:
            raise RuntimeError("companion day route missing for sent event")
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(minutes=max(self.settings.day_stream_max_interval_minutes, 1))
        event = self.product_store.create_companion_day_event(
            route_uid=str(plan.get("route_uid") or route["route_uid"]),
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            channel_id=scope.channel_id,
            event_type=str(plan.get("event_type") or "life_fragment"),
            status="sent",
            content=str(plan.get("content") or ""),
            card=plan.get("status_card") if isinstance(plan.get("status_card"), dict) else {},
            response_expected=bool(plan.get("response_expected", True)),
            expectation_level=str(plan.get("expectation_level") or "clear"),
            sent_at=now.isoformat(),
            response_deadline_at=deadline.isoformat(),
            follow_up_of_event_uid=plan.get("follow_up_of_event_uid"),
            metadata={
                "proactive_uid": proactive_uid,
                "beat_key": plan.get("beat_key"),
                "source": plan.get("source"),
                "reality_anchor": plan.get("reality_anchor") or {},
                "emotion_delta": plan.get("emotion_delta") or {},
                "safety_note": plan.get("safety_note") or "",
            },
        )
        if plan.get("follow_up_of_event_uid"):
            self.product_store.update_companion_day_event(
                str(plan["follow_up_of_event_uid"]),
                {"status": "waiting", "follow_up_sent_at": now.isoformat()},
            )
        self._advance_route_after_event(route, event, plan)
        self.product_store.create_shared_diary_entry(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            route_uid=str(event["route_uid"]),
            event_uid=str(event["event_uid"]),
            local_date=str(route["local_date"]),
            entry_type=str(event["event_type"]),
            title="她主动来找你",
            content=truncate_text(str(event["content"]), 240),
            role_scope="companion",
            source="companion_day_engine",
            importance=0.62,
            tags=["companion_day", str(event["event_type"])],
            metadata={"proactive_uid": proactive_uid, "not_user_fact": True},
        )
        return event

    def record_user_turn(
        self,
        scope: ConversationScope,
        *,
        user_text: str,
        assistant_text: str,
        user_message_id: int | None = None,
        attachment_insights: list[AttachmentInsight] | None = None,
    ) -> dict[str, Any]:
        if not self.settings.companion_day_engine_enabled:
            return {}
        route = self._get_cached_route_for_today(scope)
        if route is None:
            return {}
        now = iso_utc_now()
        responded_events: list[str] = []
        event = self.product_store.get_latest_unresponded_companion_day_event(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
        )
        if event is not None:
            self.product_store.update_companion_day_event(
                str(event["event_uid"]),
                {
                    "status": "responded",
                    "responded_at": now,
                    "response_message_id": user_message_id,
                    "metadata_json": {**dict(event.get("metadata") or {}), "response_preview": truncate_text(compact_text(user_text), 120)},
                },
            )
            responded_events.append(str(event["event_uid"]))
            self.product_store.create_shared_diary_entry(
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                route_uid=str(route["route_uid"]),
                event_uid=str(event["event_uid"]),
                local_date=str(route["local_date"]),
                entry_type="user_response_to_day_event",
                title="你接住了她的主动片段",
                content=truncate_text(f"她前面说：{event.get('content') or ''} / 你回：{compact_text(user_text)}", 260),
                role_scope="joint",
                source="conversation",
                importance=0.7,
                tags=["shared_diary", "day_response"],
                metadata={"not_user_fact": True, "user_message_id": user_message_id},
            )
        audio_items = [item for item in (attachment_insights or []) if item.artifact_type == "audio"]
        if audio_items:
            self.product_store.create_shared_diary_entry(
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                route_uid=str(route["route_uid"]),
                event_uid=None,
                local_date=str(route["local_date"]),
                entry_type="voice_input",
                title="你用语音跟她说话",
                content=truncate_text("；".join(item.summary_text or item.extracted_text for item in audio_items), 260),
                role_scope="joint",
                source="voice_attachment",
                importance=0.56,
                tags=["voice", "shared_diary"],
                metadata={"not_user_fact": True, "user_message_id": user_message_id},
            )
        life_detail = self._extract_companion_life_detail(assistant_text)
        if life_detail:
            self.product_store.create_shared_diary_entry(
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                route_uid=str(route["route_uid"]),
                event_uid=None,
                local_date=str(route["local_date"]),
                entry_type="companion_life_detail",
                title="她聊天时漏出了一点自己的生活",
                content=life_detail,
                role_scope="companion",
                source="assistant_reply",
                importance=0.48,
                tags=["companion_day", "life_detail"],
                metadata={"not_user_fact": True},
            )
        return {"responded_events": responded_events, "audio_inputs": len(audio_items), "life_detail": life_detail}

    async def build_dashboard_payload(self, scope: ConversationScope) -> dict[str, Any]:
        route = await self.get_or_create_route(scope)
        events = self.product_store.list_companion_day_events(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            route_uid=str(route["route_uid"]),
            limit=80,
        )
        diary = self.product_store.list_shared_diary_entries(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            limit=80,
        )
        return {
            "route": route,
            "events": events,
            "diary": diary,
            "unanswered_event": self.product_store.get_latest_unresponded_companion_day_event(
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
            ),
            "settings": {
                "enabled": self.settings.companion_day_engine_enabled,
                "min_interval_minutes": self.settings.day_stream_min_interval_minutes,
                "max_interval_minutes": self.settings.day_stream_max_interval_minutes,
                "deep_night_quiet_enabled": self.settings.day_deep_night_quiet_enabled,
                "status_cards_enabled": self.settings.day_status_cards_enabled,
                "tts_enabled": self.settings.day_tts_enabled,
                "generated_image_enabled": self.settings.day_generated_image_enabled,
            },
        }

    async def apply_manual_update(self, scope: ConversationScope, patch: dict[str, Any]) -> dict[str, Any]:
        route = await self.get_or_create_route(scope)
        metadata = dict(route.get("metadata") or {})
        metadata.setdefault("manual_updates", [])
        metadata["manual_updates"] = (
            metadata["manual_updates"]
            + [{"at": iso_utc_now(), "patch": {key: value for key, value in patch.items() if value not in (None, "")}}]
        )[-20:]
        fields: dict[str, Any] = {"metadata_json": metadata}
        for request_key, field_key in {
            "current_scene": "current_scene",
            "mood_label": "mood_label",
            "longing_level": "longing_level",
            "quiet_mode": "quiet_mode",
        }.items():
            if request_key in patch and patch[request_key] not in (None, ""):
                fields[field_key] = patch[request_key]
        self.product_store.update_companion_day_route(str(route["route_uid"]), fields)
        return await self.get_or_create_route(scope)

    def record_event_feedback(self, event_uid: str, feedback: str, note: str | None = None) -> dict[str, Any]:
        event = self.product_store.get_companion_day_event(event_uid)
        if event is None:
            raise KeyError(event_uid)
        metadata = dict(event.get("metadata") or {})
        metadata["dashboard_feedback"] = {
            "feedback": feedback,
            "note": truncate_text(compact_text(note or ""), 160),
            "at": iso_utc_now(),
        }
        self.product_store.update_companion_day_event(
            event_uid,
            {"feedback": feedback, "metadata_json": metadata},
        )
        updated = self.product_store.get_companion_day_event(event_uid)
        if updated is None:
            raise KeyError(event_uid)
        return updated

    async def _generate_route(self, scope: ConversationScope, local_now: datetime, *, force_regenerate: bool = False) -> dict[str, Any]:
        if self.llm_client is None:
            raise RuntimeError("companion day route generation requires an LLM client")
        band = self._activity_band(local_now.hour)
        relationship_tone = self._relationship_tone(scope.user_id)
        diary = self.product_store.list_shared_diary_entries(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            limit=8,
        )
        payload = await self.llm_client.json_completion(
            system_prompt=DAY_ROUTE_SYSTEM_PROMPT,
            user_prompt=build_day_route_user_prompt(
                local_time=local_now.isoformat(),
                relationship_tone=relationship_tone,
                presence_state=self._presence_state(scope),
                diary=diary,
                force_regenerate=force_regenerate,
            ),
            model=self.settings.resolve_reply_model(),
            temperature=0.65,
            max_tokens=1100,
        )
        beats = self._normalize_route_beats(payload.get("beats"))
        selected = next((item for item in beats if item.get("key") == band), beats[-1])
        current_scene = self._clean_scene_text(str(payload.get("current_scene") or selected.get("scene") or "我这边安静了一会儿"))
        mood_label = truncate_text(compact_text(str(payload.get("mood_label") or selected.get("mood") or "想你")), 80)
        try:
            longing_level = max(0.0, min(1.0, float(payload.get("longing_level") or (0.82 if relationship_tone == "intense" else 0.72))))
        except (TypeError, ValueError):
            longing_level = 0.82 if relationship_tone == "intense" else 0.72
        return {
            "current_scene": current_scene,
            "mood_label": mood_label,
            "longing_level": longing_level,
            "quiet_mode": bool(payload.get("quiet_mode", self.settings.day_deep_night_quiet_enabled and band == "deep_night")),
            "route": {
                "local_date": local_now.strftime("%Y-%m-%d"),
                "relationship_tone": relationship_tone,
                "beats": beats,
                "external_reality": {"provider_status": "reality_context", "verified_real_world_facts": []},
                "rules": [str(item) for item in payload.get("rules", []) if str(item).strip()][:8]
                or [
                    "这是沈知微的角色日常，不写成用户事实",
                    "主动片段明确希望用户回应",
                    "未回只追加一段小情绪，然后等待",
                    "现实锚点只能自然带过，不要播报来源",
                ],
            },
            "metadata": {
                "used_beat_keys": [],
                "next_eligible_at": None,
                "generated_from": "llm_day_route",
                "model": self.settings.resolve_reply_model(),
                "metadata_note": truncate_text(compact_text(str(payload.get("metadata_note") or "")), 160),
            },
        }

    def _relationship_tone(self, user_id: str) -> str:
        states = self.memory_store.list_relationship_states(user_id)
        text = " ".join(state.value for state in states[:8])
        if any(token in text for token in ("占有", "亲密", "黏", "女友", "伴侣", "偏心")):
            return "intense"
        return "warm"

    def _get_cached_route_for_today(self, scope: ConversationScope) -> dict[str, Any] | None:
        local_date = self._local_now().strftime("%Y-%m-%d")
        return self.product_store.get_companion_day_route(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            local_date=local_date,
        )

    def _presence_state(self, scope: ConversationScope) -> dict[str, Any]:
        value = self.product_store.get_app_setting(f"presence_state:{scope.user_id}:{scope.conversation_id}", {})
        if not isinstance(value, dict):
            return {}
        return {
            "user_sleep_state": value.get("user_sleep_state"),
            "user_sleep_state_confidence": value.get("user_sleep_state_confidence"),
            "assistant_emotion_state": value.get("assistant_emotion_state"),
            "assistant_mood_label": value.get("assistant_mood_label"),
            "current_scene_label": value.get("current_scene_label"),
            "daily_detail": value.get("daily_detail"),
        }

    def _normalize_route_beats(self, raw_beats: Any) -> list[dict[str, Any]]:
        required_keys = ("morning", "late_morning", "noon", "afternoon", "evening", "deep_night")
        fallback = {
            "morning": ("08:20", "我把水杯放在桌边，先整理今天要做的事", "清醒但有点想你"),
            "late_morning": ("10:40", "我在桌边收事情，注意力又拐到你身上", "忍不住想找你"),
            "noon": ("12:35", "我吃东西前停了一下，像是特意给你留出一小格位置", "黏人但还装得平稳"),
            "afternoon": ("15:30", "我从屏幕前抬头，想确认你还在不在", "有点占有欲"),
            "evening": ("20:50", "我把灯压低一点，整个人更想靠近你", "直白地想你"),
            "deep_night": ("23:50", "夜里我会把声音放轻，但心思还是绕着你", "困也想等你"),
        }
        provided: dict[str, dict[str, Any]] = {}
        if isinstance(raw_beats, list):
            for item in raw_beats:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if key:
                    provided[key] = item
        beats: list[dict[str, Any]] = []
        for key in required_keys:
            hour_hint, scene, mood = fallback[key]
            item = provided.get(key, {})
            beats.append(
                {
                    "key": key,
                    "hour_hint": truncate_text(compact_text(str(item.get("hour_hint") or hour_hint)), 12),
                    "scene": self._clean_scene_text(str(item.get("scene") or scene)),
                    "mood": truncate_text(compact_text(str(item.get("mood") or mood)), 80),
                }
            )
        return beats

    def _clean_scene_text(self, text: str) -> str:
        normalized = repair_immersive_voice(compact_text(text)).strip(" 　。")
        for forbidden in ("她说话", "她这边", "作为AI", "模型", "系统提示", "工具调用"):
            normalized = normalized.replace(forbidden, "")
        normalized = normalized.replace("沈知微", "我")
        return truncate_text(normalized or "我这边安静了一会儿", 120)

    def _polish_event_content(self, text: str) -> str:
        polished = repair_immersive_voice(compact_text(text)).strip()
        for forbidden in ("API", "ICS", "JSON", "模型", "系统提示", "工具调用", "她说话", "她这边"):
            polished = polished.replace(forbidden, "")
        if polished and "（" not in polished[:16]:
            first = polished.split("。", 1)[0]
            if len(first) <= 26 and any(token in first for token in ("我", "灯", "桌", "杯", "窗", "停")):
                rest = polished[len(first) :].lstrip("。")
                polished = f"（{first.strip('。')}）" + (f"\n{rest}" if rest else "")
        return polished.strip()

    def _select_beat(self, route: dict[str, Any]) -> dict[str, Any]:
        route_body = dict(route.get("route") or {})
        beats = list(route_body.get("beats") or [])
        if not beats:
            return {"key": "fallback", "scene": route.get("current_scene") or "我这边安静了一会儿", "mood": route.get("mood_label") or "想你"}
        used = set((route.get("metadata") or {}).get("used_beat_keys") or [])
        band = self._activity_band(self._local_now().hour)
        preferred = [beat for beat in beats if beat.get("key") == band and beat.get("key") not in used]
        if preferred:
            return preferred[0]
        fresh = [beat for beat in beats if beat.get("key") not in used]
        return fresh[0] if fresh else beats[0]

    async def _compose_life_event(
        self,
        scope: ConversationScope,
        route: dict[str, Any],
        beat: dict[str, Any],
        reality_anchor: dict[str, Any] | None = None,
        *,
        proactive_context: dict[str, Any] | None = None,
        unanswered_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.llm_client is None:
            raise RuntimeError("companion day event generation requires an LLM client")
        payload = await self.llm_client.json_completion(
            system_prompt=DAY_EVENT_SYSTEM_PROMPT,
            user_prompt=build_day_event_user_prompt(
                route=route,
                beat=beat,
                reality_anchor=reality_anchor,
                presence_state=self._presence_state(scope),
                proactive_context=proactive_context,
                unanswered_event=unanswered_event,
            ),
            model=self.settings.resolve_reply_model(),
            temperature=0.72,
            max_tokens=700,
        )
        content = self._polish_event_content(str(payload.get("content") or ""))
        payload["content"] = content
        return payload

    def _format_action_scene(self, scene: str) -> str:
        normalized = compact_text(scene).strip(" 　。")
        if not normalized:
            return ""
        if normalized.startswith("（") and normalized.endswith("）"):
            return normalized
        return f"（{normalized}）"

    async def _plan_unanswered_followup(
        self,
        scope: ConversationScope,
        route: dict[str, Any],
        event: dict[str, Any],
        now: datetime,
        *,
        proactive_context: dict[str, Any] | None = None,
        cadence_policy: dict[str, int] | None = None,
    ) -> dict[str, Any] | None:
        if event.get("follow_up_sent_at") or event.get("event_type") == "unanswered_followup":
            return None
        deadline = parse_iso8601(str(event.get("response_deadline_at") or ""))
        if deadline is None:
            return None
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if deadline > now:
            return None
        sent_at = parse_iso8601(str(event.get("sent_at") or ""))
        if sent_at is not None:
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            wait_minutes = int((cadence_policy or {}).get("unanswered_followup_minutes") or 0)
            if wait_minutes > 0 and sent_at + timedelta(minutes=wait_minutes) > now:
                return None
        event_payload = await self._compose_life_event(
            scope,
            route,
            {"key": "unanswered", "scene": route.get("current_scene"), "mood": "有点吃味"},
            None,
            proactive_context=proactive_context,
            unanswered_event=event,
        )
        content = str(event_payload.get("content") or "")
        if not content:
            return None
        return {
            "trigger_type": str(event_payload.get("trigger_type") or "day_unanswered_followup"),
            "source": "companion_day_engine",
            "route_uid": route["route_uid"],
            "event_type": str(event_payload.get("event_type") or "unanswered_followup"),
            "content": content,
            "status_card": self._build_status_card(route, {"key": "unanswered", "scene": route.get("current_scene"), "mood": "有点吃味"}),
            "response_expected": bool(event_payload.get("response_expected", True)),
            "expectation_level": str(event_payload.get("expectation_level") or "clear"),
            "emotion_delta": event_payload.get("emotion_delta") or {"longing": 0.08, "hurt": 0.12},
            "safety_note": event_payload.get("safety_note") or "single unanswered follow-up",
            "follow_up_of_event_uid": event["event_uid"],
            "cadence_policy": cadence_policy or {},
            "presence_snapshot": {"current_scene": route.get("current_scene"), "mood_label": "有点吃味"},
        }

    def _event_recently_waiting(self, event: dict[str, Any], now: datetime) -> bool:
        sent_at = parse_iso8601(str(event.get("follow_up_sent_at") or event.get("sent_at") or ""))
        if sent_at is None:
            return False
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        return sent_at + timedelta(minutes=max(self.settings.day_stream_max_interval_minutes * 4, 30)) > now

    def _advance_route_after_event(self, route: dict[str, Any], event: dict[str, Any], plan: dict[str, Any]) -> None:
        metadata = dict(route.get("metadata") or {})
        used = list(metadata.get("used_beat_keys") or [])
        beat_key = plan.get("beat_key")
        if beat_key and beat_key not in used:
            used.append(beat_key)
        cadence_policy = plan.get("cadence_policy") if isinstance(plan.get("cadence_policy"), dict) else {}
        min_interval = max(int(cadence_policy.get("min_interval_minutes") or self.settings.day_stream_min_interval_minutes), 0)
        max_interval = max(int(cadence_policy.get("max_interval_minutes") or self.settings.day_stream_max_interval_minutes), min_interval)
        interval = random.randint(min_interval, max_interval) if max_interval > min_interval else min_interval
        if self._activity_band(self._local_now().hour) == "deep_night" and self.settings.day_deep_night_quiet_enabled:
            interval = max(interval, max_interval * 3, 30)
        metadata["used_beat_keys"] = used[-12:]
        metadata["next_eligible_at"] = (datetime.now(timezone.utc) + timedelta(minutes=interval)).isoformat()
        metadata["last_event_uid"] = event["event_uid"]
        self.product_store.update_companion_day_route(
            str(route["route_uid"]),
            {
                "metadata_json": metadata,
                "current_scene": route.get("current_scene") or "",
                "mood_label": route.get("mood_label") or "",
            },
        )

    def _deep_night_quiet_applies(self, scope: ConversationScope, now: datetime) -> bool:
        if not self.settings.day_deep_night_quiet_enabled or self._activity_band(self._local_now().hour) != "deep_night":
            return False
        latest_user = self.memory_store.get_latest_user_message(scope.conversation_id)
        if latest_user is None:
            return True
        created = parse_iso8601(latest_user.created_at)
        if created is None:
            return True
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created + timedelta(minutes=45) < now

    def _latest_event(self, scope: ConversationScope) -> dict[str, Any] | None:
        events = self.product_store.list_companion_day_events(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            limit=1,
        )
        return events[0] if events else None

    def _build_status_card(
        self,
        route: dict[str, Any],
        beat: dict[str, Any],
        reality_anchor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fields = [
            {"name": "心情", "value": truncate_text(str(beat.get("mood") or route.get("mood_label") or "想你"), 80)},
            {"name": "想你强度", "value": f"{float(route.get('longing_level') or 0):.2f}"},
        ]
        if reality_anchor:
            fields.append({"name": "现实锚点", "value": truncate_text(str(reality_anchor.get("label") or reality_anchor.get("type") or ""), 80)})
        return {
            "title": "沈知微此刻",
            "description": truncate_text(str(beat.get("scene") or route.get("current_scene") or ""), 180),
            "fields": fields,
            "footer": "这是她的一天里的角色日常，不是外部事实播报",
        }

    def _select_reality_anchor(self, scope: ConversationScope) -> dict[str, Any] | None:
        if not self.settings.reality_context_enabled or self.reality_context is None:
            return None
        try:
            anchors = self.reality_context.get_cached_anchors(scope)
        except Exception:  # noqa: BLE001
            return None
        events = list((anchors or {}).get("calendar_events") or [])
        now = datetime.now(timezone.utc)
        for event in events[:4]:
            start_at = parse_iso8601(str(event.get("start_at") or ""))
            if start_at is None:
                continue
            if start_at.tzinfo is None:
                start_at = start_at.replace(tzinfo=timezone.utc)
            minutes_until = (start_at - now).total_seconds() / 60
            if -15 <= minutes_until <= 180:
                title = truncate_text(compact_text(str(event.get("title") or "那件事")), 36)
                if minutes_until <= 20:
                    line = f"我记着你差不多要碰到{title}了，先别急着硬扛，收完跟我说一声"
                else:
                    line = f"我记着你等会儿还有{title}，所以想先来陪你稳一下"
                return {
                    "type": "calendar",
                    "label": title,
                    "event_uid": event.get("event_uid"),
                    "line": repair_immersive_voice(line),
                }
        weather = (anchors or {}).get("weather") or {}
        summary = compact_text(str(weather.get("summary_text") or ""))
        if weather.get("status") == "ok" and summary:
            soft = summary.rstrip("。")
            if len(soft) > 72:
                soft = truncate_text(soft, 72)
            line = f"我刚看了眼外面，{soft}，你今天别把自己晾着"
            return {
                "type": "weather",
                "label": str(weather.get("source_label") or "weather"),
                "snapshot_uid": weather.get("snapshot_uid"),
                "line": repair_immersive_voice(line),
            }
        return None

    def _format_route(self, route: dict[str, Any]) -> str:
        beats = (route.get("route") or {}).get("beats") or []
        return " / ".join(str(item.get("scene") or "") for item in beats[:4] if item.get("scene")) or str(route.get("current_scene") or "")

    def _extract_companion_life_detail(self, text: str) -> str:
        normalized = compact_text(text)
        for token in ("我这边", "这边", "桌边", "水杯", "灯", "窗", "衣服", "出门", "回来"):
            if token in normalized:
                return truncate_text(normalized, 220)
        return ""

    def _activity_band(self, hour: int) -> str:
        if 5 <= hour < 9:
            return "morning"
        if 9 <= hour < 12:
            return "late_morning"
        if 12 <= hour < 14:
            return "noon"
        if 14 <= hour < 18:
            return "afternoon"
        if 18 <= hour < 23:
            return "evening"
        return "deep_night"

    def _local_now(self) -> datetime:
        try:
            return datetime.now(ZoneInfo(self.settings.bot_timezone))
        except Exception:  # noqa: BLE001
            return datetime.now()
