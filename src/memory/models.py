from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MessageRecord:
    id: int
    platform: str
    conversation_id: str
    session_id: str
    platform_message_id: str | None
    sender_type: str
    author_id: str
    user_id: str
    channel_id: str
    guild_id: str | None
    reply_to_platform_message_id: str | None
    thread_id: str | None
    content: str
    metadata: dict[str, Any]
    created_at: str


@dataclass
class SessionMemoryRecord:
    id: int
    session_id: str
    conversation_id: str
    user_id: str
    channel_id: str
    guild_id: str | None
    memory_type: str
    content: str
    priority: float
    confidence: float
    status: str
    source_message_ids: list[int]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
    last_active_at: str
    expires_at: str | None


@dataclass
class LongTermMemoryRecord:
    id: int
    memory_uid: str
    user_id: str
    conversation_id: str | None
    channel_id: str | None
    guild_id: str | None
    memory_type: str
    category: str
    content: str
    tags: list[str]
    source_message_ids: list[int]
    confidence: float
    importance: float
    status: str
    last_used_at: str | None
    supersedes_memory_uid: str | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass
class StructuredFactRecord:
    id: int
    user_id: str
    namespace: str
    key: str
    value: str
    confidence: float
    source_message_ids: list[int]
    status: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass
class RelationshipStateRecord:
    id: int
    user_id: str
    dimension: str
    value: str
    weight: float
    confidence: float
    note: str | None
    source_message_ids: list[int]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass
class ConversationSummaryRecord:
    id: int
    conversation_id: str
    user_id: str
    channel_id: str
    guild_id: str | None
    session_id: str | None
    summary_kind: str
    content: str
    message_start_id: int
    message_end_id: int
    message_count: int
    version: int
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass
class SessionMemoryCandidate:
    memory_type: str
    content: str
    priority: float
    confidence: float
    reason: str
    source_message_ids: list[int]
    expires_in_minutes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LongTermMemoryCandidate:
    memory_type: str
    category: str
    content: str
    tags: list[str]
    importance: float
    confidence: float
    reason: str
    source_message_ids: list[int]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StructuredFactCandidate:
    namespace: str
    key: str
    value: str
    confidence: float
    reason: str
    source_message_ids: list[int]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelationshipUpdateCandidate:
    dimension: str
    value: str
    weight: float
    confidence: float
    note: str | None
    reason: str
    source_message_ids: list[int]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IgnoredSignal:
    reason: str
    source_message_ids: list[int]


@dataclass
class MemoryAnalysisResult:
    summary_hint: str | None
    session_memories: list[SessionMemoryCandidate]
    long_term_memories: list[LongTermMemoryCandidate]
    structured_facts: list[StructuredFactCandidate]
    relationship_updates: list[RelationshipUpdateCandidate]
    ignored_signals: list[IgnoredSignal]
    extraction_method: str


@dataclass
class RetrievedMemoryContext:
    recent_messages: list[MessageRecord]
    session_memories: list[SessionMemoryRecord]
    long_term_memories: list[LongTermMemoryRecord]
    structured_facts: list[StructuredFactRecord]
    relationship_states: list[RelationshipStateRecord]
    summary: ConversationSummaryRecord | None


@dataclass
class MemoryWriteResult:
    session_written: int = 0
    long_term_written: int = 0
    facts_written: int = 0
    relationship_written: int = 0
