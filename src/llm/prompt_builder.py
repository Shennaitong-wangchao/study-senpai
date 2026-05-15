from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

from src.core.types import ConversationScope
from src.llm.prompts.persona import build_persona_system_prompt
from src.memory.models import (
    ConversationSummaryRecord,
    LongTermMemoryRecord,
    RelationshipStateRecord,
    RetrievedMemoryContext,
    SessionMemoryRecord,
    StructuredFactRecord,
)
from src.persona.profile import PersonaProfile
from src.persona.style_calibration import (
    ReplyStyleCalibration,
    render_anti_generic_guard,
    render_style_calibration,
)
from src.utils.text_utils import compact_text, overlap_score, truncate_text


@dataclass
class PromptBuildResult:
    messages: list[dict[str, str]]
    system_context: str
    usage: "PromptUsageMetadata"


@dataclass
class PromptUsageMetadata:
    structured_fact_keys: list[str] = field(default_factory=list)
    relationship_dimensions: list[str] = field(default_factory=list)
    long_term_memory_uids: list[str] = field(default_factory=list)
    session_memory_ids: list[int] = field(default_factory=list)
    summary_included: bool = False
    summary_version: int | None = None
    recent_message_ids: list[int] = field(default_factory=list)
    extra_context_blocks_used: int = 0
    prompt_char_count: int = 0
    estimated_input_tokens: int = 0


T = TypeVar("T")


@dataclass(frozen=True)
class PromptBudget:
    system_char_budget: int
    history_char_budget: int
    history_message_limit: int
    recent_message_char_limit: int
    final_user_char_limit: int
    strategy_note_char_limit: int
    user_note_char_limit: int
    extra_context_char_budget: int
    fact_limit: int
    relationship_limit: int
    commitment_limit: int
    care_limit: int
    ongoing_limit: int
    session_limit: int
    summary_limit: int
    fact_line_char_limit: int
    relationship_line_char_limit: int
    memory_line_char_limit: int
    session_line_char_limit: int
    summary_line_char_limit: int
    persona_section_char_limit: int
    style_section_char_limit: int
    guard_section_char_limit: int
    strategy_section_char_limit: int
    stable_ground_section_char_limit: int
    commitment_section_char_limit: int
    turn_focus_section_char_limit: int
    extra_context_section_char_limit: int
    memory_note_section_char_limit: int


