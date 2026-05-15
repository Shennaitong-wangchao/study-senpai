from __future__ import annotations

from src.core.settings import Settings
from src.core.types import ConversationScope
from src.memory.models import (
    ConversationSummaryRecord,
    LongTermMemoryRecord,
    RelationshipStateRecord,
    RetrievedMemoryContext,
    SessionMemoryRecord,
    StructuredFactRecord,
)
from src.memory.store import MemoryStore
from src.utils.text_utils import overlap_score
from src.utils.time_utils import parse_iso8601, utc_now


class MemoryRetriever:
    MEMORY_TYPE_BOOSTS = {
        "commitment_record": 0.55,
        "support_preference": 0.5,
        "study_context": 0.45,
        "routine_pattern": 0.4,
        "project_context": 0.36,
        "emotional_context": 0.34,
        "relationship_signal": 0.32,
        "care_history": 0.3,
        "stable_instruction": 0.28,
    }
    EMOTIONAL_TOKENS = ("焦虑", "委屈", "难受", "崩溃", "烦", "低落", "害怕", "慌", "没状态", "撑不住")
    STUDY_TOKENS = ("学习", "复习", "考试", "刷题", "成绩", "高考", "模考", "作业")
    ROUTINE_TOKENS = ("作息", "熬夜", "晚睡", "失眠", "睡不着", "休息")

    def __init__(self, store: MemoryStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    def retrieve_for_reply(
        self,
        scope: ConversationScope,
        *,
        current_user_input: str,
        before_message_id: int,
    ) -> RetrievedMemoryContext:
        recent_limit = max(self.settings.history_message_limit, self.settings.recent_turn_window * 2)
        recent_messages = self.store.list_recent_messages(
            scope.conversation_id,
            limit=recent_limit,
            before_message_id=before_message_id,
        )
        session_memories = self.store.list_active_session_memories(
            scope,
            limit=self.settings.session_memory_limit,
        )
        if not session_memories:
            session_memories = self.store.list_recent_active_session_memories_for_conversation(
                scope.conversation_id,
                limit=self.settings.session_memory_limit,
            )
        structured_facts = self._rank_structured_facts(
            self.store.list_structured_facts(
                scope.user_id,
                limit=self.settings.fact_limit,
            ),
            current_user_input=current_user_input,
        )
        relationship_states = self._rank_relationship_states(
            self.store.list_relationship_states(scope.user_id),
            current_user_input=current_user_input,
        )
        summary = self.store.get_latest_summary(scope.conversation_id)
        long_term_memories = self._rank_long_term_memories(
            current_user_input=current_user_input,
            memories=self.store.list_active_long_term_memories(scope.user_id),
            structured_facts=structured_facts,
            relationship_states=relationship_states,
            session_memories=session_memories,
            summary=summary,
        )

        return RetrievedMemoryContext(
            recent_messages=recent_messages,
            session_memories=session_memories,
            long_term_memories=long_term_memories,
            structured_facts=structured_facts,
            relationship_states=relationship_states,
            summary=summary,
        )

    def _rank_structured_facts(
        self,
        facts: list[StructuredFactRecord],
        *,
        current_user_input: str,
    ) -> list[StructuredFactRecord]:
        scored: list[tuple[float, StructuredFactRecord]] = []
        for fact in facts:
            text = f"{fact.namespace} {fact.key} {fact.value}"
            score = fact.confidence * 0.65 + overlap_score(current_user_input, text) * 0.7
            if fact.namespace in {"support", "boundaries", "study", "routine", "identity"}:
                score += 0.28
            scored.append((score, fact))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [fact for _, fact in scored[: self.settings.fact_limit]]

    def _rank_relationship_states(
        self,
        states: list[RelationshipStateRecord],
        *,
        current_user_input: str,
    ) -> list[RelationshipStateRecord]:
        scored: list[tuple[float, RelationshipStateRecord]] = []
        for state in states:
            text_score = overlap_score(current_user_input, state.value)
            score = state.weight * 0.55 + state.confidence * 0.35 + text_score * 0.65
            if state.dimension in {"boundaries", "response_style", "guidance_preference", "soothing_style"}:
                score += 0.3
            scored.append((score, state))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [state for _, state in scored[:8]]

    def _rank_long_term_memories(
        self,
        *,
        current_user_input: str,
        memories: list[LongTermMemoryRecord],
        structured_facts: list[StructuredFactRecord],
        relationship_states: list[RelationshipStateRecord],
        session_memories: list[SessionMemoryRecord],
        summary: ConversationSummaryRecord | None,
    ) -> list[LongTermMemoryRecord]:
        scored: list[tuple[float, LongTermMemoryRecord]] = []
        emotional_turn = any(token in current_user_input for token in self.EMOTIONAL_TOKENS)
        study_turn = any(token in current_user_input for token in self.STUDY_TOKENS)
        routine_turn = any(token in current_user_input for token in self.ROUTINE_TOKENS)
        reference_texts = self._build_reference_texts(structured_facts, relationship_states, session_memories, summary)

        for memory in memories:
            text_score = overlap_score(current_user_input, memory.content)
            tag_score = max((overlap_score(current_user_input, tag) for tag in memory.tags), default=0.0)
            type_boost = self.MEMORY_TYPE_BOOSTS.get(memory.memory_type, 0.0)
            contextual_boost = 0.0
            if emotional_turn and memory.memory_type in {"emotional_context", "care_history", "support_preference", "commitment_record"}:
                contextual_boost += 0.28
            if study_turn and memory.memory_type in {"study_context", "commitment_record", "support_preference"}:
                contextual_boost += 0.24
            if routine_turn and memory.memory_type in {"routine_pattern", "commitment_record", "support_preference"}:
                contextual_boost += 0.22
            redundancy_penalty = self._redundancy_penalty(memory, reference_texts)
            recency_boost = self._recency_boost(memory.updated_at)
            score = (
                text_score * 1.25
                + tag_score * 0.75
                + memory.importance * 0.9
                + memory.confidence * 0.65
                + type_boost
                + contextual_boost
                + recency_boost
                - redundancy_penalty
            )
            scored.append((score, memory))

        scored.sort(key=lambda item: item[0], reverse=True)
        return self._prune_redundant_memories([memory for _, memory in scored], reference_texts)

    def _recency_boost(self, updated_at: str) -> float:
        parsed = parse_iso8601(updated_at)
        if parsed is None:
            return 0.0
        age_hours = (utc_now() - parsed).total_seconds() / 3600
        if age_hours <= 24:
            return 0.45
        if age_hours <= 72:
            return 0.3
        if age_hours <= 24 * 7:
            return 0.16
        return 0.0

    def _build_reference_texts(
        self,
        structured_facts: list[StructuredFactRecord],
        relationship_states: list[RelationshipStateRecord],
        session_memories: list[SessionMemoryRecord],
        summary: ConversationSummaryRecord | None,
    ) -> list[str]:
        references = [fact.value for fact in structured_facts]
        references.extend(state.value for state in relationship_states)
        references.extend(memory.content for memory in session_memories)
        if summary:
            references.append(summary.content)
        return references

    def _redundancy_penalty(
        self,
        memory: LongTermMemoryRecord,
        reference_texts: list[str],
    ) -> float:
        if memory.memory_type in {"commitment_record", "care_history"}:
            return 0.0
        overlap = max((overlap_score(memory.content, text) for text in reference_texts), default=0.0)
        if overlap < 0.42:
            return 0.0
        return overlap * 0.6

    def _prune_redundant_memories(
        self,
        memories: list[LongTermMemoryRecord],
        reference_texts: list[str],
    ) -> list[LongTermMemoryRecord]:
        selected: list[LongTermMemoryRecord] = []
        seen_texts = list(reference_texts)
        for memory in memories:
            if len(selected) >= self.settings.long_term_memory_limit:
                break
            if memory.memory_type not in {"commitment_record", "care_history"}:
                if max((overlap_score(memory.content, text) for text in seen_texts), default=0.0) >= 0.72:
                    continue
            selected.append(memory)
            seen_texts.append(memory.content)
        return selected
