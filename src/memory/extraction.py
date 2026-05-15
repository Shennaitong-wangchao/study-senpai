from __future__ import annotations

import logging
import re
from typing import Any

from src.core.types import ConversationScope
from src.llm.client import LLMClient
from src.llm.prompts.memory_extraction import (
    MEMORY_EXTRACTION_SYSTEM_PROMPT,
    build_memory_extraction_user_prompt,
)
from src.memory.models import (
    IgnoredSignal,
    LongTermMemoryCandidate,
    MemoryAnalysisResult,
    MessageRecord,
    RelationshipUpdateCandidate,
    SessionMemoryCandidate,
    StructuredFactCandidate,
)
from src.utils.text_utils import compact_text, truncate_text


logger = logging.getLogger(__name__)


class MemoryExtractor:
    SHORT_TERM_FOLLOWUP_RE = re.compile(
        r"(今天|今晚|明天|明晚|后天|这周|本周|下周|这两天|过几天|几天后|待会|等会|回头|到时候).{0,32}"
        r"(提醒|记得|问我|盯|到货|到了|要做|要去|要交|要考|复盘|处理|睡|吃药|别忘)"
    )

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    async def analyze_for_memory(
        self,
        scope: ConversationScope,
        turn_messages: list[MessageRecord],
        current_summary: str | None = None,
    ) -> MemoryAnalysisResult:
        transcript = self._render_transcript(turn_messages)
        try:
            payload = await self.llm_client.json_completion(
                system_prompt=MEMORY_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=build_memory_extraction_user_prompt(transcript, current_summary),
            )
            analysis = self._parse_payload(payload, turn_messages)
            analysis.session_memories = self._filter_session_candidates(analysis.session_memories)
            return analysis
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memory extraction fell back to heuristics for %s: %s", scope.conversation_id, exc)
            return self._heuristic_analysis(turn_messages)

    def _filter_session_candidates(
        self,
        candidates: list[SessionMemoryCandidate],
    ) -> list[SessionMemoryCandidate]:
        allowed_types = {"open_loop", "study_checkpoint", "temporary_emotional_state", "care_follow_up", "short_term_goal"}
        filtered: list[SessionMemoryCandidate] = []
        for candidate in candidates:
            if candidate.memory_type not in allowed_types:
                continue
            if candidate.memory_type == "temporary_emotional_state":
                candidate.expires_in_minutes = min(candidate.expires_in_minutes, 180)
            filtered.append(candidate)
        return filtered

    def _render_transcript(self, messages: list[MessageRecord]) -> str:
        lines = []
        for message in messages:
            lines.append(f"[{message.sender_type.upper()}#{message.id}] {message.content}")
        return "\n".join(lines)

    def _parse_payload(
        self,
        payload: dict[str, Any],
        turn_messages: list[MessageRecord],
    ) -> MemoryAnalysisResult:
        default_source_ids = [message.id for message in turn_messages]

        def _source_ids(item: dict[str, Any]) -> list[int]:
            raw_ids = item.get("source_message_ids") or default_source_ids
            return [int(value) for value in raw_ids]

        session_memories = [
            SessionMemoryCandidate(
                memory_type=str(item.get("memory_type", "current_topic")),
                content=compact_text(str(item.get("content", ""))),
                priority=float(item.get("priority", 0.5)),
                confidence=float(item.get("confidence", 0.5)),
                reason=str(item.get("reason", "")),
                source_message_ids=_source_ids(item),
                expires_in_minutes=int(item.get("expires_in_minutes", 180)),
                metadata=item.get("metadata") or {},
            )
            for item in payload.get("session_memories", [])
            if compact_text(str(item.get("content", "")))
        ]

        long_term_memories = [
            LongTermMemoryCandidate(
                memory_type=str(item.get("memory_type", "personal_fact")),
                category=str(item.get("category", "general")),
                content=compact_text(str(item.get("content", ""))),
                tags=[str(tag) for tag in item.get("tags", []) if str(tag).strip()],
                importance=float(item.get("importance", 0.5)),
                confidence=float(item.get("confidence", 0.5)),
                reason=str(item.get("reason", "")),
                source_message_ids=_source_ids(item),
                metadata=item.get("metadata") or {},
            )
            for item in payload.get("long_term_memories", [])
            if compact_text(str(item.get("content", "")))
        ]

        structured_facts = [
            StructuredFactCandidate(
                namespace=str(item.get("namespace", "context")),
                key=str(item.get("key", "unknown_key")),
                value=compact_text(str(item.get("value", ""))),
                confidence=float(item.get("confidence", 0.5)),
                reason=str(item.get("reason", "")),
                source_message_ids=_source_ids(item),
                metadata=item.get("metadata") or {},
            )
            for item in payload.get("structured_facts", [])
            if compact_text(str(item.get("key", ""))) and compact_text(str(item.get("value", "")))
        ]

        relationship_updates = [
            RelationshipUpdateCandidate(
                dimension=str(item.get("dimension", "trust_signal")),
                value=compact_text(str(item.get("value", ""))),
                weight=float(item.get("weight", 0.5)),
                confidence=float(item.get("confidence", 0.5)),
                note=compact_text(str(item.get("note", ""))) or None,
                reason=str(item.get("reason", "")),
                source_message_ids=_source_ids(item),
                metadata=item.get("metadata") or {},
            )
            for item in payload.get("relationship_updates", [])
            if compact_text(str(item.get("value", "")))
        ]

        ignored_signals = [
            IgnoredSignal(
                reason=str(item.get("reason", "")),
                source_message_ids=[int(value) for value in item.get("source_message_ids", default_source_ids)],
            )
            for item in payload.get("ignored_signals", [])
        ]

        return MemoryAnalysisResult(
            summary_hint=compact_text(str(payload.get("summary_hint", ""))) or None,
            session_memories=session_memories,
            long_term_memories=long_term_memories,
            structured_facts=structured_facts,
            relationship_updates=relationship_updates,
            ignored_signals=ignored_signals,
            extraction_method="llm",
        )

    def _heuristic_analysis(self, turn_messages: list[MessageRecord]) -> MemoryAnalysisResult:
        source_ids = [message.id for message in turn_messages]
        last_user = next((message for message in reversed(turn_messages) if message.sender_type == "user"), None)
        last_assistant = next((message for message in reversed(turn_messages) if message.sender_type == "assistant"), None)
        if last_user is None:
            return MemoryAnalysisResult(
                summary_hint=None,
                session_memories=[],
                long_term_memories=[],
                structured_facts=[],
                relationship_updates=[],
                ignored_signals=[],
                extraction_method="heuristic",
            )

        content = compact_text(last_user.content)
        assistant_content = compact_text(last_assistant.content) if last_assistant else ""
        session_memories = [
            SessionMemoryCandidate(
                memory_type="current_topic",
                content=f"当前话题：{truncate_text(content, 100)}",
                priority=0.65,
                confidence=0.6,
                reason="fallback heuristic current topic",
                source_message_ids=source_ids,
                expires_in_minutes=180,
            )
        ]

        structured_facts: list[StructuredFactCandidate] = []
        long_term_memories: list[LongTermMemoryCandidate] = []
        relationship_updates: list[RelationshipUpdateCandidate] = []
        matched_emotions: list[str] = []

        short_term_followup_match = self.SHORT_TERM_FOLLOWUP_RE.search(content)
        if short_term_followup_match:
            session_memories.append(
                SessionMemoryCandidate(
                    memory_type="open_loop",
                    content=f"短期未收事项：{truncate_text(content, 110)}",
                    priority=0.82,
                    confidence=0.72,
                    reason="heuristic short-term follow-up detection",
                    source_message_ids=source_ids,
                    expires_in_minutes=60 * 36,
                )
            )

        preferred_name_match = re.search(
            r"(?:叫我|称呼我(?:的时候)?叫|你可以叫我|最好叫我|喊我|你就叫我)([\u4e00-\u9fffA-Za-z0-9_]{1,12})",
            content,
        )
        if preferred_name_match:
            structured_facts.append(
                StructuredFactCandidate(
                    namespace="identity",
                    key="preferred_name",
                    value=preferred_name_match.group(1),
                    confidence=0.8,
                    reason="user explicitly stated preferred addressing",
                    source_message_ids=source_ids,
                )
            )

        reminder_preference_match = re.search(
            r"(?:你可以|你就|以后(?:你)?)(?:多)?(?:提醒|督促|监督|管)(?:我)?(.{0,18})",
            content,
        )
        if reminder_preference_match:
            preference_detail = compact_text(reminder_preference_match.group(0))
            structured_facts.append(
                StructuredFactCandidate(
                    namespace="support",
                    key="reminder_preference",
                    value=preference_detail,
                    confidence=0.78,
                    reason="user explicitly described reminder or supervision preference",
                    source_message_ids=source_ids,
                )
            )
            relationship_updates.append(
                RelationshipUpdateCandidate(
                    dimension="guidance_preference",
                    value=preference_detail,
                    weight=0.8,
                    confidence=0.76,
                    note="用户对被提醒、被督促或被管束的接受方式",
                    reason="heuristic guidance preference detection",
                    source_message_ids=source_ids,
                )
            )
            if any(keyword in preference_detail for keyword in ("早点睡", "作息", "睡觉", "休息")):
                long_term_memories.append(
                    LongTermMemoryCandidate(
                        memory_type="routine_pattern",
                        category="sleep_management_need",
                        content=f"用户希望被提醒或督促作息：{preference_detail}",
                        tags=["routine", "sleep", "reminder"],
                        importance=0.8,
                        confidence=0.72,
                        reason="heuristic routine support preference extraction",
                        source_message_ids=source_ids,
                    )
                )

        like_match = re.search(r"(?:我喜欢|我更喜欢|我比较喜欢|我偏爱)(.{1,20})", content)
        if like_match:
            liked = compact_text(like_match.group(1))
            long_term_memories.append(
                LongTermMemoryCandidate(
                    memory_type="user_preference",
                    category="likes",
                    content=f"用户喜欢{liked}",
                    tags=["preference", "likes"],
                    importance=0.72,
                    confidence=0.68,
                    reason="heuristic preference extraction",
                    source_message_ids=source_ids,
                )
            )

        study_keywords = ("学习", "复习", "考试", "刷题", "背书", "作业", "成绩", "高考", "模考", "晚自习")
        if any(keyword in content for keyword in study_keywords):
            long_term_memories.append(
                LongTermMemoryCandidate(
                    memory_type="study_context",
                    category="study_status",
                    content=f"用户当前学习相关状态：{truncate_text(content, 100)}",
                    tags=["study", "learning_state"],
                    importance=0.84,
                    confidence=0.74,
                    reason="heuristic study context extraction",
                    source_message_ids=source_ids,
                )
            )
            if any(token in content for token in ("今天", "今晚", "明天", "这周", "待会", "等会")):
                session_memories.append(
                    SessionMemoryCandidate(
                        memory_type="study_checkpoint",
                        content=f"当前学习节点或短期任务：{truncate_text(content, 90)}",
                        priority=0.8,
                        confidence=0.72,
                        reason="heuristic short-term study checkpoint detection",
                        source_message_ids=source_ids,
                        expires_in_minutes=240,
                    )
                )

        goal_match = re.search(r"(?:目标是|想考上|想上|想去|准备考|打算考|想上岸|目标院校是)(.{1,24})", content)
        if goal_match:
            structured_facts.append(
                StructuredFactCandidate(
                    namespace="study",
                    key="long_term_goal",
                    value=compact_text(goal_match.group(1).strip("，。！？,. ")),
                    confidence=0.8,
                    reason="user stated a study or exam goal",
                    source_message_ids=source_ids,
                )
            )

        routine_match = re.search(r"(熬夜|晚睡|失眠|作息|睡不着|睡得很晚|黑白颠倒|作息乱|经常失眠|总是熬夜)", content)
        if routine_match:
            long_term_memories.append(
                LongTermMemoryCandidate(
                    memory_type="routine_pattern",
                    category="sleep_or_routine_issue",
                    content=f"用户存在作息或睡眠相关问题：{truncate_text(content, 100)}",
                    tags=["routine", "sleep", "schedule"],
                    importance=0.82,
                    confidence=0.74,
                    reason="heuristic routine pattern extraction",
                    source_message_ids=source_ids,
                )
            )
            structured_facts.append(
                StructuredFactCandidate(
                    namespace="routine",
                    key="sleep_or_routine_issue",
                    value=truncate_text(content, 80),
                    confidence=0.7,
                    reason="user described a recurring routine or sleep issue",
                    source_message_ids=source_ids,
                )
            )

        emotional_keywords = ("焦虑", "委屈", "难受", "崩溃", "烦", "低落", "害怕", "慌", "压得喘不过气", "没状态")
        matched_emotions = [keyword for keyword in emotional_keywords if keyword in content]
        if matched_emotions:
            session_memories.append(
                SessionMemoryCandidate(
                    memory_type="temporary_emotional_state",
                    content=f"用户当前情绪状态偏向：{'、'.join(matched_emotions[:3])}",
                    priority=0.88,
                    confidence=0.76,
                    reason="heuristic emotional state detection",
                    source_message_ids=source_ids,
                    expires_in_minutes=180,
                )
            )

        sensitivity_match = re.search(r"(?:我最怕|我很容易|我一(?:被|到).{0,8}就|我特别怕|我受不了)(.{1,24})", content)
        if sensitivity_match:
            long_term_memories.append(
                LongTermMemoryCandidate(
                    memory_type="emotional_context",
                    category="sensitive_point",
                    content=f"用户情绪敏感点或触发因素：{truncate_text(content, 100)}",
                    tags=["emotion", "sensitivity", "trigger"],
                    importance=0.83,
                    confidence=0.73,
                    reason="heuristic emotional sensitivity extraction",
                    source_message_ids=source_ids,
                )
            )

        project_match = re.search(r"(?:我最近在做|我在做|我正在做|我最近一直在搞|我最近在推进|我手上在弄)(.{1,32})", content)
        if project_match:
            project = compact_text(project_match.group(1).strip("，。！？,. "))
            long_term_memories.append(
                LongTermMemoryCandidate(
                    memory_type="project_context",
                    category="active_project",
                    content=f"用户近期在做项目或任务：{project}",
                    tags=["project", "active_context"],
                    importance=0.82,
                    confidence=0.72,
                    reason="heuristic project extraction",
                    source_message_ids=source_ids,
                )
            )

        dislike_match = re.search(r"(?:我不喜欢|我讨厌|我受不了)(.{1,20})", content)
        if dislike_match:
            disliked = compact_text(dislike_match.group(1))
            long_term_memories.append(
                LongTermMemoryCandidate(
                    memory_type="user_preference",
                    category="dislikes",
                    content=f"用户不喜欢{disliked}",
                    tags=["preference", "dislikes"],
                    importance=0.75,
                    confidence=0.7,
                    reason="heuristic dislike extraction",
                    source_message_ids=source_ids,
                )
            )
            if any(keyword in disliked for keyword in ["客服", "官方", "太冷", "机械", "生硬", "敷衍", "语气"]):
                relationship_updates.append(
                    RelationshipUpdateCandidate(
                        dimension="response_style",
                        value=f"用户不喜欢偏客服或过于官方的回复风格：{disliked}",
                        weight=0.82,
                        confidence=0.76,
                        note="后续回复应更自然、更有人味",
                        reason="heuristic response style boundary detection",
                        source_message_ids=source_ids,
                    )
                )
            if any(keyword in disliked for keyword in ["说教", "凶", "逼", "一直追问", "大道理", "安慰"]):
                relationship_updates.append(
                    RelationshipUpdateCandidate(
                        dimension="soothing_style",
                        value=f"用户不喜欢的安抚或督促方式：{disliked}",
                        weight=0.8,
                        confidence=0.75,
                        note="安抚和引导需要更克制、更有分寸",
                        reason="heuristic soothing style boundary detection",
                        source_message_ids=source_ids,
                    )
                )

        if "不要" in content or "别这样" in content or "不想" in content:
            relationship_updates.append(
                RelationshipUpdateCandidate(
                    dimension="boundaries",
                    value=truncate_text(content, 120),
                    weight=0.75,
                    confidence=0.68,
                    note="用户表达了边界或不适",
                    reason="heuristic boundary detection",
                    source_message_ids=source_ids,
                )
            )

        if "客服" in content and ("别太" in content or "不要太" in content or "不像" in content):
            relationship_updates.append(
                RelationshipUpdateCandidate(
                    dimension="response_style",
                    value="用户不喜欢过于客服化、官方化的相处语气",
                    weight=0.82,
                    confidence=0.74,
                    note="保持清冷、克制、自然的人感，不要像客服话术",
                    reason="heuristic colloquial anti-customer-service style detection",
                    source_message_ids=source_ids,
                )
            )

        if assistant_content and re.search(r"(我会记得|我会提醒你|我来提醒你|我帮你看着|晚点我再问你|我记着|我替你盯着)", assistant_content):
            long_term_memories.append(
                LongTermMemoryCandidate(
                    memory_type="commitment_record",
                    category="assistant_commitment",
                    content=f"沈知微答应过用户：{truncate_text(assistant_content, 100)}",
                    tags=["commitment", "follow_up", "care"],
                    importance=0.88,
                    confidence=0.78,
                    reason="heuristic assistant commitment extraction",
                    source_message_ids=source_ids,
                )
            )

        if matched_emotions and assistant_content and re.search(r"(先|慢一点|别急|我在|过来|你先|先休息|先把)", assistant_content):
            long_term_memories.append(
                LongTermMemoryCandidate(
                    memory_type="care_history",
                    category="soothing_or_containment",
                    content=f"沈知微在用户状态不好时的承接方式：{truncate_text(assistant_content, 100)}",
                    tags=["care", "soothing", "containment"],
                    importance=0.72,
                    confidence=0.66,
                    reason="heuristic care history extraction",
                    source_message_ids=source_ids,
                )
            )
            session_memories.append(
                SessionMemoryCandidate(
                    memory_type="care_follow_up",
                    content="这一轮用户需要被接住并慢慢收回节奏。",
                    priority=0.86,
                    confidence=0.74,
                    reason="heuristic care follow-up detection",
                    source_message_ids=source_ids,
                    expires_in_minutes=180,
                )
            )

        return MemoryAnalysisResult(
            summary_hint=truncate_text(content, 140),
            session_memories=session_memories,
            long_term_memories=long_term_memories,
            structured_facts=structured_facts,
            relationship_updates=relationship_updates,
            ignored_signals=[],
            extraction_method="heuristic",
        )
