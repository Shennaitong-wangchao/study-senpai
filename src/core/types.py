from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConversationScope:
    platform: str
    conversation_id: str
    user_id: str
    channel_id: str
    guild_id: str | None
    session_id: str


@dataclass
class MessageContext:
    platform_message_id: str | None
    author_id: str
    reply_to_platform_message_id: str | None = None
    thread_id: str | None = None
