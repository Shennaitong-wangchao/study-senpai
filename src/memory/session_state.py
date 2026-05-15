from __future__ import annotations

import uuid

from src.core.types import ConversationScope
from src.memory.store import MemoryStore
from src.utils.time_utils import parse_iso8601, utc_now


class SessionStateManager:
    def __init__(
        self,
        store: MemoryStore,
        session_timeout_minutes: int,
        *,
        single_user_mode: bool = False,
        single_user_id: str = "primary_user",
    ) -> None:
        self.store = store
        self.session_timeout_minutes = session_timeout_minutes
        self.single_user_mode = single_user_mode
        self.single_user_id = single_user_id

    @staticmethod
    def build_conversation_id(
        platform: str,
        *,
        user_id: str,
        channel_id: str,
        guild_id: str | None,
    ) -> str:
        guild_part = guild_id or "dm"
        return f"{platform}:{guild_part}:{channel_id}:{user_id}"

    def build_scope(
        self,
        *,
        platform: str,
        user_id: str,
        channel_id: str,
        guild_id: str | None,
    ) -> ConversationScope:
        normalized_user_id = self._normalize_user_id(user_id)
        conversation_id = self.build_conversation_id(
            platform,
            user_id=normalized_user_id,
            channel_id=channel_id,
            guild_id=guild_id,
        )
        session_id = self.resolve_session_id(conversation_id)
        return ConversationScope(
            platform=platform,
            conversation_id=conversation_id,
            user_id=normalized_user_id,
            channel_id=channel_id,
            guild_id=guild_id,
            session_id=session_id,
        )

    def resolve_session_id(self, conversation_id: str) -> str:
        latest_message = self.store.get_latest_message(conversation_id)
        if latest_message:
            created_at = parse_iso8601(latest_message.created_at)
            if created_at:
                elapsed_minutes = (utc_now() - created_at).total_seconds() / 60
                if elapsed_minutes <= self.session_timeout_minutes:
                    return latest_message.session_id
        return f"session_{uuid.uuid4().hex}"

    def _normalize_user_id(self, user_id: str) -> str:
        if self.single_user_mode:
            return self.single_user_id
        return user_id
