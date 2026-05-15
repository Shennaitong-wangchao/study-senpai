from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModeState:
    mode: str = "auto"
    learning_mode: bool = False
    custom_model: str | None = None
    backup_model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AttachmentInsight:
    filename: str
    artifact_type: str
    content_type: str | None
    extracted_text: str
    summary_text: str
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def context_line(self) -> str:
        detail = self.summary_text or self.extracted_text
        if not detail:
            return f"{self.filename}（{self.artifact_type}）"
        return f"{self.filename}（{self.artifact_type}）：{detail}"


@dataclass
class SearchDigestItem:
    title: str
    snippet: str
    url: str


@dataclass
class SearchDigest:
    query: str
    items: list[SearchDigestItem]
    mode: str = "native_llm_search"
    note: str | None = None

    def to_context_block(self) -> str:
        lines = [f"搜索主题：{self.query}"]
        for item in self.items:
            lines.append(f"- {item.title}：{item.snippet} ({item.url})")
        return "\n".join(lines)


@dataclass
class ReplyPlan:
    request_type: str
    scene: str
    reply_goal: str
    mood: str
    rhythm: str
    should_search: bool
    should_draw: bool
    learning_mode: bool
    mode_text: str
    preferred_length: str
    system_note: str
    user_note: str
    strategy_tags: list[str] = field(default_factory=list)


@dataclass
class ImageGenerationResult:
    prompt: str
    file_path: str
    revised_prompt: str | None = None


@dataclass
class CandidateMemoryRecord:
    id: int
    candidate_uid: str
    user_id: str
    conversation_id: str | None
    session_id: str | None
    channel_id: str | None
    guild_id: str | None
    memory_type: str
    category: str
    content: str
    tags: list[str]
    confidence: float
    importance: float
    reason: str | None
    source_message_ids: list[int]
    dedupe_signature: str
    status: str
    metadata: dict[str, Any]
    approved_memory_uid: str | None
    review_note: str | None
    reviewed_at: str | None
    created_at: str
    updated_at: str


@dataclass
class BackgroundTaskRecord:
    id: int
    task_uid: str
    task_type: str
    user_id: str | None
    conversation_id: str | None
    session_id: str | None
    dedupe_key: str | None
    payload: dict[str, Any]
    status: str
    attempts: int
    max_attempts: int
    priority: float
    timeout_seconds: int
    available_at: str
    started_at: str | None
    finished_at: str | None
    last_error: str | None
    result: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass
class HealthCheckRecord:
    id: int
    component: str
    status: str
    message: str
    latency_ms: float
    details: dict[str, Any]
    checked_at: str


@dataclass
class TurnTraceRecord:
    id: int
    turn_uid: str
    user_id: str
    conversation_id: str
    session_id: str
    user_message_id: int | None
    assistant_message_id: int | None
    request_type: str
    reply_goal: str
    scene: str
    mode_text: str
    model_name: str | None
    backup_model_name: str | None
    fallback_used: bool
    latency_ms: float
    user_input: str
    assistant_reply: str
    attachments: list[dict[str, Any]]
    search_context: list[dict[str, Any]]
    planning: dict[str, Any]
    retrieval: dict[str, Any]
    metrics: dict[str, Any]
    error_text: str | None
    created_at: str


@dataclass
class ExperienceMetricsRecord:
    id: int
    turn_uid: str
    persona_consistency: float
    memory_hit_quality: float
    memory_usage_rate: float
    proactive_acceptance: float
    repeated_comfort_rate: float
    over_explaining_rate: float
    tool_trace_leakage_rate: float
    proactive_cold_response_rate: float
    structure_type: str
    metadata: dict[str, Any]
    created_at: str


@dataclass
class ProactiveMessageRecord:
    id: int
    proactive_uid: str
    user_id: str
    conversation_id: str
    channel_id: str
    trigger_type: str
    opening_text: str
    status: str
    accepted: bool | None
    cold_response: bool | None
    response_message_id: int | None
    response_latency_minutes: float | None
    metadata: dict[str, Any]
    sent_at: str
    updated_at: str
