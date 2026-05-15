from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScopeSnapshotModel(BaseModel):
    user_id: str
    conversation_id: str
    channel_id: Optional[str] = None
    guild_id: Optional[str] = None
    display_name: str
    last_message_at: str
    latest_sender_type: str
    latest_preview: str
    pending_candidates: int
    active_memories: int
    turn_count: int


class PaginationMeta(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0
    total_pages: int = 0
    q: str = ""
    sort: str = ""
    filters: Dict[str, Any] = Field(default_factory=dict)
    refreshed_at: Optional[str] = None
    duration_ms: float = 0.0


class PanelEnvelope(BaseModel):
    active_scope: Optional[ScopeSnapshotModel] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    groups: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    highlights: Dict[str, Any] = Field(default_factory=dict)
    meta: PaginationMeta


class ActionResponse(BaseModel):
    ok: bool = True
    message: Optional[str] = None
    item_id: Optional[str] = None
    active_scope: Optional[ScopeSnapshotModel] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class LoginResponse(BaseModel):
    ok: bool
    username: str
    csrf_token: Optional[str] = None
    force_password_change: bool = False


class OverviewResponse(BaseModel):
    active_scope: Optional[ScopeSnapshotModel] = None
    overview: Dict[str, Any] = Field(default_factory=dict)
    quick_links: List[Dict[str, str]] = Field(default_factory=list)
    refreshed_at: str


class ScopesResponse(BaseModel):
    active_scope: Optional[ScopeSnapshotModel] = None
    items: List[ScopeSnapshotModel] = Field(default_factory=list)
    refreshed_at: str


class SecurityResponse(BaseModel):
    metrics: Dict[str, Any] = Field(default_factory=dict)
    events: List[Dict[str, Any]] = Field(default_factory=list)
    password_policy: Dict[str, Any] = Field(default_factory=dict)
    audits: List[Dict[str, Any]] = Field(default_factory=list)
    refreshed_at: str


class ModeStateResponse(BaseModel):
    mode: str = "auto"
    learning_mode: bool = False
    custom_model: Optional[str] = None
    backup_model: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GlobalSearchResponse(BaseModel):
    query: str
    groups: List[Dict[str, Any]] = Field(default_factory=list)
    total_hits: int = 0
    refreshed_at: str


class PerformanceResponse(BaseModel):
    performance: Dict[str, Any] = Field(default_factory=dict)
    experience: Dict[str, Any] = Field(default_factory=dict)
    json_extraction: Dict[str, Any] = Field(default_factory=dict)
    refreshed_at: str


class HealthResponse(BaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    trends: Dict[str, Any] = Field(default_factory=dict)
    refreshed_at: str
