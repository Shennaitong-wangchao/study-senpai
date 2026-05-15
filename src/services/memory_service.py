from __future__ import annotations

from src.core.types import ConversationScope, MessageContext
from src.memory.models import MemoryAnalysisResult, MessageRecord, RetrievedMemoryContext
from src.memory.pipeline import MemoryPipeline


class MemoryService:
    def __init__(self, pipeline: MemoryPipeline) -> None:
        self.pipeline = pipeline

    def build_scope(
        self,
        *,
        platform: str,
        user_id: str,
        channel_id: str,
        guild_id: str | None,
    ) -> ConversationScope:
        return self.pipeline.build_scope(
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
        metadata: dict | None = None,
    ) -> MessageRecord:
        return self.pipeline.ingest_message(
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
        return self.pipeline.retrieve_for_reply(
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
        return await self.pipeline.process_completed_turn(scope, turn_messages=turn_messages)
