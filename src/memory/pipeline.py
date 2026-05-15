from __future__ import annotations

import logging
from typing import Any

from src.core.types import ConversationScope, MessageContext
from src.memory.extraction import MemoryExtractor
from src.memory.gating import MemoryGate
from src.memory.models import MemoryAnalysisResult, MessageRecord, RetrievedMemoryContext
from src.memory.retrieval import MemoryRetriever
from src.memory.session_state import SessionStateManager
from src.memory.store import MemoryStore
from src.memory.summarizer import ConversationSummarizer
from src.memory.writer import MemoryWriter


logger = logging.getLogger(__name__)


class MemoryPipeline:
    def __init__(
        self,
        *,
        store: MemoryStore,
        session_manager: SessionStateManager,
        extractor: MemoryExtractor,
        writer: MemoryWriter,
        retriever: MemoryRetriever,
        summarizer: ConversationSummarizer,
        summary_trigger_message_count: int = 16,
    ) -> None:
        self.store = store
        self.session_manager = session_manager
        self.extractor = extractor
        self.writer = writer
        self.retriever = retriever
        self.summarizer = summarizer
        self.gate = MemoryGate(summary_trigger_message_count=summary_trigger_message_count)

    def build_scope(
        self,
        *,
        platform: str,
        user_id: str,
        channel_id: str,
        guild_id: str | None,
    ) -> ConversationScope:
        return self.session_manager.build_scope(
            platform=platform,
            user_id=user_id,
            channel_id=channel_id,
            guild_id=guild_id,
        )

    def ingest_message(
        self,
        scope: ConversationScope,
        *,
        sender_type: str,
        content: str,
        context: MessageContext,
        metadata: dict[str, Any] | None = None,
    ) -> MessageRecord:
        return self.store.insert_message(
            scope,
            sender_type=sender_type,
            content=content,
            context=context,
            metadata=metadata,
        )

    def retrieve_for_reply(
        self,
        scope: ConversationScope,
        *,
        current_user_input: str,
        before_message_id: int,
    ) -> RetrievedMemoryContext:
        return self.retriever.retrieve_for_reply(
            scope,
            current_user_input=current_user_input,
            before_message_id=before_message_id,
        )

    async def process_completed_turn(
        self,
        scope: ConversationScope,
        *,
        turn_messages: list[MessageRecord],
    ) -> MemoryAnalysisResult:
        latest_summary = self.store.get_latest_summary(scope.conversation_id)
        after_message_id = latest_summary.message_end_id if latest_summary else 0
        recent_messages = self.store.list_messages_after(scope.conversation_id, after_message_id)
        gate_decision = self.gate.decide(
            turn_messages=turn_messages,
            recent_messages=recent_messages,
            messages_since_summary=len(recent_messages),
        )

        if gate_decision.should_extract:
            analysis = await self.extractor.analyze_for_memory(
                scope,
                turn_messages=turn_messages,
                current_summary=latest_summary.content if latest_summary else None,
            )
            write_result = self.writer.apply_analysis(scope, analysis)
            logger.info(
                "Memory write result | conversation=%s session=%s method=%s reasons=%s session=%s long_term=%s facts=%s relationship=%s",
                scope.conversation_id,
                scope.session_id,
                analysis.extraction_method,
                ",".join(gate_decision.reasons) or "none",
                write_result.session_written,
                write_result.long_term_written,
                write_result.facts_written,
                write_result.relationship_written,
            )
        else:
            analysis = MemoryAnalysisResult(
                summary_hint=None,
                session_memories=[],
                long_term_memories=[],
                structured_facts=[],
                relationship_updates=[],
                ignored_signals=[],
                extraction_method="gated_skip",
            )
            logger.info(
                "Memory extraction skipped | conversation=%s session=%s messages_since_summary=%s",
                scope.conversation_id,
                scope.session_id,
                len(recent_messages),
            )

        if gate_decision.should_refresh_summary:
            await self.summarizer.maybe_refresh_summary(scope, force=True)
        return analysis
