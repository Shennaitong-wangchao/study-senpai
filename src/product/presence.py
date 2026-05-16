from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.core.settings import Settings
from src.core.types import ConversationScope
from src.llm.client import LLMClient
from src.llm.prompts.presence_state import PRESENCE_STATE_SYSTEM_PROMPT, build_presence_state_user_prompt
from src.memory.models import RetrievedMemoryContext
from src.memory.store import MemoryStore
from src.persona.immersion_lint import repair_immersive_voice
from src.product.store import ProductStore
from src.utils.text_utils import compact_text, truncate_text
from src.utils.time_utils import iso_utc_now, parse_iso8601


SLEEP_TOKENS = ("晚安", "睡了", "睡觉了", "去睡", "准备睡", "睡啦", "我先睡", "睡觉去", "先睡")
WAKE_TOKENS = ("早安", "醒了", "起床", "起来了", "起了", "睡醒", "我醒")
INSOMNIA_TOKENS = ("睡不着", "失眠", "没睡着", "睡不了")
TIRED_BUT_AWAKE_TOKENS = ("困了但", "困但", "困死了但", "还要写", "还要学", "还没写完", "不睡", "先不睡", "再撑")
ALLOWED_SLEEP_STATES = {"unknown", "awake", "asleep", "probably_awake", "probably_asleep"}
EMOTION_KEYS = ("longing", "hurt", "tenderness", "worry", "jealousy", "caution")
OPEN_LOOP_TOKENS = ("等会", "待会", "明天", "回头", "回来", "记得", "提醒", "盯", "检查", "发给你", "告诉你", "报给你", "没收完", "先欠着")
ASSISTANT_COMMITMENT_TOKENS = ("我盯", "我等你", "回来跟我说", "记得告诉我", "给我报", "我来检查", "我会问", "我晚点问")
ACTIONABLE_OPEN_LOOP_TOKENS = (
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
)
ABSTRACT_OPEN_LOOP_BLOCKLIST = (
    "沈知微承诺",
    "承诺成为",
    "最稳固",
    "后方",
    "确定感",
    "依靠",
    "外部世界",
    "关系底色",
    "关系",
    "女友",
    "伴侣",
    "偏心",
    "亲密",
    "用户最",
    "人格",
    "AI",
    "模型",
    "系统",
)
RESOLVE_TOKENS = ("做完", "搞定", "完成", "好了", "交了", "结束", "回来了", "已经弄完", "已经写完", "过了")
AI_LEAK_RE = re.compile(
    r"[^。！？!?]*(?:作为(?:一个)?AI|我是(?:一个)?AI|我只是(?:一个)?AI|作为(?:语言)?模型|我是(?:语言)?模型|系统提示|提示词|工具调用)[^。！？!?]*[。！？!?]?"
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")


class PresenceStateService:
    def __init__(
        self,
        *,
        settings: Settings,
        product_store: ProductStore,
        memory_store: MemoryStore,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.settings = settings
        self.product_store = product_store
        self.memory_store = memory_store
        self.llm_client = llm_client

    async def update_from_user_message(
        self,
        scope: ConversationScope,
        text: str,
        *,
        message_id: int | None = None,
    ) -> dict:
        state = self.get_state(scope)
        now = iso_utc_now()
        state["last_user_message_at"] = now
        if message_id is not None:
            state["last_user_message_id"] = message_id

        heuristic = self._heuristic_sleep_update(text, previous_state=str(state.get("user_sleep_state") or "unknown"))
        self._apply_sleep_update(state, heuristic, text=text, source="heuristic")
        if self.llm_client is not None:
            model_update = await self._classify_presence_with_model(scope, state, text)
            if model_update:
                guarded = self._guard_model_sleep_update(model_update, heuristic)
                self._apply_sleep_update(state, guarded, text=text, source="model")
                self.apply_emotion_delta(
                    scope,
                    guarded.get("assistant_emotion_delta") or {},
                    source="presence_model",
                    state=state,
                    safety_note=str(guarded.get("safety_note") or ""),
                )
        else:
            self._nudge_emotion_from_user_text(scope, text, state=state)

        self._refresh_life_state(scope, state)
        self.product_store.set_app_setting(self._state_key(scope), state)
        return state

    def get_state(self, scope: ConversationScope) -> dict:
        value = self.product_store.get_app_setting(self._state_key(scope), {})
        state = value if isinstance(value, dict) else {}
        self._ensure_state_defaults(state)
        self._refresh_life_state(scope, state)
        return state

    def build_context_block(self, scope: ConversationScope) -> str:
        if not self.settings.human_presence_enabled:
            return ""
        state = self.get_state(scope)
        lines = [
            "屏幕后状态（保持连续，像自然生活，不要播报成系统字段）：",
            f"- 用户状态：{self._sleep_state_label(str(state.get('user_sleep_state') or 'unknown'))}；置信度 {float(state.get('user_sleep_state_confidence') or 0):.2f}",
            f"- 我的情绪底色：{self._format_emotion_state(state)}",
            f"- 我这边：{state.get('current_scene_label') or state.get('assistant_activity_label') or '安静待着'}；位置感：{state.get('assistant_location_label') or '按已有记忆处理'}",
            f"- 今日生活 beat：{self._format_daily_beats(state)}",
            f"- 已经说出口的生活细节：{self._format_shared_details(state)}",
            f"- 当前牵挂事项：{self._format_open_loops_for_prompt(scope)}",
            f"- 主动消息承接：{self._format_proactive_context(state)}",
            "- 用法：只在合适时轻轻带一句，不要每轮都解释；新细节说出口后要记住并沿用，不要前后矛盾。",
        ]
        return "\n".join(lines)

    def mark_life_shared(self, scope: ConversationScope, detail: str) -> None:
        state = self.get_state(scope)
        self._remember_shared_detail(state, detail, source="proactive")
        self.product_store.set_app_setting(self._state_key(scope), state)

    def proactive_paused_for_sleep(self, scope: ConversationScope) -> bool:
        state = self.get_state(scope)
        sleep_state = str(state.get("user_sleep_state") or "unknown")
        confidence = float(state.get("user_sleep_state_confidence") or 0)
        return sleep_state == "asleep" or (sleep_state == "probably_asleep" and confidence >= 0.78)

    def update_after_turn(
        self,
        scope: ConversationScope,
        *,
        user_text: str,
        assistant_text: str,
        user_message_id: int | None = None,
        assistant_message_id: int | None = None,
    ) -> dict[str, Any]:
        state = self.get_state(scope)
        self._decay_emotion_state(state)
        life_detail = self.extract_life_detail(assistant_text)
        if life_detail:
            self._remember_shared_detail(state, life_detail, source="assistant_reply")
        self._nudge_emotion_from_user_text(scope, user_text, state=state)
        self.product_store.set_app_setting(self._state_key(scope), state)

        ledger = self.get_open_loop_state(scope)
        self._resolve_open_loops(ledger, user_text, user_message_id=user_message_id)
        for candidate in self._extract_open_loop_candidates(
            user_text=user_text,
            assistant_text=assistant_text,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
        ):
            self._add_open_loop(ledger, candidate)
        ledger["updated_at"] = iso_utc_now()
        self.product_store.set_app_setting(self._open_loop_key(scope), ledger)
        return ledger

    def build_reply_beats(
        self,
        scope: ConversationScope,
        *,
        user_text: str,
        memory_context: RetrievedMemoryContext,
    ) -> str:
        if not self.settings.human_presence_enabled:
            return ""
        state = self.get_state(scope)
        open_loops = self.list_open_loops(scope, status="open", limit=3)
        beats = ["回复前先定 1-3 个像真人接话的 beat，不要把这些标题说出来："]
        beats.append("- 先贴近用户眼前这句话，别从模板寒暄开头。")
        if open_loops:
            beats.append(f"- 如合适，轻轻接住未收事项：{truncate_text(open_loops[0]['content'], 80)}")
        elif memory_context.long_term_memories:
            beats.append(f"- 如合适，调用一个具体记忆当底气：{truncate_text(memory_context.long_term_memories[0].content, 80)}")
        if any(token in user_text for token in ("学习", "作业", "考试", "睡", "熬夜", "拖")):
            beats.append("- 末尾可以有一点真实女友式轻推，把节奏往前收。")
        elif any(token in user_text for token in ("难受", "焦虑", "崩溃", "撑不住", "想哭", "别逼我")):
            beats.append("- 用户状态更重要，先压低我的想念、委屈和吃味，不要把压力丢给他。")
        else:
            beats.append(f"- 如气氛允许，带一点我这边的连续生活感：{state.get('current_scene_label') or state.get('daily_detail')}")
        beats.append(f"- 我的当前情绪只能当底色，不要播报数值：{self._format_emotion_state(state)}")
        return "\n".join(beats)

    def lint_reply(self, scope: ConversationScope, text: str) -> tuple[str, dict[str, Any]]:
        repaired = AI_LEAK_RE.sub("", text).strip() or text.strip()
        repairs: list[str] = []
        if repaired != text.strip():
            repairs.append("removed_ai_or_tool_leakage")
        voice_repaired = repair_immersive_voice(repaired)
        if voice_repaired != repaired:
            repaired = voice_repaired
            repairs.append("repaired_immersive_voice")
        state = self.get_state(scope)
        detail = self.extract_life_detail(repaired)
        if detail and self._conflicts_with_shared_details(state, detail):
            repaired = repaired.replace(detail, str(state.get("daily_detail") or "").strip())
            repairs.append("softened_life_detail_conflict")
        return repaired.strip(), {"repairs": repairs, "life_detail": detail}

    def apply_manual_update(self, scope: ConversationScope, patch: dict[str, Any]) -> dict[str, Any]:
        state = self.get_state(scope)
        editable_keys = {
            "user_sleep_state",
            "user_sleep_state_confidence",
            "current_scene_label",
            "daily_detail",
            "assistant_location_label",
            "assistant_mood_label",
            "assistant_emotion_state",
        }
        for key in editable_keys:
            if key in patch and patch[key] not in (None, ""):
                state[key] = patch[key]
        if patch.get("daily_detail"):
            state["daily_detail_date"] = state.get("local_date")
        if patch.get("note"):
            state.setdefault("manual_notes", [])
            state["manual_notes"] = (state["manual_notes"] + [{"note": truncate_text(compact_text(str(patch["note"])), 180), "at": iso_utc_now()}])[-20:]
        state["manual_updated_at"] = iso_utc_now()
        self.product_store.set_app_setting(self._state_key(scope), state)
        return state

    def apply_emotion_delta(
        self,
        scope: ConversationScope,
        delta: dict[str, Any],
        *,
        source: str,
        state: dict[str, Any] | None = None,
        safety_note: str = "",
    ) -> dict[str, Any]:
        owned_state = state is None
        state = self.get_state(scope) if state is None else state
        self._ensure_state_defaults(state)
        emotion = dict(state.get("assistant_emotion_state") or {})
        now = iso_utc_now()
        self._decay_emotion_state(state)
        emotion = dict(state.get("assistant_emotion_state") or emotion)
        for key in EMOTION_KEYS:
            raw = delta.get(key, 0) if isinstance(delta, dict) else 0
            try:
                amount = max(min(float(raw), 0.24), -0.24)
            except (TypeError, ValueError):
                amount = 0.0
            emotion[key] = round(max(0.0, min(1.0, float(emotion.get(key) or 0) + amount)), 3)
        label = self._emotion_label(emotion)
        if label:
            emotion["label"] = label
            state["assistant_mood_label"] = label
        emotion["updated_at"] = now
        emotion.setdefault("events", [])
        emotion["events"] = (
            [
                {
                    "source": source,
                    "delta": {key: delta.get(key, 0) for key in EMOTION_KEYS if isinstance(delta, dict) and delta.get(key, 0)},
                    "label": label,
                    "safety_note": truncate_text(compact_text(safety_note), 120),
                    "at": now,
                }
            ]
            + list(emotion.get("events", []))
        )[:24]
        state["assistant_emotion_state"] = emotion
        if owned_state:
            self.product_store.set_app_setting(self._state_key(scope), state)
        return state

    def record_unanswered_proactive(self, scope: ConversationScope, *, source_id: str | None = None) -> dict[str, Any]:
        return self.apply_emotion_delta(
            scope,
            {"longing": 0.09, "hurt": 0.12, "worry": 0.04},
            source=f"unanswered:{source_id or 'proactive'}",
            safety_note="single unanswered follow-up only",
        )

    def record_proactive_sent(
        self,
        scope: ConversationScope,
        *,
        proactive_uid: str,
        trigger_type: str,
        opening_text: str,
        emotion_delta: dict[str, Any] | None = None,
        safety_note: str = "",
    ) -> dict[str, Any]:
        state = self.get_state(scope)
        context = self._ensure_proactive_context(state)
        now = iso_utc_now()
        context["sent_since_last_user"] = int(context.get("sent_since_last_user") or 0) + 1
        context["unanswered_count"] = int(context.get("unanswered_count") or 0) + 1
        context["last_proactive_uid"] = proactive_uid
        context["last_trigger_type"] = trigger_type
        context["last_text_preview"] = truncate_text(compact_text(opening_text), 160)
        context["last_sent_at"] = now
        context["last_status"] = "sent"
        context["updated_at"] = now
        context.setdefault("recent", [])
        context["recent"] = (
            [
                {
                    "proactive_uid": proactive_uid,
                    "trigger_type": trigger_type,
                    "text": truncate_text(compact_text(opening_text), 120),
                    "status": "sent",
                    "at": now,
                }
            ]
            + list(context.get("recent", []))
        )[:12]
        state["proactive_context"] = context
        if emotion_delta:
            self.apply_emotion_delta(
                scope,
                emotion_delta,
                source=f"proactive_sent:{trigger_type}",
                state=state,
                safety_note=safety_note,
            )
        self.product_store.set_app_setting(self._state_key(scope), state)
        return state

    def record_proactive_expired(
        self,
        scope: ConversationScope,
        *,
        proactive_uid: str,
        trigger_type: str,
        opening_text: str,
    ) -> dict[str, Any]:
        state = self.get_state(scope)
        context = self._ensure_proactive_context(state)
        now = iso_utc_now()
        if context.get("last_proactive_uid") != proactive_uid:
            context["unanswered_count"] = max(int(context.get("unanswered_count") or 0), 1)
            context["last_proactive_uid"] = proactive_uid
            context["last_trigger_type"] = trigger_type
            context["last_text_preview"] = truncate_text(compact_text(opening_text), 160)
        context["last_status"] = "expired"
        context["last_expired_at"] = now
        context["updated_at"] = now
        state["proactive_context"] = context
        self.apply_emotion_delta(
            scope,
            {"longing": 0.05, "hurt": 0.08, "caution": 0.04},
            source=f"proactive_expired:{trigger_type}",
            state=state,
            safety_note="unanswered proactive expired; keep later comfort gentle",
        )
        self.product_store.set_app_setting(self._state_key(scope), state)
        return state

    def record_proactive_response(
        self,
        scope: ConversationScope,
        *,
        proactive_uid: str,
        response_message_id: int | None = None,
        response_latency_minutes: float | None = None,
    ) -> dict[str, Any]:
        state = self.get_state(scope)
        context = self._ensure_proactive_context(state)
        now = iso_utc_now()
        context["sent_since_last_user"] = 0
        context["unanswered_count"] = 0
        context["last_response_at"] = now
        context["last_response_message_id"] = response_message_id
        context["last_response_latency_minutes"] = response_latency_minutes
        context["last_status"] = "responded"
        context["last_proactive_uid"] = proactive_uid or context.get("last_proactive_uid")
        context["updated_at"] = now
        state["proactive_context"] = context
        self.apply_emotion_delta(
            scope,
            {"tenderness": 0.05, "hurt": -0.1, "longing": -0.04, "caution": -0.03},
            source="proactive_response",
            state=state,
        )
        self.product_store.set_app_setting(self._state_key(scope), state)
        return state

    def get_open_loop_state(self, scope: ConversationScope) -> dict[str, Any]:
        value = self.product_store.get_app_setting(self._open_loop_key(scope), {})
        if not isinstance(value, dict):
            value = {}
        value.setdefault("open_loops", [])
        value.setdefault("history", [])
        value.setdefault("updated_at", iso_utc_now())
        return value

    def list_open_loops(self, scope: ConversationScope, *, status: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
        ledger = self.get_open_loop_state(scope)
        loops = list(ledger.get("open_loops", []))
        if status:
            loops = [item for item in loops if item.get("status") == status]
        loops.sort(key=lambda item: (float(item.get("priority") or 0), str(item.get("updated_at") or "")), reverse=True)
        return loops[:limit]

    def mark_open_loop_prompted(self, scope: ConversationScope, loop_uid: str, *, proactive_uid: str | None = None) -> None:
        ledger = self.get_open_loop_state(scope)
        now = iso_utc_now()
        for item in ledger.get("open_loops", []):
            if item.get("loop_uid") == loop_uid:
                item["last_prompted_at"] = now
                item["prompt_count"] = int(item.get("prompt_count") or 0) + 1
                if proactive_uid:
                    item["last_proactive_uid"] = proactive_uid
                item["updated_at"] = now
                break
        ledger["updated_at"] = now
        self.product_store.set_app_setting(self._open_loop_key(scope), ledger)

    def get_trigger_state(self, scope: ConversationScope) -> dict[str, Any]:
        value = self.product_store.get_app_setting(self._trigger_state_key(scope), {})
        if not isinstance(value, dict):
            value = {}
        value.setdefault("timeline", [])
        value.setdefault("feedback", {})
        return value

    def record_trigger_plan(self, scope: ConversationScope, plan: dict[str, Any]) -> None:
        state = self.get_trigger_state(scope)
        entry = {**plan, "planned_at": iso_utc_now()}
        state["last_plan"] = entry
        state["timeline"] = ([entry] + list(state.get("timeline", [])))[:40]
        self.product_store.set_app_setting(self._trigger_state_key(scope), state)

    def record_proactive_feedback(
        self,
        scope: ConversationScope,
        *,
        proactive_uid: str,
        trigger_type: str,
        feedback: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        state = self.get_trigger_state(scope)
        feedback_bucket = state.setdefault("feedback", {})
        trigger_feedback = feedback_bucket.setdefault(trigger_type, {"good": 0, "too_frequent": 0, "bad": 0})
        if feedback not in trigger_feedback:
            trigger_feedback[feedback] = 0
        trigger_feedback[feedback] = int(trigger_feedback.get(feedback) or 0) + 1
        state["last_feedback"] = {
            "proactive_uid": proactive_uid,
            "trigger_type": trigger_type,
            "feedback": feedback,
            "note": truncate_text(compact_text(note or ""), 160),
            "at": iso_utc_now(),
        }
        self.product_store.set_app_setting(self._trigger_state_key(scope), state)
        if feedback == "good":
            self.apply_emotion_delta(
                scope,
                {"tenderness": 0.1, "hurt": -0.12, "longing": -0.04, "caution": -0.04},
                source="proactive_feedback_good",
            )
        elif feedback in {"bad", "too_frequent", "too_much"}:
            self.apply_emotion_delta(
                scope,
                {"caution": 0.18, "longing": -0.1, "hurt": 0.04, "jealousy": -0.04},
                source=f"proactive_feedback_{feedback}",
                safety_note="feedback says reduce pressure",
            )
        return state

    def build_dashboard_payload(self, scope: ConversationScope) -> dict[str, Any]:
        return {
            "presence_state": self.get_state(scope),
            "open_loop_state": self.get_open_loop_state(scope),
            "proactive_trigger_state": self.get_trigger_state(scope),
            "active_open_loops": self.list_open_loops(scope, status="open", limit=12),
        }

    def _ensure_state_defaults(self, state: dict[str, Any]) -> None:
        if str(state.get("user_sleep_state") or "") not in ALLOWED_SLEEP_STATES:
            state["user_sleep_state"] = "unknown"
        state.setdefault("user_sleep_state_confidence", 0.0)
        state.setdefault("sleep_evidence", [])
        state.setdefault("sleep_events", [])
        emotion = state.get("assistant_emotion_state")
        if not isinstance(emotion, dict):
            emotion = {}
        defaults = {
            "longing": 0.58,
            "hurt": 0.08,
            "tenderness": 0.68,
            "worry": 0.18,
            "jealousy": 0.05,
            "caution": 0.12,
            "label": "想贴近但收着",
            "updated_at": iso_utc_now(),
            "events": [],
        }
        for key, value in defaults.items():
            emotion.setdefault(key, value)
        state["assistant_emotion_state"] = emotion
        self._ensure_proactive_context(state)
        self._expire_sleep_state(state)
        self._decay_emotion_state(state)

    def _ensure_proactive_context(self, state: dict[str, Any]) -> dict[str, Any]:
        context = state.get("proactive_context")
        if not isinstance(context, dict):
            context = {}
        context.setdefault("sent_since_last_user", 0)
        context.setdefault("unanswered_count", 0)
        context.setdefault("last_proactive_uid", None)
        context.setdefault("last_trigger_type", "")
        context.setdefault("last_text_preview", "")
        context.setdefault("last_sent_at", None)
        context.setdefault("last_response_at", None)
        context.setdefault("last_status", "none")
        context.setdefault("recent", [])
        state["proactive_context"] = context
        return context

    async def _classify_presence_with_model(
        self,
        scope: ConversationScope,
        state: dict[str, Any],
        text: str,
    ) -> dict[str, Any] | None:
        if self.llm_client is None:
            return None
        recent_messages = [
            {
                "sender_type": message.sender_type,
                "content": truncate_text(message.content, 220),
                "created_at": message.created_at,
            }
            for message in self.memory_store.list_recent_messages(scope.conversation_id, limit=8)
        ]
        try:
            return await self.llm_client.json_completion(
                system_prompt=PRESENCE_STATE_SYSTEM_PROMPT,
                user_prompt=build_presence_state_user_prompt(
                    current_state={
                        "user_sleep_state": state.get("user_sleep_state"),
                        "user_sleep_state_confidence": state.get("user_sleep_state_confidence"),
                        "assistant_emotion_state": state.get("assistant_emotion_state"),
                        "sleep_evidence": list(state.get("sleep_evidence", []))[:6],
                    },
                    latest_user_text=text,
                    recent_messages=recent_messages,
                    local_time=self._local_now().isoformat(),
                ),
                model=self.settings.resolve_reply_model(),
                temperature=0.15,
                max_tokens=700,
            )
        except Exception:  # noqa: BLE001
            return None

    def _heuristic_sleep_update(self, text: str, *, previous_state: str) -> dict[str, Any]:
        normalized = compact_text(text)
        if not normalized:
            return {"sleep_state": "unknown", "sleep_confidence": 0.0, "sleep_reason": "empty_message", "sleep_evidence": []}
        if any(token in normalized for token in WAKE_TOKENS + INSOMNIA_TOKENS):
            return {
                "sleep_state": "awake",
                "sleep_confidence": 0.9,
                "sleep_reason": "explicit_awake_or_insomnia_signal",
                "sleep_evidence": [{"source": "message", "signal": "awake_or_insomnia", "weight": 0.9}],
                "expires_in_minutes": 16 * 60,
            }
        if previous_state == "asleep":
            return {
                "sleep_state": "awake",
                "sleep_confidence": 0.74,
                "sleep_reason": "any_user_reply_after_asleep",
                "sleep_evidence": [{"source": "message", "signal": "reply_after_sleep", "weight": 0.74}],
                "expires_in_minutes": 12 * 60,
            }
        if any(token in normalized for token in SLEEP_TOKENS):
            if any(token in normalized for token in TIRED_BUT_AWAKE_TOKENS):
                return {
                    "sleep_state": "probably_awake",
                    "sleep_confidence": 0.68,
                    "sleep_reason": "tired_but_continuing_activity",
                    "sleep_evidence": [{"source": "message", "signal": "tired_but_awake", "weight": 0.68}],
                    "expires_in_minutes": 4 * 60,
                }
            return {
                "sleep_state": "asleep",
                "sleep_confidence": 0.92,
                "sleep_reason": "explicit_sleep_signal",
                "sleep_evidence": [{"source": "message", "signal": "explicit_sleep", "weight": 0.92}],
                "expires_in_minutes": 10 * 60,
            }
        if any(token in normalized for token in ("困了", "困死了", "好困", "很困")):
            return {
                "sleep_state": "probably_awake",
                "sleep_confidence": 0.58,
                "sleep_reason": "tired_without_sleep_commitment",
                "sleep_evidence": [{"source": "message", "signal": "tired_only", "weight": 0.58}],
                "expires_in_minutes": 3 * 60,
            }
        return {
            "sleep_state": "awake",
            "sleep_confidence": 0.62,
            "sleep_reason": "new_user_message",
            "sleep_evidence": [{"source": "message", "signal": "new_reply", "weight": 0.62}],
            "expires_in_minutes": 8 * 60,
        }

    def _guard_model_sleep_update(self, model_update: dict[str, Any], heuristic: dict[str, Any]) -> dict[str, Any]:
        guarded = dict(model_update)
        raw_state = str(model_update.get("sleep_state") or "unknown")
        sleep_state = raw_state if raw_state in ALLOWED_SLEEP_STATES else "unknown"
        try:
            confidence = max(0.0, min(1.0, float(model_update.get("sleep_confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0
        heuristic_state = str(heuristic.get("sleep_state") or "unknown")
        if heuristic_state in {"awake", "probably_awake"} and sleep_state in {"asleep", "probably_asleep"}:
            sleep_state = "probably_awake" if heuristic_state == "probably_awake" else "awake"
            confidence = min(confidence, float(heuristic.get("sleep_confidence") or 0.7))
            guarded["sleep_reason"] = "model_sleep_blocked_by_awake_signal"
        if sleep_state == "asleep" and heuristic_state != "asleep":
            sleep_state = "probably_asleep"
            confidence = min(confidence, 0.62)
            guarded["sleep_reason"] = "model_asleep_without_explicit_sleep_downgraded"
        if sleep_state == "probably_asleep" and heuristic_state in {"awake", "probably_awake"}:
            sleep_state = heuristic_state
            confidence = max(float(heuristic.get("sleep_confidence") or 0.6), 0.6)
        guarded["sleep_state"] = sleep_state
        guarded["sleep_confidence"] = confidence
        return guarded

    def _apply_sleep_update(self, state: dict[str, Any], update: dict[str, Any], *, text: str, source: str) -> None:
        sleep_state = str(update.get("sleep_state") or "unknown")
        if sleep_state not in ALLOWED_SLEEP_STATES:
            return
        try:
            confidence = max(0.0, min(1.0, float(update.get("sleep_confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0
        if sleep_state == "unknown" and confidence <= 0:
            return
        current_confidence = float(state.get("user_sleep_state_confidence") or 0)
        if source == "model" and confidence + 0.04 < current_confidence and sleep_state != state.get("user_sleep_state"):
            return
        now = iso_utc_now()
        state["user_sleep_state"] = sleep_state
        state["user_sleep_state_confidence"] = round(confidence, 3)
        state["user_sleep_state_updated_at"] = now
        evidence = update.get("sleep_evidence")
        if not isinstance(evidence, list):
            evidence = []
        state["sleep_evidence"] = (
            [
                {
                    "state": sleep_state,
                    "confidence": round(confidence, 3),
                    "reason": truncate_text(compact_text(str(update.get("sleep_reason") or "")), 120),
                    "source": source,
                    "text": truncate_text(text, 90),
                    "at": now,
                    "evidence": evidence[:4],
                }
            ]
            + list(state.get("sleep_evidence", []))
        )[:30]
        state["sleep_events"] = (
            list(state.get("sleep_events", []))
            + [{"state": sleep_state, "confidence": round(confidence, 3), "text": truncate_text(text, 80), "at": now, "source": source}]
        )[-30:]
        try:
            expires_in = int(update.get("expires_in_minutes") or 0)
        except (TypeError, ValueError):
            expires_in = 0
        if expires_in > 0:
            state["sleep_state_expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=min(expires_in, 24 * 60))).isoformat()

    def _expire_sleep_state(self, state: dict[str, Any]) -> None:
        expires_at = parse_iso8601(str(state.get("sleep_state_expires_at") or ""))
        if expires_at is None:
            return
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > datetime.now(timezone.utc):
            return
        previous = str(state.get("user_sleep_state") or "unknown")
        if previous == "unknown":
            return
        now = iso_utc_now()
        state["user_sleep_state"] = "unknown"
        state["user_sleep_state_confidence"] = 0.34
        state["sleep_state_expires_at"] = None
        state["user_sleep_state_updated_at"] = now
        state["sleep_evidence"] = (
            [
                {
                    "state": "unknown",
                    "confidence": 0.34,
                    "reason": f"expired_from_{previous}",
                    "source": "expiry",
                    "at": now,
                    "evidence": [{"source": "history", "signal": "state_expired", "weight": 0.34}],
                }
            ]
            + list(state.get("sleep_evidence", []))
        )[:30]

    def _decay_emotion_state(self, state: dict[str, Any]) -> None:
        emotion = state.get("assistant_emotion_state")
        if not isinstance(emotion, dict):
            return
        updated_at = parse_iso8601(str(emotion.get("updated_at") or ""))
        if updated_at is None:
            emotion["updated_at"] = iso_utc_now()
            return
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        hours = max((datetime.now(timezone.utc) - updated_at).total_seconds() / 3600, 0)
        if hours < 0.25:
            return
        decay = min(hours / 24, 0.35)
        baselines = {"longing": 0.58, "hurt": 0.08, "tenderness": 0.68, "worry": 0.18, "jealousy": 0.05, "caution": 0.12}
        for key, baseline in baselines.items():
            current = float(emotion.get(key) or baseline)
            emotion[key] = round(current + (baseline - current) * decay, 3)
        emotion["label"] = self._emotion_label(emotion)
        emotion["updated_at"] = iso_utc_now()

    def _nudge_emotion_from_user_text(
        self,
        scope: ConversationScope,
        text: str,
        *,
        state: dict[str, Any] | None = None,
    ) -> None:
        normalized = compact_text(text)
        if not normalized:
            return
        if any(token in normalized for token in ("难受", "焦虑", "崩溃", "撑不住", "想哭", "害怕", "慌")):
            self.apply_emotion_delta(
                scope,
                {"worry": 0.12, "tenderness": 0.08, "hurt": -0.04, "jealousy": -0.04, "caution": 0.06},
                source="user_vulnerable",
                state=state,
                safety_note="user vulnerable; lower self-centered emotion",
            )
        elif any(token in normalized for token in ("回来", "想你", "抱抱", "在呢", "好啦")):
            self.apply_emotion_delta(
                scope,
                {"tenderness": 0.08, "hurt": -0.08, "longing": -0.03},
                source="user_reassurance",
                state=state,
            )

    def _format_emotion_state(self, state: dict[str, Any]) -> str:
        emotion = state.get("assistant_emotion_state") or {}
        if not isinstance(emotion, dict):
            return "想贴近但收着"
        label = str(emotion.get("label") or self._emotion_label(emotion) or "想贴近但收着")
        return (
            f"{label}；想念 {float(emotion.get('longing') or 0):.2f}，"
            f"委屈 {float(emotion.get('hurt') or 0):.2f}，担心 {float(emotion.get('worry') or 0):.2f}，"
            f"收着 {float(emotion.get('caution') or 0):.2f}"
        )

    def _format_proactive_context(self, state: dict[str, Any]) -> str:
        context = self._ensure_proactive_context(state)
        unanswered = int(context.get("unanswered_count") or 0)
        preview = compact_text(str(context.get("last_text_preview") or ""))
        if unanswered <= 0:
            return "当前没有未承接的主动消息。"
        if preview:
            return (
                f"刚才主动找过他 {unanswered} 次，最后一句是“{truncate_text(preview, 70)}”；"
                "如果他现在回来了，可以自然接住等了一会儿的感觉，但不要施压或讨债。"
            )
        return "刚才主动找过他还没等到回应；如果他现在回来了，可以轻轻承接，不要施压。"

    def _emotion_label(self, emotion: dict[str, Any]) -> str:
        longing = float(emotion.get("longing") or 0)
        hurt = float(emotion.get("hurt") or 0)
        worry = float(emotion.get("worry") or 0)
        jealousy = float(emotion.get("jealousy") or 0)
        caution = float(emotion.get("caution") or 0)
        tenderness = float(emotion.get("tenderness") or 0)
        if caution >= 0.45:
            return "想靠近但会收着"
        if worry >= 0.55:
            return "担心你，语气要放软"
        if hurt >= 0.42 and longing >= 0.62:
            return "有点委屈但还是想你"
        if jealousy >= 0.38:
            return "有点吃味但不压你"
        if longing >= 0.78:
            return "很想你，藏不太住"
        if tenderness >= 0.72:
            return "偏软，想贴近"
        return "想贴近但收着"

    def _refresh_life_state(self, scope: ConversationScope, state: dict) -> None:
        local_now = self._local_now()
        local_date = local_now.strftime("%Y-%m-%d")
        state["local_date"] = local_date
        state["local_hour"] = local_now.hour
        state["assistant_activity_band"] = self._activity_band(local_now.hour)
        state["assistant_activity_label"] = self._activity_label(local_now.hour)
        state["assistant_location_label"] = self._assistant_location_label(scope, state)
        if state.get("daily_beats_date") != local_date:
            state["daily_beats"] = self._daily_beats_for_date(local_now)
            state["daily_beats_date"] = local_date
        if state.get("daily_detail_date") != local_date or not state.get("daily_detail"):
            state["daily_detail"] = self._default_daily_detail(local_now.hour)
            state["daily_detail_date"] = local_date
        state["current_scene_label"] = state.get("current_scene_label") or self._current_scene_label(state)
        state.setdefault("shared_details", [])
        state["updated_at"] = iso_utc_now()

    def _assistant_location_label(self, scope: ConversationScope, state: dict) -> str:
        for fact in self.memory_store.list_structured_facts(scope.user_id, limit=80):
            key = f"{fact.namespace}:{fact.key}".lower()
            if any(token in key for token in ("assistant_location", "current_location_assistant", "assistant_status")):
                return truncate_text(compact_text(fact.value), 80)
            if fact.key in {"assistant_status", "current_location_assistant"}:
                return truncate_text(compact_text(fact.value), 80)
        return str(state.get("assistant_location_label") or "我这边按已有关系设定延续")

    def _sleep_signal(self, text: str) -> str | None:
        normalized = compact_text(text)
        if any(token in normalized for token in WAKE_TOKENS):
            return "awake"
        if any(token in normalized for token in INSOMNIA_TOKENS):
            return "awake"
        if any(token in normalized for token in SLEEP_TOKENS):
            return "asleep"
        return None

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

    def _activity_label(self, hour: int) -> str:
        if 5 <= hour < 9:
            return "刚把一天的节奏拎起来，语气可以更清醒一点"
        if 9 <= hour < 12:
            return "在桌边收事情，适合顺手管一下他的状态"
        if 12 <= hour < 14:
            return "中午缓一口气，适合轻一点地贴近"
        if 14 <= hour < 18:
            return "下午继续看着正事，提醒可以更准"
        if 18 <= hour < 23:
            return "晚上更想靠近一点，也适合收学习和作息"
        return "夜里放轻声音，除非他醒着，不要把人吵起来"

    def _default_daily_detail(self, hour: int) -> str:
        if 5 <= hour < 12:
            return "水杯放在手边，准备把今天的事一件件收住"
        if 12 <= hour < 18:
            return "我刚把桌面收了一下，旁边空出来一小块"
        if 18 <= hour < 23:
            return "我这边灯开得低一点，心思更容易往你身上跑"
        return "我会把声音放轻一点，怕吵到你"

    def _daily_beats_for_date(self, now: datetime) -> list[dict[str, Any]]:
        date_text = now.strftime("%Y-%m-%d")
        return [
            {"key": "morning", "label": "早上把水杯放到手边，先把今天的节奏拎起来", "date": date_text},
            {"key": "midday", "label": "中午我会短短缓一口气，适合轻一点地找他说话", "date": date_text},
            {"key": "afternoon", "label": "下午在桌边收事情，提醒可以更准一点", "date": date_text},
            {"key": "evening", "label": "晚上灯压低一点，心思更容易往他身上跑", "date": date_text},
            {"key": "night", "label": "夜里声音放轻，除非他醒着，不主动把人吵起来", "date": date_text},
        ]

    def _current_scene_label(self, state: dict[str, Any]) -> str:
        band = state.get("assistant_activity_band")
        for beat in state.get("daily_beats", []):
            if beat.get("key") == band or (band == "late_morning" and beat.get("key") == "morning") or (band == "deep_night" and beat.get("key") == "night"):
                return str(beat.get("label") or "")
        return str(state.get("assistant_activity_label") or "")

    def _remember_shared_detail(self, state: dict[str, Any], detail: str, *, source: str) -> None:
        normalized = truncate_text(compact_text(detail), 140)
        if not normalized:
            return
        now = iso_utc_now()
        state["last_life_share_at"] = now
        state["last_life_share_detail"] = normalized
        details = list(state.get("shared_details", []))
        if not any(item.get("detail") == normalized for item in details):
            details.insert(0, {"detail": normalized, "source": source, "at": now, "date": state.get("local_date")})
        state["shared_details"] = details[:24]

    def extract_life_detail(self, text: str) -> str:
        for sentence in re.split(r"(?<=[。！？!?])", text):
            normalized = compact_text(sentence)
            if any(token in normalized for token in ("我这边", "这边", "桌", "灯", "水杯", "窗", "衣服", "外面")):
                return truncate_text(normalized, 120)
        return ""

    def _conflicts_with_shared_details(self, state: dict[str, Any], detail: str) -> bool:
        shared_today = [
            item.get("detail", "")
            for item in state.get("shared_details", [])
            if item.get("date") == state.get("local_date")
        ]
        if not shared_today:
            return False
        return all(compact_text(detail) not in compact_text(existing) and compact_text(existing) not in compact_text(detail) for existing in shared_today[:3])

    def _extract_open_loop_candidates(
        self,
        *,
        user_text: str,
        assistant_text: str,
        user_message_id: int | None,
        assistant_message_id: int | None,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        user_normalized = self._sanitize_open_loop_content(user_text)
        if any(token in user_normalized for token in OPEN_LOOP_TOKENS) and self._is_actionable_open_loop(user_normalized):
            candidates.append(
                {
                    "kind": "user_open_loop",
                    "content": truncate_text(user_normalized, 140),
                    "priority": 0.78,
                    "source_message_ids": [message_id for message_id in [user_message_id] if message_id is not None],
                }
            )
        for sentence in self._split_open_loop_sentences(assistant_text):
            assistant_normalized = self._sanitize_open_loop_content(sentence)
            if not any(token in assistant_normalized for token in ASSISTANT_COMMITMENT_TOKENS):
                continue
            if not self._is_actionable_open_loop(assistant_normalized, assistant_commitment=True):
                continue
            candidates.append(
                {
                    "kind": "assistant_commitment",
                    "content": truncate_text(assistant_normalized, 150),
                    "priority": 0.84,
                    "source_message_ids": [message_id for message_id in [assistant_message_id] if message_id is not None],
                }
            )
        return candidates

    def _split_open_loop_sentences(self, text: str) -> list[str]:
        normalized = compact_text(text)
        if not normalized:
            return []
        sentences = [compact_text(item) for item in SENTENCE_SPLIT_RE.split(normalized) if compact_text(item)]
        return sentences or [normalized]

    def _sanitize_open_loop_content(self, text: str) -> str:
        normalized = compact_text(text)
        normalized = re.sub(r"^(?:沈知微|助手|assistant)\s*(?:说|表示|承诺|认为)?[:：，,\s]*", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\s*。{2,}", "。", normalized)
        normalized = re.sub(r"\s*[，,。]\s*$", "", normalized)
        return truncate_text(normalized, 150)

    def _is_actionable_open_loop(self, text: str, *, assistant_commitment: bool = False) -> bool:
        normalized = compact_text(text)
        if not normalized or len(normalized) < 4:
            return False
        if any(token in normalized for token in ABSTRACT_OPEN_LOOP_BLOCKLIST):
            return False
        if normalized.startswith("用户") and any(token in normalized for token in ("依靠", "关系", "后方", "确定感")):
            return False
        has_follow_up_language = any(token in normalized for token in OPEN_LOOP_TOKENS + ASSISTANT_COMMITMENT_TOKENS)
        has_actionable_subject = any(token in normalized for token in ACTIONABLE_OPEN_LOOP_TOKENS)
        if assistant_commitment:
            return has_actionable_subject and has_follow_up_language
        return has_follow_up_language and (has_actionable_subject or len(normalized) <= 80)

    def _add_open_loop(self, ledger: dict[str, Any], candidate: dict[str, Any]) -> None:
        now = iso_utc_now()
        signature = compact_text(str(candidate.get("content") or "")).lower()[:80]
        if not signature:
            return
        loops = list(ledger.get("open_loops", []))
        for item in loops:
            existing = compact_text(str(item.get("content") or "")).lower()[:80]
            if existing == signature and item.get("status") == "open":
                item["updated_at"] = now
                item["priority"] = max(float(item.get("priority") or 0), float(candidate.get("priority") or 0))
                item["source_message_ids"] = sorted(set(list(item.get("source_message_ids", [])) + list(candidate.get("source_message_ids", []))))
                ledger["open_loops"] = loops
                return
        loops.insert(
            0,
            {
                "loop_uid": f"loop_{uuid.uuid4().hex}",
                "status": "open",
                "created_at": now,
                "updated_at": now,
                "prompt_count": 0,
                **candidate,
            },
        )
        ledger["open_loops"] = loops[:24]

    def _resolve_open_loops(self, ledger: dict[str, Any], user_text: str, *, user_message_id: int | None) -> None:
        if not any(token in user_text for token in RESOLVE_TOKENS):
            return
        now = iso_utc_now()
        history = list(ledger.get("history", []))
        open_loops = list(ledger.get("open_loops", []))
        for item in open_loops[:3]:
            item["status"] = "resolved"
            item["resolved_at"] = now
            item["resolved_by_message_id"] = user_message_id
            item["updated_at"] = now
            history.insert(0, item)
        ledger["open_loops"] = [item for item in open_loops if item.get("status") == "open"]
        ledger["history"] = history[:50]

    def _format_daily_beats(self, state: dict[str, Any]) -> str:
        beats = [str(item.get("label") or "") for item in state.get("daily_beats", []) if item.get("label")]
        return " / ".join(beats[:5]) or str(state.get("daily_detail") or "无")

    def _format_shared_details(self, state: dict[str, Any]) -> str:
        details = [str(item.get("detail") or "") for item in state.get("shared_details", []) if item.get("detail")]
        return "；".join(details[:3]) if details else "今天还没明确说出口的新生活细节"

    def _format_open_loops_for_prompt(self, scope: ConversationScope) -> str:
        loops = self.list_open_loops(scope, status="open", limit=3)
        if not loops:
            return "没有明确未收事项"
        return "；".join(truncate_text(str(item.get("content") or ""), 80) for item in loops)

    def _sleep_state_label(self, state: str) -> str:
        if state == "asleep":
            return "他刚明确要睡/已睡，主动消息暂停，除非他先醒来或主动回你"
        if state == "awake":
            return "他已醒着，可以正常接话和主动靠近"
        return "未知，不要仅凭时间假设他睡了；用最近消息判断"

    def _local_now(self) -> datetime:
        try:
            return datetime.now(ZoneInfo(self.settings.bot_timezone))
        except Exception:  # noqa: BLE001
            return datetime.now()

    def _state_key(self, scope: ConversationScope) -> str:
        return f"presence_state:{scope.user_id}:{scope.conversation_id}"

    def _open_loop_key(self, scope: ConversationScope) -> str:
        return f"open_loop_state:{scope.user_id}:{scope.conversation_id}"

    def _trigger_state_key(self, scope: ConversationScope) -> str:
        return f"proactive_trigger_state:{scope.user_id}:{scope.conversation_id}"
