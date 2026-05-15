from __future__ import annotations

from src.core.settings import Settings
from src.core.types import ConversationScope
from src.memory.models import MemoryAnalysisResult, MemoryWriteResult
from src.memory.relationship import RelationshipManager
from src.memory.store import MemoryStore
from src.product.store import ProductStore
from src.utils.time_utils import add_minutes, utc_now


class MemoryWriter:
    def __init__(
        self,
        store: MemoryStore,
        settings: Settings,
        relationship_manager: RelationshipManager,
        product_store: ProductStore | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.relationship_manager = relationship_manager
        self.product_store = product_store

    def apply_analysis(self, scope: ConversationScope, analysis: MemoryAnalysisResult) -> MemoryWriteResult:
        result = MemoryWriteResult()

        for candidate in analysis.session_memories:
            if candidate.confidence < 0.35 or not candidate.content:
                continue
            if candidate.memory_type not in {
                "open_loop",
                "study_checkpoint",
                "temporary_emotional_state",
                "care_follow_up",
                "short_term_goal",
                "current_topic",
            }:
                continue
            if len(candidate.content.strip()) < 8:
                continue
            expires_at = None
            if candidate.expires_in_minutes:
                expires_at = add_minutes(utc_now(), candidate.expires_in_minutes).isoformat()
            self.store.add_or_refresh_session_memory(
                scope,
                memory_type=candidate.memory_type,
                content=candidate.content,
                priority=candidate.priority,
                confidence=candidate.confidence,
                source_message_ids=candidate.source_message_ids,
                expires_at=expires_at,
                metadata={**candidate.metadata, "reason": candidate.reason},
            )
            result.session_written += 1

        for candidate in analysis.structured_facts:
            if candidate.confidence < 0.55 or not candidate.key or not candidate.value:
                continue
            self.store.upsert_structured_fact(
                scope.user_id,
                namespace=candidate.namespace,
                key=candidate.key,
                value=candidate.value,
                confidence=candidate.confidence,
                source_message_ids=candidate.source_message_ids,
                metadata={**candidate.metadata, "reason": candidate.reason},
            )
            result.facts_written += 1

        for candidate in analysis.long_term_memories:
            if candidate.confidence < 0.6 or candidate.importance < 0.55 or not candidate.content:
                continue
            if self._should_auto_promote(candidate.memory_type, candidate.importance, candidate.confidence):
                self.store.insert_or_merge_long_term_memory(
                    scope,
                    memory_type=candidate.memory_type,
                    category=candidate.category,
                    content=candidate.content,
                    tags=candidate.tags,
                    confidence=candidate.confidence,
                    importance=candidate.importance,
                    source_message_ids=candidate.source_message_ids,
                    metadata={**candidate.metadata, "reason": candidate.reason},
                )
                result.long_term_written += 1
            elif self.product_store is not None:
                self.product_store.create_candidate_memory(scope, candidate)

        for candidate in analysis.relationship_updates:
            normalized = self.relationship_manager.normalize_candidate(candidate)
            if normalized.confidence < 0.55 or not normalized.value:
                continue
            self.store.upsert_relationship_state(
                scope.user_id,
                dimension=normalized.dimension,
                value=normalized.value,
                weight=normalized.weight,
                confidence=normalized.confidence,
                note=normalized.note,
                source_message_ids=normalized.source_message_ids,
                metadata={**normalized.metadata, "reason": normalized.reason},
            )
            result.relationship_written += 1

        return result

    def _should_auto_promote(
        self,
        memory_type: str,
        importance: float,
        confidence: float,
    ) -> bool:
        if memory_type in {"commitment_record", "care_history", "routine_pattern", "study_context"}:
            return importance >= 0.68 and confidence >= 0.68
        return importance >= 0.82 and confidence >= 0.78
