from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.dashboard.schemas import ModeStateResponse, ScopeSnapshotModel


class MobileFeatureFlags(BaseModel):
    streaming_chat: bool = True
    attachments: bool = True
    voice_transcription: bool = True
    image_generation: bool = True
    local_notifications: bool = True
    apns: bool = False
    authentication_required: bool = False
    https_required: bool = False
    device_context_sync: bool = True
    native_dashboard: bool = True


class MobileCompanionProfile(BaseModel):
    app_name: str = "Lover"
    display_name: str = "学姐"
    relationship_label: str = "学姐陪伴"
    tone: str = "温柔主动、稳定、有分寸"


class MobileSceneState(BaseModel):
    key: str = "morning"
    asset_name: str = "scene-morning"
    status_line: str = "学姐在这儿，先陪你把今天稳住。"
    reason: str = "time"
    updated_at: str


class MobileDashboardGroup(BaseModel):
    id: str
    title: str
    subtitle: str = ""
    panels: List[str] = Field(default_factory=list)


class MobileBootstrapResponse(BaseModel):
    active_scope: Optional[ScopeSnapshotModel] = None
    mode: ModeStateResponse = Field(default_factory=ModeStateResponse)
    profile: MobileCompanionProfile = Field(default_factory=MobileCompanionProfile)
    scene_state: Optional[MobileSceneState] = None
    timeline_cursor: Optional[str] = None
    dashboard_groups: List[MobileDashboardGroup] = Field(default_factory=list)
    presence: Dict[str, Any] = Field(default_factory=dict)
    companion_day: Dict[str, Any] = Field(default_factory=dict)
    proactive: Dict[str, Any] = Field(default_factory=dict)
    reality_context: Dict[str, Any] = Field(default_factory=dict)
    feature_flags: MobileFeatureFlags = Field(default_factory=MobileFeatureFlags)
    refreshed_at: str


class MobileMessageModel(BaseModel):
    id: int
    platform: str
    conversation_id: str
    session_id: str
    platform_message_id: Optional[str] = None
    sender_type: str
    author_id: str
    user_id: str
    channel_id: str
    guild_id: Optional[str] = None
    reply_to_platform_message_id: Optional[str] = None
    thread_id: Optional[str] = None
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class MobileMessagesResponse(BaseModel):
    active_scope: Optional[ScopeSnapshotModel] = None
    items: List[MobileMessageModel] = Field(default_factory=list)
    has_more: bool = False
    next_before_id: Optional[int] = None
    refreshed_at: str


class MobileTimelineAttachment(BaseModel):
    upload_uid: Optional[str] = None
    filename: str
    artifact_type: str = "document"
    content_type: Optional[str] = None
    summary_text: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MobileTimelineItem(BaseModel):
    id: str
    kind: str
    created_at: str
    content: str = ""
    sender_label: str = ""
    message_id: Optional[int] = None
    proactive_uid: Optional[str] = None
    attachments: List[MobileTimelineAttachment] = Field(default_factory=list)
    generated_image_url: Optional[str] = None
    feedback: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MobileTimelineResponse(BaseModel):
    active_scope: Optional[ScopeSnapshotModel] = None
    items: List[MobileTimelineItem] = Field(default_factory=list)
    has_more: bool = False
    next_cursor: Optional[str] = None
    refreshed_at: str


class MobileToolOverrides(BaseModel):
    search: Optional[bool] = None
    draw: Optional[bool] = None


class MobileChatRequest(BaseModel):
    content: str = ""
    client_message_id: Optional[str] = None
    attachment_uids: List[str] = Field(default_factory=list)
    display_name: str = "Lover"
    tool_overrides: MobileToolOverrides = Field(default_factory=MobileToolOverrides)
    client_scene: Optional[str] = None
    client_timezone: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MobileAttachmentItem(BaseModel):
    filename: str
    artifact_type: str
    content_type: Optional[str] = None
    extracted_text: str = ""
    summary_text: str = ""
    truncated: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MobileAttachmentUploadResponse(BaseModel):
    upload_uid: str
    items: List[MobileAttachmentItem] = Field(default_factory=list)
    created_at: str


class MobileStatusResponse(BaseModel):
    active_scope: Optional[ScopeSnapshotModel] = None
    text: str
    mode: ModeStateResponse = Field(default_factory=ModeStateResponse)
    requests_last_hour: int = 0
    refreshed_at: str


class MobileProactiveResponse(BaseModel):
    active_scope: Optional[ScopeSnapshotModel] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    cursor: Optional[str] = None
    refreshed_at: str


class MobileProactivePreferencesResponse(BaseModel):
    active_scope: Optional[ScopeSnapshotModel] = None
    preferences: Dict[str, Any] = Field(default_factory=dict)
    gate: Dict[str, Any] = Field(default_factory=dict)
    refreshed_at: str


class MobileDeviceLocation(BaseModel):
    label: str = "iPhone"
    latitude: float
    longitude: float
    note: Optional[str] = None


class MobileDeviceCalendarEvent(BaseModel):
    title: str
    start_at: str
    end_at: Optional[str] = None
    location: Optional[str] = None
    is_all_day: bool = False
    note: Optional[str] = None


class MobileDeviceContextRequest(BaseModel):
    location: Optional[MobileDeviceLocation] = None
    calendar_events: List[MobileDeviceCalendarEvent] = Field(default_factory=list)
    source: str = "ios"


class MobileDeviceContextResponse(BaseModel):
    ok: bool = True
    active_scope: Optional[ScopeSnapshotModel] = None
    location: Optional[Dict[str, Any]] = None
    calendar_event_count: int = 0
    payload: Dict[str, Any] = Field(default_factory=dict)
    refreshed_at: str