class PromptBuilder:
    FACT_NAMESPACE_BASE = {
        "identity": 1.0,
        "boundaries": 1.05,
        "support": 0.98,
        "study": 0.9,
        "routine": 0.88,
        "projects": 0.66,
        "preferences": 0.6,
        "relationship": 0.82,
        "context": 0.55,
    }

    RELATIONSHIP_BASE = {
        "boundaries": 1.05,
        "response_style": 1.0,
        "guidance_preference": 0.96,
        "soothing_style": 0.94,
        "addressing_style": 0.82,
        "care_expectation": 0.78,
        "comfort_level": 0.7,
        "interaction_rhythm": 0.66,
        "trust_signal": 0.62,
    }

    LONG_TERM_BASE = {
        "commitment_record": 1.18,
        "care_history": 1.06,
        "support_preference": 1.02,
        "study_context": 0.94,
        "routine_pattern": 0.9,
        "emotional_context": 0.94,
        "project_context": 0.74,
        "relationship_signal": 0.76,
        "stable_instruction": 0.82,
        "user_preference": 0.62,
        "personal_fact": 0.58,
        "recurring_pattern": 0.66,
    }
    STANDARD_BUDGET = PromptBudget(
        system_char_budget=3800,
        history_char_budget=1800,
        history_message_limit=6,
        recent_message_char_limit=280,
        final_user_char_limit=1800,
        strategy_note_char_limit=220,
        user_note_char_limit=220,
        extra_context_char_budget=500,
        fact_limit=3,
        relationship_limit=3,
        commitment_limit=2,
        care_limit=1,
        ongoing_limit=2,
        session_limit=2,
        summary_limit=1,
        fact_line_char_limit=72,
        relationship_line_char_limit=72,
        memory_line_char_limit=84,
        session_line_char_limit=58,
        summary_line_char_limit=90,
        persona_section_char_limit=1350,
        style_section_char_limit=320,
        guard_section_char_limit=170,
        strategy_section_char_limit=220,
        stable_ground_section_char_limit=380,
        commitment_section_char_limit=360,
        turn_focus_section_char_limit=240,
        extra_context_section_char_limit=500,
        memory_note_section_char_limit=180,
    )
    COMPACT_BUDGET = PromptBudget(
        system_char_budget=2500,
        history_char_budget=900,
        history_message_limit=4,
        recent_message_char_limit=180,
        final_user_char_limit=1000,
        strategy_note_char_limit=140,
        user_note_char_limit=140,
        extra_context_char_budget=260,
        fact_limit=2,
        relationship_limit=2,
        commitment_limit=1,
        care_limit=1,
        ongoing_limit=1,
        session_limit=2,
        summary_limit=1,
        fact_line_char_limit=56,
        relationship_line_char_limit=56,
        memory_line_char_limit=64,
        session_line_char_limit=48,
        summary_line_char_limit=68,
        persona_section_char_limit=980,
        style_section_char_limit=180,
        guard_section_char_limit=110,
        strategy_section_char_limit=140,
        stable_ground_section_char_limit=240,
        commitment_section_char_limit=220,
        turn_focus_section_char_limit=180,
        extra_context_section_char_limit=260,
        memory_note_section_char_limit=120,
    )

    def __init__(self, persona_profile: PersonaProfile) -> None:
        self.persona_profile = persona_profile

    def build_messages(
        self,
        *,
        scope: ConversationScope,
        memory_context: RetrievedMemoryContext,
        current_user_input: str,
        style_calibration: ReplyStyleCalibration,
        strategy_note: str | None = None,
        user_note: str | None = None,
        extra_context_blocks: list[str] | None = None,
        compact: bool = False,
    ) -> PromptBuildResult:
        budget = self.COMPACT_BUDGET if compact else self.STANDARD_BUDGET
        seen_signatures: list[str] = []
        stable_ground, selected_fact_keys, relationship_dimensions = self._format_stable_ground(
            memory_context,
            style_calibration,
            seen_signatures,
            budget,
        )
        commitment_bridge, selected_long_term_memory_uids = self._format_commitment_bridge(
            memory_context,
            style_calibration,
            seen_signatures,
            budget,
        )
        turn_focus, selected_session_memory_ids, summary_included = self._format_turn_focus(
            memory_context,
            style_calibration,
            seen_signatures,
            budget,
        )
        extra_context, extra_context_blocks_used = self._render_extra_context(extra_context_blocks or [], budget)

        system_sections: list[tuple[str, str, int]] = [
            ("System Prompt", build_persona_system_prompt(self.persona_profile), budget.persona_section_char_limit),
            ("Turn Calibration", render_style_calibration(style_calibration), budget.style_section_char_limit),
            ("Anti-Generic Guard", render_anti_generic_guard(style_calibration), budget.guard_section_char_limit),
            ("Reply Strategy", strategy_note or "", budget.strategy_section_char_limit),
            ("What You Already Know", stable_ground, budget.stable_ground_section_char_limit),
            ("What You Are Already Holding", commitment_bridge, budget.commitment_section_char_limit),
            ("What Still Matters Now", turn_focus, budget.turn_focus_section_char_limit),
            ("This Turn Extra Context", extra_context, budget.extra_context_section_char_limit),
            (
                "Memory Use Note",
                (
                    "把这些信息当成你心里一直有数的依据，不要逐条复述。"
                    "它们是你开口时的底气、分寸和偏心，不是你要念给他听的记录。"
                    "\n\n【重要】如果记忆里没有某个信息，就不要假装记得或编造细节。"
                    "只使用确实存在的记忆，不要虚构用户的名字、经历、项目或任何个人信息。"
                ),
                budget.memory_note_section_char_limit,
            ),
            ("Current Scope", f"conversation_id={scope.conversation_id}\nsession_id={scope.session_id}", 96),
        ]

        system_context = self._compose_system_context(system_sections, budget)

        messages: list[dict[str, str]] = [{"role": "system", "content": system_context}]
        recent_messages, selected_recent_message_ids = self._select_recent_messages(memory_context.recent_messages, budget)
        messages.extend(recent_messages)
        user_content = truncate_text(current_user_input, budget.final_user_char_limit)
        if user_note:
            user_content = (
                f"{user_content}\n\n[这一轮回复提示]\n"
                f"{truncate_text(user_note, budget.user_note_char_limit)}"
            )
        messages.append({"role": "user", "content": user_content})
        usage = PromptUsageMetadata(
            structured_fact_keys=selected_fact_keys,
            relationship_dimensions=relationship_dimensions,
            long_term_memory_uids=selected_long_term_memory_uids,
            session_memory_ids=selected_session_memory_ids,
            summary_included=summary_included,
            summary_version=memory_context.summary.version if memory_context.summary and summary_included else None,
            recent_message_ids=selected_recent_message_ids,
            extra_context_blocks_used=extra_context_blocks_used,
        )
        usage.prompt_char_count = sum(len(message["content"]) for message in messages)
        usage.estimated_input_tokens = self._estimate_tokens(usage.prompt_char_count)
        return PromptBuildResult(messages=messages, system_context=system_context, usage=usage)

    def _format_stable_ground(
        self,
        memory_context: RetrievedMemoryContext,
        calibration: ReplyStyleCalibration,
        seen_signatures: list[str],
        budget: PromptBudget,
    ) -> tuple[str, list[str], list[str]]:
        fact_entries = self._select_fact_briefs(
            memory_context.structured_facts,
            calibration,
            seen_signatures,
            limit=budget.fact_limit,
            line_limit=budget.fact_line_char_limit,
        )
        relationship_entries = self._select_relationship_briefs(
            memory_context.relationship_states,
            calibration,
            seen_signatures,
            limit=budget.relationship_limit,
            line_limit=budget.relationship_line_char_limit,
        )
        fact_lines = [line for line, _ in fact_entries]
        relationship_lines = [line for line, _ in relationship_entries]

        blocks = []
        if fact_lines:
            blocks.append("你对他的稳定把握：")
            blocks.extend(f"- {line}" for line in fact_lines)
        if relationship_lines:
            blocks.append("你们相处时要守住的手感：")
            blocks.extend(f"- {line}" for line in relationship_lines)
        return (
            "\n".join(blocks) if blocks else "无特别补充。",
            [f"{record.namespace}:{record.key}" for _, record in fact_entries],
            [record.dimension for _, record in relationship_entries],
        )

    def _format_commitment_bridge(
        self,
        memory_context: RetrievedMemoryContext,
        calibration: ReplyStyleCalibration,
        seen_signatures: list[str],
        budget: PromptBudget,
    ) -> tuple[str, list[str]]:
        scored_memories = sorted(
            memory_context.long_term_memories,
            key=lambda memory: self._score_long_term_memory(memory, calibration),
            reverse=True,
        )

        commitment_entries: list[tuple[str, str]] = []
        care_entries: list[tuple[str, str]] = []
        ongoing_entries: list[tuple[str, str]] = []
        for memory in scored_memories:
            brief = self._memory_to_brief(memory)
            if not brief or self._is_redundant(brief, seen_signatures):
                continue
            self._remember_signature(brief, seen_signatures)
            if memory.memory_type == "commitment_record":
                commitment_entries.append((brief, memory.memory_uid))
            elif memory.memory_type in {"care_history", "support_preference", "emotional_context"}:
                care_entries.append((brief, memory.memory_uid))
            else:
                ongoing_entries.append((brief, memory.memory_uid))

        blocks = []
        if commitment_entries:
            blocks.append("你已经接下来的事：")
            blocks.extend(f"- {line}" for line, _ in commitment_entries[: budget.commitment_limit])
        if care_entries:
            blocks.append("你照顾他时要更准的地方：")
            blocks.extend(f"- {line}" for line, _ in care_entries[: budget.care_limit])
        if ongoing_entries:
            blocks.append("你还在长期看着的点：")
            blocks.extend(f"- {line}" for line, _ in ongoing_entries[: budget.ongoing_limit])
        selected_uids = [memory_uid for _, memory_uid in commitment_entries[: budget.commitment_limit]]
        selected_uids.extend(memory_uid for _, memory_uid in care_entries[: budget.care_limit])
        selected_uids.extend(memory_uid for _, memory_uid in ongoing_entries[: budget.ongoing_limit])
        return "\n".join(blocks) if blocks else "目前没有额外的承诺或长期盯点。", selected_uids

    def _format_turn_focus(
        self,
        memory_context: RetrievedMemoryContext,
        calibration: ReplyStyleCalibration,
        seen_signatures: list[str],
        budget: PromptBudget,
    ) -> tuple[str, list[int], bool]:
        session_entries = self._select_session_briefs(
            memory_context.session_memories,
            calibration,
            seen_signatures,
            limit=budget.session_limit,
            line_limit=budget.session_line_char_limit,
        )
        session_lines = [line for line, _ in session_entries]
        summary_lines = self._select_summary_lines(
            memory_context.summary,
            calibration,
            seen_signatures,
            limit=budget.summary_limit,
            session_lines=session_lines,
            line_limit=budget.summary_line_char_limit,
        )

        blocks = []
        if session_lines:
            blocks.append("这一轮最该先顾的：")
            blocks.extend(f"- {line}" for line in session_lines)
        if summary_lines:
            blocks.append("长线里还不能松开的：")
            blocks.extend(f"- {line}" for line in summary_lines)
        return (
            "\n".join(blocks) if blocks else "按当前消息判断，不必额外展开历史。",
            [record.id for _, record in session_entries],
            bool(summary_lines),
        )

    def _select_fact_briefs(
        self,
        facts: list[StructuredFactRecord],
        calibration: ReplyStyleCalibration,
        seen_signatures: list[str],
        *,
        limit: int,
        line_limit: int,
    ) -> list[tuple[str, StructuredFactRecord]]:
        candidates: list[tuple[float, str, StructuredFactRecord]] = []
        for fact in facts:
            brief = self._fact_to_brief(fact)
            if not brief:
                continue
            candidates.append((self._score_fact(fact, calibration), brief, fact))

        return self._take_unique_entries(candidates, seen_signatures, limit, line_limit=line_limit)

    def _select_relationship_briefs(
        self,
        states: list[RelationshipStateRecord],
        calibration: ReplyStyleCalibration,
        seen_signatures: list[str],
        *,
        limit: int,
        line_limit: int,
    ) -> list[tuple[str, RelationshipStateRecord]]:
        candidates: list[tuple[float, str, RelationshipStateRecord]] = []
        for state in states:
            brief = self._relationship_to_brief(state)
            if not brief:
                continue
            candidates.append((self._score_relationship(state, calibration), brief, state))

        return self._take_unique_entries(candidates, seen_signatures, limit, line_limit=line_limit)

    def _select_session_briefs(
        self,
        session_memories: list[SessionMemoryRecord],
        calibration: ReplyStyleCalibration,
        seen_signatures: list[str],
        *,
        limit: int,
        line_limit: int,
    ) -> list[tuple[str, SessionMemoryRecord]]:
        has_specific_focus = any(
            memory.memory_type in {"care_follow_up", "temporary_emotional_state", "study_checkpoint", "open_loop"}
            for memory in session_memories
        )
        candidates: list[tuple[float, str, SessionMemoryRecord]] = []
        for memory in session_memories:
            if memory.memory_type == "current_topic" and has_specific_focus:
                continue
            brief = self._session_to_brief(memory)
            if not brief:
                continue
            score = memory.priority + memory.confidence
            if memory.memory_type in {"care_follow_up", "temporary_emotional_state"}:
                score += calibration.soothing_priority * 0.7
            if memory.memory_type == "study_checkpoint":
                score += calibration.guidance_priority * 0.65
            if memory.memory_type == "open_loop":
                score += calibration.steadiness_priority * 0.35
            candidates.append((score, brief, memory))

        return self._take_unique_entries(candidates, seen_signatures, limit, line_limit=line_limit)

    def _select_summary_lines(
        self,
        summary: ConversationSummaryRecord | None,
        calibration: ReplyStyleCalibration,
        seen_signatures: list[str],
        *,
        limit: int,
        session_lines: list[str] | None = None,
        line_limit: int,
    ) -> list[str]:
        if summary is None or summary.message_count < 6:
            return []

        parsed_lines = self._parse_summary_lines(summary.content, line_limit=line_limit)
        if len(parsed_lines) < 2:
            return []

        session_lines = session_lines or []
        candidates: list[tuple[float, str]] = []
        for line in parsed_lines:
            if session_lines and max((overlap_score(line, session_line) for session_line in session_lines), default=0.0) >= 0.58:
                continue
            score = self._score_summary_line(line, calibration)
            if session_lines:
                score -= 0.08
            candidates.append((score, line))

        return self._take_unique_lines(candidates, seen_signatures, limit, line_limit=line_limit)

    def _fact_to_brief(self, fact: StructuredFactRecord) -> str | None:
        if fact.namespace == "identity" and fact.key == "preferred_name":
            return f"默认更适合叫他{fact.value}。"
        if fact.namespace == "study" and fact.key == "long_term_goal":
            return f"长线目标还压在{fact.value}那边。"
        if fact.namespace == "support" and fact.key == "reminder_preference":
            return f"他更吃这种提醒或看着的力度：{truncate_text(fact.value, 80)}"
        if fact.namespace == "routine":
            return f"作息是会把他带偏的点：{truncate_text(fact.value, 80)}"
        if fact.namespace == "boundaries":
            return f"别碰的方式：{truncate_text(fact.value, 80)}"
        if fact.namespace == "projects":
            return f"他最近一直在推进：{truncate_text(fact.value, 80)}"
        if fact.namespace == "preferences":
            return f"稳定偏好：{truncate_text(fact.value, 80)}"
        if fact.namespace == "relationship":
            return f"关系上的稳定偏好：{truncate_text(fact.value, 80)}"
        if fact.namespace == "context":
            return truncate_text(fact.value, 90)
        return None

    def _relationship_to_brief(self, state: RelationshipStateRecord) -> str | None:
        if state.dimension == "boundaries":
            return f"先守边界，再靠近：{truncate_text(state.value, 90)}"
        if state.dimension == "response_style":
            return f"说话别滑向官方或客服：{truncate_text(state.value, 90)}"
        if state.dimension == "guidance_preference":
            return f"他接受你这样提醒或带节奏：{truncate_text(state.value, 90)}"
        if state.dimension == "soothing_style":
            return f"安抚时要避开的方式：{truncate_text(state.value, 90)}"
        if state.dimension == "addressing_style":
            return f"称呼和靠近方式：{truncate_text(state.value, 90)}"
        if state.dimension == "care_expectation":
            return f"他默认你会这样看着他：{truncate_text(state.value, 90)}"
        if state.dimension == "trust_signal":
            return f"相处温度：{truncate_text(state.value, 90)}"
        return None

    def _memory_to_brief(self, memory: LongTermMemoryRecord) -> str | None:
        content = self._strip_memory_prefix(memory.content)
        content = truncate_text(content, 110)
        if memory.memory_type == "commitment_record":
            return f"你答应过：{content}"
        if memory.memory_type == "care_history":
            return f"你上次是这样把他接回来的：{content}"
        if memory.memory_type == "study_context":
            return f"学习状态还要继续看着：{content}"
        if memory.memory_type == "routine_pattern":
            return f"作息这一块还不能松：{content}"
        if memory.memory_type == "emotional_context":
            return f"情绪上最容易卡住的地方：{content}"
        if memory.memory_type == "project_context":
            return f"最近反复挂在心上的事：{content}"
        if memory.memory_type == "support_preference":
            return f"更适合的照顾方式：{content}"
        if memory.memory_type == "relationship_signal":
            return f"关系里的稳定信号：{content}"
        if memory.memory_type == "stable_instruction":
            return f"稳定要求：{content}"
        if memory.memory_type == "user_preference":
            return content
        return content

    def _session_to_brief(self, memory: SessionMemoryRecord) -> str | None:
        if memory.memory_type == "care_follow_up":
            return "这一轮先把人接稳，再慢慢收节奏。"
        if memory.memory_type == "temporary_emotional_state":
            return truncate_text(memory.content, 72)
        if memory.memory_type == "study_checkpoint":
            return truncate_text(memory.content, 72)
        if memory.memory_type == "short_term_goal":
            return f"这轮顺手往前接一下：{truncate_text(memory.content, 72)}"
        if memory.memory_type == "open_loop":
            return f"还有没收完的话头：{truncate_text(memory.content, 72)}"
        if memory.memory_type == "current_topic":
            return truncate_text(memory.content, 72)
        return truncate_text(memory.content, 72)

    def _parse_summary_lines(self, content: str, *, line_limit: int) -> list[str]:
        lines = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.endswith("：") and len(line) <= 16:
                continue
            if line.startswith("- "):
                line = line[2:].strip()
            if line:
                lines.append(truncate_text(line, line_limit))
        return lines

    def _score_fact(self, fact: StructuredFactRecord, calibration: ReplyStyleCalibration) -> float:
        score = self.FACT_NAMESPACE_BASE.get(fact.namespace, 0.45) + fact.confidence * 0.25
        if fact.namespace == "support":
            score += calibration.guidance_priority * 0.34 + calibration.soothing_priority * 0.22
        if fact.namespace == "study":
            score += calibration.guidance_priority * 0.34
        if fact.namespace == "routine":
            score += calibration.guidance_priority * 0.28
        if fact.namespace == "boundaries":
            score += 0.25
        return score

    def _score_relationship(self, state: RelationshipStateRecord, calibration: ReplyStyleCalibration) -> float:
        score = self.RELATIONSHIP_BASE.get(state.dimension, 0.45) + state.weight * 0.2
        if state.dimension == "guidance_preference":
            score += calibration.guidance_priority * 0.3
        if state.dimension == "soothing_style":
            score += calibration.soothing_priority * 0.3
        if state.dimension == "response_style":
            score += 0.18
        if state.dimension == "boundaries":
            score += 0.22
        return score

    def _score_long_term_memory(self, memory: LongTermMemoryRecord, calibration: ReplyStyleCalibration) -> float:
        score = self.LONG_TERM_BASE.get(memory.memory_type, 0.48) + memory.importance * 0.22 + memory.confidence * 0.16
        if memory.memory_type in {"commitment_record", "care_history"}:
            score += calibration.bias_level * 0.16
        if memory.memory_type in {"care_history", "emotional_context", "support_preference"}:
            score += calibration.soothing_priority * 0.32
        if memory.memory_type in {"study_context", "routine_pattern", "support_preference", "commitment_record"}:
            score += calibration.guidance_priority * 0.3
        if memory.memory_type == "project_context":
            score += calibration.steadiness_priority * 0.1
        return score

    def _score_summary_line(self, line: str, calibration: ReplyStyleCalibration) -> float:
        score = 0.35
        if any(token in line for token in ("卡住", "敏感", "委屈", "焦虑", "不稳", "接住", "收回来")):
            score += calibration.soothing_priority * 0.5
        if any(token in line for token in ("提醒", "作息", "学习", "目标", "推进", "盯", "未完")):
            score += calibration.guidance_priority * 0.45
        if any(token in line for token in ("答应", "接手", "继续", "下次", "还没收完")):
            score += 0.24
        if any(token in line for token in ("不喜欢", "别", "边界")):
            score += 0.18
        return score

    def _take_unique_entries(
        self,
        candidates: list[tuple[float, str, T]],
        seen_signatures: list[str],
        limit: int,
        *,
        line_limit: int,
    ) -> list[tuple[str, T]]:
        chosen: list[tuple[str, T]] = []
        for _, line, record in sorted(candidates, key=lambda item: item[0], reverse=True):
            line = truncate_text(line, line_limit)
            if self._is_redundant(line, seen_signatures):
                continue
            self._remember_signature(line, seen_signatures)
            chosen.append((line, record))
            if len(chosen) >= limit:
                break
        return chosen

    def _take_unique_lines(
        self,
        candidates: list[tuple[float, str]],
        seen_signatures: list[str],
        limit: int,
        *,
        line_limit: int,
    ) -> list[str]:
        chosen: list[str] = []
        for _, line in sorted(candidates, key=lambda item: item[0], reverse=True):
            line = truncate_text(line, line_limit)
            if self._is_redundant(line, seen_signatures):
                continue
            self._remember_signature(line, seen_signatures)
            chosen.append(line)
            if len(chosen) >= limit:
                break
        return chosen

    def _compose_system_context(
        self,
        system_sections: list[tuple[str, str, int]],
        budget: PromptBudget,
    ) -> str:
        rendered: list[str] = []
        for title, content, section_limit in system_sections:
            normalized = compact_text(content)
            if not normalized:
                continue
            rendered.append(f"[{title}]\n{truncate_text(normalized, section_limit)}")
        system_context = "\n\n".join(rendered)
        return truncate_text(system_context, budget.system_char_budget)

    def _render_extra_context(self, blocks: list[str], budget: PromptBudget) -> str:
        rendered_blocks: list[str] = []
        consumed = 0
        used = 0
        for block in blocks:
            normalized = compact_text(block)
            if not normalized:
                continue
            remaining = budget.extra_context_char_budget - consumed
            if remaining <= 0:
                break
            clipped = truncate_text(normalized, remaining)
            rendered_blocks.append(clipped)
            consumed += len(clipped)
            used += 1
        return "\n\n".join(rendered_blocks), used

    def _select_recent_messages(
        self,
        recent_messages,
        budget: PromptBudget,
    ) -> tuple[list[dict[str, str]], list[int]]:
        selected: list[dict[str, str]] = []
        selected_ids: list[int] = []
        remaining = budget.history_char_budget
        for message in reversed(recent_messages):
            if len(selected) >= budget.history_message_limit:
                break
            content = truncate_text(message.content, budget.recent_message_char_limit)
            if selected and len(content) > remaining:
                break
            role = "assistant" if message.sender_type == "assistant" else "user"
            selected.append({"role": role, "content": content})
            selected_ids.append(int(message.id))
            remaining -= len(content)
            if remaining <= 0:
                break
        return list(reversed(selected)), list(reversed(selected_ids))

    def _estimate_tokens(self, char_count: int) -> int:
        if char_count <= 0:
            return 0
        return max((char_count + 3) // 4, 1)

    def _strip_memory_prefix(self, content: str) -> str:
        replacements = {
            "沈知微答应过用户：": "",
            "沈知微在用户状态不好时的承接方式：": "",
            "用户当前学习相关状态：": "",
            "用户存在作息或睡眠相关问题：": "",
            "用户情绪敏感点或触发因素：": "",
            "用户近期在做项目或任务：": "",
            "用户希望被提醒或督促作息：": "",
        }
        for prefix, replacement in replacements.items():
            if content.startswith(prefix):
                return replacement + content[len(prefix) :]
        return content

    def _is_redundant(self, line: str, seen_signatures: list[str]) -> bool:
        signature = compact_text(line)
        if not signature:
            return True
        return any(overlap_score(signature, seen) >= 0.72 for seen in seen_signatures)

    def _remember_signature(self, line: str, seen_signatures: list[str]) -> None:
        signature = compact_text(line)
        if signature:
            seen_signatures.append(signature)
