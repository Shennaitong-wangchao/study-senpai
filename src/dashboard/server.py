from __future__ import annotations

import math
import ipaddress
import secrets
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from src.core.settings import Settings
from src.core.types import ConversationScope, MessageContext
from src.llm.client import LLMClient
from src.dashboard.schemas import (
    ActionResponse,
    GlobalSearchResponse,
    HealthResponse,
    LoginResponse,
    ModeStateResponse,
    OverviewResponse,
    PaginationMeta,
    PanelEnvelope,
    PerformanceResponse,
    ScopesResponse,
    ScopeSnapshotModel,
    SecurityResponse,
)
from src.dashboard.security import hash_dashboard_password, request_source_ip, verify_dashboard_password
from src.memory.session_state import SessionStateManager
from src.memory.store import MemoryStore
from src.product.day_engine import CompanionDayEngine
from src.product.models import AttachmentInsight
from src.product.presence import PresenceStateService
from src.product.proactive import (
    get_proactive_preferences,
    proactive_backoff_key,
    proactive_cadence_policy,
    set_proactive_preferences,
)
from src.product.reality import RealityContextService
from src.product.store import ProductStore
from src.mobile.schemas import (
    MobileAttachmentItem,
    MobileAttachmentUploadResponse,
    MobileBootstrapResponse,
    MobileChatRequest,
    MobileCompanionProfile,
    MobileDeviceContextRequest,
    MobileDeviceContextResponse,
    MobileFeatureFlags,
    MobileMessageModel,
    MobileMessagesResponse,
    MobileProactivePreferencesResponse,
    MobileProactiveResponse,
    MobileDashboardGroup,
    MobileSceneState,
    MobileStatusResponse,
    MobileTimelineAttachment,
    MobileTimelineItem,
    MobileTimelineResponse,
)
from src.utils.json_utils import get_json_extraction_stats, json_dumps, json_loads
from src.utils.text_utils import compact_text, truncate_text
from src.utils.time_utils import iso_utc_now, parse_iso8601


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

ALLOWED_MODE_VALUES = {"auto", "fast", "think", "custom"}
ALLOWED_ERROR_STATUS_VALUES = {"open", "processed", "ignored", "archived"}
LOCAL_DEV_HOSTS = {"localhost", "127.0.0.1", "::1", "testclient", "testserver"}
ALLOWED_REVIEW_ACTIONS = {"approve", "reject"}
ALLOWED_REFRESH_MODES = {"paused", "5s", "15s", "manual"}


class CandidateReviewRequest(BaseModel):
    note: Optional[str] = None


class BatchCandidateReviewRequest(BaseModel):
    candidate_uids: List[str] = Field(default_factory=list)
    action: str
    note: Optional[str] = None


class ErrorStatusRequest(BaseModel):
    status: str
    note: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ModeUpdateRequest(BaseModel):
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    mode: str
    learning_mode: bool = False
    custom_model: Optional[str] = None
    backup_model: Optional[str] = None


class ScopeUpdateRequest(BaseModel):
    user_id: str
    conversation_id: str


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str
    confirm_password: str


class TaskPriorityRequest(BaseModel):
    priority: float = 1.0


class PresenceUpdateRequest(BaseModel):
    user_sleep_state: Optional[str] = None
    user_sleep_state_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    current_scene_label: Optional[str] = None
    daily_detail: Optional[str] = None
    assistant_location_label: Optional[str] = None
    assistant_mood_label: Optional[str] = None
    note: Optional[str] = None


class ProactiveFeedbackRequest(BaseModel):
    feedback: str
    note: Optional[str] = None


class ProactivePreferencesRequest(BaseModel):
    enabled: Optional[bool] = None
    cadence: Optional[str] = None


class CompanionDayUpdateRequest(BaseModel):
    current_scene: Optional[str] = None
    mood_label: Optional[str] = None
    longing_level: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    quiet_mode: Optional[bool] = None
    note: Optional[str] = None


class CompanionDayFeedbackRequest(BaseModel):
    feedback: str
    note: Optional[str] = None


class RealityLocationRequest(BaseModel):
    label: str
    latitude: float
    longitude: float
    note: Optional[str] = None


class RealityCalendarSourceRequest(BaseModel):
    url: str
    label: Optional[str] = None
    enabled: bool = True


class RealityCalendarSourceToggleRequest(BaseModel):
    enabled: bool


class RealityManualEventRequest(BaseModel):
    title: str
    start_at: str
    end_at: Optional[str] = None
    location: Optional[str] = None
    is_all_day: bool = False
    note: Optional[str] = None


def _normalize_mode_value(raw_mode: str) -> str:
    normalized = (raw_mode or "").strip().lower()
    aliases = {
        "自动": "auto",
        "fast": "fast",
        "quick": "fast",
        "快速": "fast",
        "thinking": "think",
        "deep": "think",
        "深度": "think",
        "think": "think",
        "自定义": "custom",
        "custom": "custom",
    }
    return aliases.get(normalized, normalized)


def _host_without_port(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(f"//{value}")
    return (parsed.hostname or value).strip("[]").lower()


def _is_local_dev_host(value: str | None) -> bool:
    host = _host_without_port(value)
    if host in LOCAL_DEV_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_local_mobile_dev_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    target_host = request.url.hostname or request.headers.get("host", "")
    return _is_local_dev_host(client_host) and _is_local_dev_host(target_host)


def _origin_matches_dashboard(request: Request) -> bool:
    expected = (request.url.scheme, request.url.netloc)
    candidates = [
        request.headers.get("origin"),
        request.headers.get("referer"),
    ]
    for value in candidates:
        if not value:
            continue
        parsed = urlparse(value)
        if (parsed.scheme, parsed.netloc) != expected:
            return False
    return True


def _prefers_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "*/*" in accept


@lru_cache(maxsize=8)
def _read_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _render_template(name: str, *, bootstrap: dict[str, Any]) -> str:
    payload = json_dumps(bootstrap).replace("</", "<\\/")
    return _read_template(name).replace("__BOOTSTRAP_JSON__", payload)


def _normalize_q(value: str | None) -> str:
    return compact_text(value or "")[:120]


def _normalize_page(page: int, page_size: int, *, max_size: int = 60) -> tuple[int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), max_size)
    return safe_page, safe_page_size


def _build_text_search(q: str, columns: list[str]) -> tuple[str, list[Any]]:
    normalized = _normalize_q(q)
    if not normalized:
        return "", []
    like = f"%{normalized}%"
    return "(" + " OR ".join(f"{column} LIKE ?" for column in columns) + ")", [like] * len(columns)


def _paged_meta(
    *,
    total: int,
    page: int,
    page_size: int,
    q: str = "",
    sort: str = "",
    filters: dict[str, Any] | None = None,
    duration_ms: float = 0.0,
) -> PaginationMeta:
    total_pages = math.ceil(total / page_size) if page_size else 0
    return PaginationMeta(
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        q=q,
        sort=sort,
        filters=filters or {},
        refreshed_at=iso_utc_now(),
        duration_ms=round(duration_ms, 2),
    )


def _build_panel_response(
    *,
    active_scope: dict[str, Any] | None,
    items: list[dict[str, Any]],
    total: int,
    page: int,
    page_size: int,
    q: str = "",
    sort: str = "",
    filters: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    groups: list[dict[str, Any]] | None = None,
    highlights: dict[str, Any] | None = None,
    duration_ms: float = 0.0,
) -> PanelEnvelope:
    scope_model = None if active_scope is None else ScopeSnapshotModel.model_validate(active_scope)
    return PanelEnvelope(
        active_scope=scope_model,
        items=items,
        groups=groups or [],
        summary=summary or {},
        highlights=highlights or {},
        meta=_paged_meta(
            total=total,
            page=page,
            page_size=page_size,
            q=q,
            sort=sort,
            filters=filters,
            duration_ms=duration_ms,
        ),
    )


def _run_paged_select(
    *,
    db,
    columns: str,
    from_clause: str,
    params: list[Any],
    order_by: str,
    page: int,
    page_size: int,
) -> tuple[list[Any], int]:
    count_row = db.fetchone(f"SELECT COUNT(*) AS count {from_clause}", params)
    total = int(count_row["count"]) if count_row else 0
    offset = (page - 1) * page_size
    rows = db.fetchall(
        f"SELECT {columns} {from_clause} ORDER BY {order_by} LIMIT ? OFFSET ?",
        [*params, page_size, offset],
    )
    return rows, total


def _serialize_audit_row(row: Any) -> dict[str, Any]:
    return {
        "audit_uid": row["audit_uid"],
        "actor_username": row["actor_username"],
        "source_ip": row["source_ip"],
        "action_type": row["action_type"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "scope_user_id": row["scope_user_id"],
        "scope_conversation_id": row["scope_conversation_id"],
        "status": row["status"],
        "undo_available": bool(row["undo_available"]),
        "details": json_loads(row["details_json"], {}),
        "undo_payload": json_loads(row["undo_payload_json"], {}),
        "created_at": row["created_at"],
        "undone_at": row["undone_at"],
    }


def _serialize_candidate_row(row: Any) -> dict[str, Any]:
    metadata = json_loads(row["metadata_json"], {})
    return {
        "candidate_uid": row["candidate_uid"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "session_id": row["session_id"],
        "channel_id": row["channel_id"],
        "guild_id": row["guild_id"],
        "memory_type": row["memory_type"],
        "category": row["category"],
        "content": row["content"],
        "tags": json_loads(row["tags_json"], []),
        "confidence": float(row["confidence"]),
        "importance": float(row["importance"]),
        "reason": row["reason"],
        "source_message_ids": json_loads(row["source_message_ids_json"], []),
        "dedupe_signature": row["dedupe_signature"],
        "status": row["status"],
        "metadata": metadata,
        "approved_memory_uid": row["approved_memory_uid"],
        "review_note": row["review_note"],
        "reviewed_at": row["reviewed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "preview": truncate_text(row["content"], 120),
    }


def _serialize_error_row(row: Any) -> dict[str, Any]:
    details = json_loads(row["details_json"], {})
    return {
        "error_uid": row["error_uid"],
        "component": row["component"],
        "severity": row["severity"],
        "message": row["message"],
        "details": details,
        "request_id": details.get("request_id"),
        "related_task_uid": row["related_task_uid"],
        "related_turn_uid": row["related_turn_uid"],
        "status": row["status"],
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }


def _serialize_memory_row(row: Any) -> dict[str, Any]:
    metadata = json_loads(row["metadata_json"], {})
    return {
        "memory_uid": row["memory_uid"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "channel_id": row["channel_id"],
        "guild_id": row["guild_id"],
        "memory_type": row["memory_type"],
        "category": row["category"],
        "content": row["content"],
        "tags": json_loads(row["tags_json"], []),
        "source_message_ids": json_loads(row["source_message_ids_json"], []),
        "confidence": float(row["confidence"]),
        "importance": float(row["importance"]),
        "status": row["status"],
        "last_used_at": row["last_used_at"],
        "hit_count": int(row["hit_count"] or 0),
        "last_hit_at": row["last_hit_at"],
        "approved_from_candidate": metadata.get("approved_from_candidate"),
        "metadata": metadata,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _serialize_task_row(row: Any) -> dict[str, Any]:
    payload = json_loads(row["payload_json"], {})
    result = json_loads(row["result_json"], {})
    return {
        "task_uid": row["task_uid"],
        "task_type": row["task_type"],
        "request_id": payload.get("request_id") or result.get("request_id"),
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "session_id": row["session_id"],
        "dedupe_key": row["dedupe_key"],
        "payload": payload,
        "status": row["status"],
        "attempts": int(row["attempts"]),
        "max_attempts": int(row["max_attempts"]),
        "priority": float(row["priority"]),
        "timeout_seconds": int(row["timeout_seconds"]),
        "available_at": row["available_at"],
        "next_retry_at": row["available_at"] if row["status"] == "retrying" else None,
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "last_error": row["last_error"],
        "result": result,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _serialize_turn_row(row: Any) -> dict[str, Any]:
    planning = json_loads(row["planning_json"], {})
    retrieval = json_loads(row["retrieval_json"], {})
    metrics = json_loads(row["metrics_json"], {})
    attachments = json_loads(row["attachments_json"], [])
    search_context = json_loads(row["search_context_json"], [])
    return {
        "turn_uid": row["turn_uid"],
        "request_id": metrics.get("request_id") or planning.get("request_id"),
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "session_id": row["session_id"],
        "request_type": row["request_type"],
        "reply_goal": row["reply_goal"],
        "scene": row["scene"],
        "mode_text": row["mode_text"],
        "model_name": row["model_name"],
        "backup_model_name": row["backup_model_name"],
        "fallback_used": bool(row["fallback_used"]),
        "latency_ms": float(row["latency_ms"]),
        "prompt_char_count": metrics.get("prompt_char_count", 0),
        "estimated_input_tokens": metrics.get("estimated_input_tokens", 0),
        "estimated_output_tokens": metrics.get("estimated_output_tokens", 0),
        "estimated_total_tokens": metrics.get("estimated_total_tokens", 0),
        "estimated_cost_usd": metrics.get("estimated_cost_usd", 0),
        "attachment_count": metrics.get("attachment_count", len(attachments)),
        "search_count": metrics.get("search_count", len(search_context)),
        "user_input": row["user_input"],
        "assistant_reply": row["assistant_reply"],
        "attachments": attachments,
        "search_context": search_context,
        "planning": planning,
        "retrieval": retrieval,
        "metrics": metrics,
        "error_text": row["error_text"],
        "created_at": row["created_at"],
    }


def _serialize_snapshot_row(row: Any, previous_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = json_loads(row["snapshot_json"], {})
    diff = _snapshot_diff(snapshot, previous_snapshot or {})
    return {
        "snapshot_uid": row["snapshot_uid"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "session_id": row["session_id"],
        "turn_uid": row["turn_uid"],
        "snapshot": snapshot,
        "diff": diff,
        "created_at": row["created_at"],
    }


def _snapshot_diff(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    if not previous:
        return {"status": "initial", "changed_keys": list(current.keys()), "changes": {}}
    changed: dict[str, Any] = {}
    for key in sorted(set(current) | set(previous)):
        if current.get(key) == previous.get(key):
            continue
        current_value = current.get(key)
        previous_value = previous.get(key)
        if isinstance(current_value, list) and isinstance(previous_value, list):
            changed[key] = {
                "before_count": len(previous_value),
                "after_count": len(current_value),
                "after_preview": truncate_text(compact_text(json_dumps(current_value[:2])), 120),
            }
            continue
        changed[key] = {
            "before": truncate_text(compact_text(json_dumps(previous_value)), 120),
            "after": truncate_text(compact_text(json_dumps(current_value)), 120),
        }
    return {"status": "changed" if changed else "same", "changed_keys": list(changed.keys()), "changes": changed}


def _serialize_attachment_row(row: Any) -> dict[str, Any]:
    metadata = json_loads(row["metadata_json"], {})
    return {
        "artifact_uid": row["artifact_uid"],
        "platform_message_id": row["platform_message_id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "artifact_type": row["artifact_type"],
        "extracted_text": row["extracted_text"],
        "summary_text": row["summary_text"],
        "truncated": bool(row["truncated"]),
        "metadata": metadata,
        "created_at": row["created_at"],
    }


def _serialize_fact_row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "user_id": row["user_id"],
        "namespace": row["namespace"],
        "key": row["key"],
        "value": row["value"],
        "confidence": float(row["confidence"]),
        "source_message_ids": json_loads(row["source_message_ids_json"], []),
        "status": row["status"],
        "metadata": json_loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _serialize_relationship_row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "user_id": row["user_id"],
        "dimension": row["dimension"],
        "value": row["value"],
        "weight": float(row["weight"]),
        "confidence": float(row["confidence"]),
        "note": row["note"],
        "source_message_ids": json_loads(row["source_message_ids_json"], []),
        "metadata": json_loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _serialize_summary_row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "conversation_id": row["conversation_id"],
        "user_id": row["user_id"],
        "channel_id": row["channel_id"],
        "guild_id": row["guild_id"],
        "session_id": row["session_id"],
        "summary_kind": row["summary_kind"],
        "content": row["content"],
        "message_start_id": int(row["message_start_id"]),
        "message_end_id": int(row["message_end_id"]),
        "message_count": int(row["message_count"]),
        "version": int(row["version"]),
        "metadata": json_loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _serialize_shared_diary_row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "diary_uid": row["diary_uid"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "route_uid": row["route_uid"],
        "event_uid": row["event_uid"],
        "local_date": row["local_date"],
        "entry_type": row["entry_type"],
        "title": row["title"],
        "content": row["content"],
        "role_scope": row["role_scope"],
        "source": row["source"],
        "importance": float(row["importance"]),
        "tags": json_loads(row["tags_json"], []),
        "metadata": json_loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _serialize_proactive_row(row: Any) -> dict[str, Any]:
    metadata = json_loads(row["metadata_json"], {})
    accepted = row["accepted"]
    cold_response = row["cold_response"]
    return {
        "proactive_uid": row["proactive_uid"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "channel_id": row["channel_id"],
        "trigger_type": row["trigger_type"],
        "opening_text": row["opening_text"],
        "status": row["status"],
        "accepted": None if accepted is None else bool(accepted),
        "cold_response": None if cold_response is None else bool(cold_response),
        "response_message_id": row["response_message_id"],
        "response_latency_minutes": row["response_latency_minutes"],
        "metadata": metadata,
        "sent_at": row["sent_at"],
        "updated_at": row["updated_at"],
    }


def build_dashboard_app(
    *,
    settings: Settings,
    product_store: ProductStore,
    memory_store: MemoryStore,
    llm_client: LLMClient | None = None,
    companion_service: Any | None = None,
    attachment_service: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="Shen Zhiwei Dashboard")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="dashboard-static")
    presence_service = PresenceStateService(
        settings=settings,
        product_store=product_store,
        memory_store=memory_store,
        llm_client=llm_client,
    )
    reality_service = RealityContextService(
        settings=settings,
        product_store=product_store,
    )
    day_engine = CompanionDayEngine(
        settings=settings,
        product_store=product_store,
        memory_store=memory_store,
        llm_client=llm_client,
        reality_context=reality_service,
    )

    def add_dashboard_headers(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        return response

    def is_mobile_path(path: str) -> bool:
        return path == "/mobile" or path.startswith("/mobile/")

    def mobile_auth_error(request: Request) -> JSONResponse | None:
        if settings.mobile_api_token:
            authorization = request.headers.get("authorization", "")
            scheme, _, token = authorization.partition(" ")
            token = token.strip()
            if scheme.lower() == "bearer" and token and secrets.compare_digest(token, settings.mobile_api_token):
                return None
            return JSONResponse(
                {"detail": "mobile authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if _is_local_mobile_dev_request(request):
            return None
        return JSONResponse(
            {"detail": "MOBILE_API_TOKEN is required for non-local mobile API access"},
            status_code=403,
        )

    def session_csrf_token(request: Request) -> str | None:
        return request.session.get("csrf_token") if settings.dashboard_auth_enabled else None

    def session_value(request: Request, key: str, default: Any = None) -> Any:
        if not settings.dashboard_auth_enabled:
            return default
        return request.session.get(key, default)

    def issue_dashboard_session(request: Request) -> None:
        request.session.clear()
        request.session.update(
            {
                "dashboard_authenticated": True,
                "dashboard_username": settings.dashboard_auth_username,
                "csrf_token": secrets.token_urlsafe(24),
                "force_password_change": product_store.dashboard_password_change_required(
                    generated_password_in_use=settings.dashboard_auth_password_generated,
                ),
            }
        )

    def clear_dashboard_session(request: Request) -> None:
        if settings.dashboard_auth_enabled:
            request.session.clear()

    def session_username(request: Request) -> str:
        return str(session_value(request, "dashboard_username", settings.dashboard_auth_username))

    def resolve_scope_ids(
        *,
        user_id: str,
        conversation_id: str | None,
        channel_id: str | None,
        guild_id: str | None,
    ) -> tuple[str, str]:
        resolved_channel_id = channel_id or "dashboard-review"
        resolved_conversation_id = conversation_id or SessionStateManager.build_conversation_id(
            "discord",
            user_id=user_id,
            channel_id=resolved_channel_id,
            guild_id=guild_id,
        )
        return resolved_channel_id, resolved_conversation_id

    def current_scope_snapshot() -> dict[str, Any] | None:
        active = product_store.get_dashboard_active_scope()
        if active is not None:
            snapshot = product_store.get_scope_snapshot(
                user_id=str(active["user_id"]),
                conversation_id=str(active["conversation_id"]),
            )
            if snapshot is not None:
                return snapshot

        recent_conversations = memory_store.list_recent_conversations(limit=1)
        if recent_conversations:
            item = recent_conversations[0]
            snapshot = product_store.get_scope_snapshot(
                user_id=str(item["user_id"]),
                conversation_id=str(item["conversation_id"]),
            )
            if snapshot is not None:
                product_store.set_dashboard_active_scope(
                    user_id=snapshot["user_id"],
                    conversation_id=snapshot["conversation_id"],
                    channel_id=snapshot["channel_id"],
                    guild_id=snapshot["guild_id"],
                )
                return snapshot

        memory_row = product_store.db.fetchone(
            """
            SELECT user_id, conversation_id, channel_id, guild_id
            FROM long_term_memories
            WHERE status = 'active'
            ORDER BY importance DESC, updated_at DESC
            LIMIT 1
            """
        )
        if memory_row:
            _, resolved_conversation_id = resolve_scope_ids(
                user_id=str(memory_row["user_id"]),
                conversation_id=memory_row["conversation_id"],
                channel_id=memory_row["channel_id"],
                guild_id=memory_row["guild_id"],
            )
            snapshot = product_store.get_scope_snapshot(
                user_id=str(memory_row["user_id"]),
                conversation_id=resolved_conversation_id,
            )
            if snapshot is not None:
                product_store.set_dashboard_active_scope(
                    user_id=snapshot["user_id"],
                    conversation_id=snapshot["conversation_id"],
                    channel_id=snapshot["channel_id"],
                    guild_id=snapshot["guild_id"],
                )
                return snapshot
        return None

    def resolve_primary_scope() -> tuple[str, str] | None:
        snapshot = current_scope_snapshot()
        if snapshot is None:
            return None
        return str(snapshot["user_id"]), str(snapshot["conversation_id"])

    def conversation_scope_from_snapshot(snapshot: dict[str, Any]) -> ConversationScope:
        return ConversationScope(
            platform="discord",
            conversation_id=str(snapshot["conversation_id"]),
            user_id=str(snapshot["user_id"]),
            channel_id=None if snapshot.get("channel_id") is None else str(snapshot.get("channel_id")),
            guild_id=None if snapshot.get("guild_id") is None else str(snapshot.get("guild_id")),
            session_id=str(snapshot.get("session_id") or "dashboard-presence"),
        )

    def current_conversation_scope() -> tuple[dict[str, Any], ConversationScope]:
        snapshot = current_scope_snapshot()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="no active scope")
        return snapshot, conversation_scope_from_snapshot(snapshot)

    def proactive_preferences_payload(scope: ConversationScope) -> dict[str, Any]:
        preferences = get_proactive_preferences(
            settings=settings,
            product_store=product_store,
            memory_store=memory_store,
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
        )
        policy = proactive_cadence_policy(str(preferences.get("cadence") or "low"))
        latest = next(
            (
                item
                for item in product_store.list_proactive_messages(limit=80)
                if item.user_id == scope.user_id and item.conversation_id == scope.conversation_id
            ),
            None,
        )
        backoff = product_store.get_app_setting(proactive_backoff_key(scope.conversation_id), {})
        gate = {
            "system_enabled": settings.enable_proactive_messages,
            "policy": policy,
            "backoff": backoff if isinstance(backoff, dict) else {},
            "latest_proactive": None
            if latest is None
            else {
                "proactive_uid": latest.proactive_uid,
                "trigger_type": latest.trigger_type,
                "status": latest.status,
                "sent_at": latest.sent_at,
                "opening_text": truncate_text(latest.opening_text, 120),
            },
        }
        return {"preferences": preferences, "gate": gate}

    def dashboard_password_is_valid(password: str) -> bool:
        password_hash = product_store.get_dashboard_password_hash()
        if password_hash:
            return verify_dashboard_password(password, password_hash)
        return secrets.compare_digest(password, settings.dashboard_auth_password)

    def audit_action(
        request: Request,
        *,
        action_type: str,
        target_type: str,
        target_id: str,
        details: dict[str, Any] | None = None,
        undo_available: bool = False,
        undo_payload: dict[str, Any] | None = None,
        scope: dict[str, Any] | None = None,
    ) -> str:
        return product_store.record_dashboard_action_audit(
            actor_username=session_username(request),
            source_ip=request_source_ip(request),
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            scope_user_id=None if scope is None else scope.get("user_id"),
            scope_conversation_id=None if scope is None else scope.get("conversation_id"),
            details=details,
            undo_available=undo_available,
            undo_payload=undo_payload,
        )

    class DashboardSecurityMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if not settings.dashboard_auth_enabled:
                response = await call_next(request)
                return add_dashboard_headers(response)

            path = request.url.path
            public_paths = {"/login", "/api/login", "/static"}
            password_change_allowed_paths = {"/api/account/password", "/api/logout"}
            if is_mobile_path(path):
                auth_error = mobile_auth_error(request)
                if auth_error is not None:
                    return add_dashboard_headers(auth_error)
                response = await call_next(request)
                return add_dashboard_headers(response)
            if not any(path == public or path.startswith(f"{public}/") for public in public_paths):
                if not session_value(request, "dashboard_authenticated"):
                    if _prefers_html(request):
                        return add_dashboard_headers(RedirectResponse("/login", status_code=303))
                    return add_dashboard_headers(
                        JSONResponse({"detail": "dashboard authentication required"}, status_code=401)
                    )
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    if not _origin_matches_dashboard(request):
                        return add_dashboard_headers(
                            JSONResponse({"detail": "invalid dashboard origin"}, status_code=403)
                        )
                    session_token = session_csrf_token(request)
                    header_token = request.headers.get("x-csrf-token", "")
                    if not session_token or not secrets.compare_digest(header_token, session_token):
                        return add_dashboard_headers(
                            JSONResponse({"detail": "invalid csrf token"}, status_code=403)
                        )
                    if bool(session_value(request, "force_password_change", False)) and path not in password_change_allowed_paths:
                        return add_dashboard_headers(
                            JSONResponse({"detail": "password change required before other write actions"}, status_code=403)
                        )
            response = await call_next(request)
            return add_dashboard_headers(response)

    app.add_middleware(DashboardSecurityMiddleware)
    if settings.dashboard_auth_enabled:
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.dashboard_session_secret,
            same_site="strict",
            max_age=settings.dashboard_session_ttl_seconds,
            https_only=settings.dashboard_session_https_only,
            session_cookie="zhiwei_dashboard_session",
        )

    def render_login_page(request: Request) -> HTMLResponse:
        return HTMLResponse(
            _render_template(
                "login.html",
                bootstrap={
                    "title": "沈知微 Dashboard 登录",
                    "csrfToken": session_csrf_token(request) or "",
                    "refreshModes": sorted(ALLOWED_REFRESH_MODES),
                },
            )
        )

    def render_dashboard_page(request: Request) -> HTMLResponse:
        scope = current_scope_snapshot()
        bootstrap = {
            "title": "沈知微长期陪伴系统",
            "csrfToken": session_csrf_token(request) or "",
            "username": session_value(request, "dashboard_username"),
            "forcePasswordChange": bool(session_value(request, "force_password_change", False)),
            "activeScope": scope,
            "refreshModes": sorted(ALLOWED_REFRESH_MODES),
        }
        return HTMLResponse(_render_template("dashboard.html", bootstrap=bootstrap))

    def update_error_status_row(error_uid: str, *, status: str) -> bool:
        resolved_at = iso_utc_now() if status != "open" else None
        cursor = product_store.db.execute(
            """
            UPDATE error_events
            SET status = ?, resolved_at = ?
            WHERE error_uid = ?
            """,
            (status, resolved_at, error_uid),
        )
        return (cursor.rowcount or 0) > 0

    def candidate_scope_from_row(row: Any) -> ConversationScope:
        resolved_channel_id, resolved_conversation_id = resolve_scope_ids(
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
        )
        return ConversationScope(
            platform="discord",
            conversation_id=resolved_conversation_id,
            user_id=row["user_id"],
            channel_id=resolved_channel_id,
            guild_id=row["guild_id"],
            session_id=row["session_id"] or "dashboard-review",
        )

    def approve_candidate_in_transaction(connection: Any, candidate_uid: str, note: str | None) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT * FROM candidate_memories
            WHERE candidate_uid = ?
            LIMIT 1
            """,
            (candidate_uid,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"candidate is already {row['status']}")

        scope = candidate_scope_from_row(row)
        tags = json_loads(row["tags_json"], [])
        source_message_ids = json_loads(row["source_message_ids_json"], [])
        metadata = json_loads(row["metadata_json"], {})
        reviewed_at = iso_utc_now()
        approved_memory_uid = memory_store.insert_or_merge_long_term_memory(
            scope,
            memory_type=row["memory_type"],
            category=row["category"],
            content=row["content"],
            tags=tags,
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            source_message_ids=source_message_ids,
            metadata={**metadata, "approved_from_candidate": row["candidate_uid"]},
            connection=connection,
        )
        updated = connection.execute(
            """
            UPDATE candidate_memories
            SET status = 'approved', review_note = ?, approved_memory_uid = ?, reviewed_at = ?, updated_at = ?
            WHERE candidate_uid = ? AND status = 'pending'
            """,
            (note, approved_memory_uid, reviewed_at, reviewed_at, candidate_uid),
        )
        if (updated.rowcount or 0) != 1:
            raise HTTPException(status_code=409, detail="candidate approval conflict")
        return {"candidate_uid": candidate_uid, "approved_memory_uid": approved_memory_uid}

    def reject_candidate_in_transaction(connection: Any, candidate_uid: str, note: str | None) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT * FROM candidate_memories
            WHERE candidate_uid = ?
            LIMIT 1
            """,
            (candidate_uid,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"candidate is already {row['status']}")
        reviewed_at = iso_utc_now()
        updated = connection.execute(
            """
            UPDATE candidate_memories
            SET status = 'rejected', review_note = ?, approved_memory_uid = NULL, reviewed_at = ?, updated_at = ?
            WHERE candidate_uid = ? AND status = 'pending'
            """,
            (note, reviewed_at, reviewed_at, candidate_uid),
        )
        if (updated.rowcount or 0) != 1:
            raise HTTPException(status_code=409, detail="candidate rejection conflict")
        return {"candidate_uid": candidate_uid}

    def approve_candidate(candidate_uid: str, note: str | None) -> dict[str, Any]:
        with product_store.db.transaction() as connection:
            return approve_candidate_in_transaction(connection, candidate_uid, note)

    def reject_candidate(candidate_uid: str, note: str | None) -> dict[str, Any]:
        with product_store.db.transaction() as connection:
            return reject_candidate_in_transaction(connection, candidate_uid, note)

    def active_scope_clause(scope: dict[str, Any] | None, *, user_column: str = "user_id", conversation_column: str = "conversation_id") -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if scope is None:
            return clauses, params
        if scope.get("user_id"):
            clauses.append(f"{user_column} = ?")
            params.append(scope["user_id"])
        if scope.get("conversation_id"):
            clauses.append(f"{conversation_column} = ?")
            params.append(scope["conversation_id"])
        return clauses, params

    def message_model(record: Any) -> MobileMessageModel:
        return MobileMessageModel(
            id=record.id,
            platform=record.platform,
            conversation_id=record.conversation_id,
            session_id=record.session_id,
            platform_message_id=record.platform_message_id,
            sender_type=record.sender_type,
            author_id=record.author_id,
            user_id=record.user_id,
            channel_id=record.channel_id,
            guild_id=record.guild_id,
            reply_to_platform_message_id=record.reply_to_platform_message_id,
            thread_id=record.thread_id,
            content=record.content,
            metadata=record.metadata,
            created_at=record.created_at,
        )

    def attachment_item_from_insight(insight: AttachmentInsight) -> MobileAttachmentItem:
        return MobileAttachmentItem(
            filename=insight.filename,
            artifact_type=insight.artifact_type,
            content_type=insight.content_type,
            extracted_text=insight.extracted_text,
            summary_text=insight.summary_text,
            truncated=insight.truncated,
            metadata=insight.metadata,
        )

    def attachment_insight_from_item(item: dict[str, Any]) -> AttachmentInsight:
        return AttachmentInsight(
            filename=str(item.get("filename") or "attachment"),
            artifact_type=str(item.get("artifact_type") or "document"),
            content_type=None if item.get("content_type") is None else str(item.get("content_type")),
            extracted_text=str(item.get("extracted_text") or ""),
            summary_text=str(item.get("summary_text") or ""),
            truncated=bool(item.get("truncated")),
            metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
        )

    def generated_image_url_from_path(raw_path: Any) -> str | None:
        if not raw_path:
            return None
        safe_name = Path(str(raw_path)).name
        if not safe_name:
            return None
        return f"/mobile/generated-images/{safe_name}"

    def mobile_scene_state(
        *,
        presence_payload: dict[str, Any],
        companion_payload: dict[str, Any],
        reality_payload: dict[str, Any],
    ) -> MobileSceneState:
        now = datetime.now(timezone.utc)
        hour = datetime.now().hour
        key = "late-night"
        reason = "time"
        status_line = "夜里学姐把灯压低一点，位置还给你留着。"
        if 6 <= hour < 12:
            key = "morning"
            status_line = "学姐在桌边等你醒过来，先陪你把今天稳住。"
        elif 12 <= hour < 18:
            key = "afternoon"
            status_line = "午后的光慢下来，学姐还在等你一句回声。"
        elif 18 <= hour < 23:
            key = "evening"
            status_line = "灯亮起来了，学姐把语气放轻一点陪你。"

        reality_text = json_dumps(reality_payload).lower()
        companion_text = json_dumps(companion_payload).lower()
        presence_text = json_dumps(presence_payload).lower()
        if any(token in reality_text for token in ("rain", "雨", "precipitation")):
            key = "rain"
            reason = "weather"
            status_line = "外面像有雨，学姐把这一会儿替你收得安静些。"
        if any(token in companion_text for token in ("study", "学习", "专注")):
            key = "focus"
            reason = "companion_day"
            status_line = "学姐把书页摊开了，陪你慢慢进入状态。"
        if any(token in presence_text for token in ("waiting", "想念", "longing", "miss")):
            key = "waiting"
            reason = "presence"
            status_line = "学姐没有催你，只是认真地等你回来。"

        return MobileSceneState(
            key=key,
            asset_name=f"scene-{key}",
            status_line=status_line,
            reason=reason,
            updated_at=now.isoformat(),
        )

    def mobile_dashboard_groups() -> list[MobileDashboardGroup]:
        return [
            MobileDashboardGroup(
                id="companion",
                title="陪伴状态",
                subtitle="学姐当前在场感、模式和一天安排",
                panels=["overview", "presence", "companion-day", "modes"],
            ),
            MobileDashboardGroup(
                id="memory",
                title="记忆与上下文",
                subtitle="长期记忆、候选、事实、关系和摘要",
                panels=[
                    "search",
                    "memories",
                    "candidates",
                    "snapshots",
                    "facts",
                    "relationships",
                    "summaries",
                    "shared-diary",
                    "attachments",
                ],
            ),
            MobileDashboardGroup(
                id="reality",
                title="主动与现实锚点",
                subtitle="主动消息、现实位置、日程和会话 scope",
                panels=["proactive", "reality-context", "scopes"],
            ),
            MobileDashboardGroup(
                id="ops",
                title="运行排查",
                subtitle="Turn、任务、错误、健康、性能和日志",
                panels=["turns", "tasks", "errors", "health", "performance", "logs"],
            ),
            MobileDashboardGroup(
                id="security",
                title="安全审计",
                subtitle="安全状态、审计记录和可撤销操作",
                panels=["security", "audits"],
            ),
        ]

    def mobile_timeline_attachments_from_metadata(metadata: dict[str, Any]) -> list[MobileTimelineAttachment]:
        raw_items = metadata.get("attachments")
        if not isinstance(raw_items, list):
            return []
        attachments: list[MobileTimelineAttachment] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            attachments.append(
                MobileTimelineAttachment(
                    filename=str(raw.get("filename") or "attachment"),
                    artifact_type=str(raw.get("artifact_type") or "document"),
                    content_type=None if raw.get("content_type") is None else str(raw.get("content_type")),
                    summary_text=str(raw.get("summary_text") or raw.get("extracted_text") or ""),
                    metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
                )
            )
        return attachments

    def mobile_message_timeline_item(record: Any) -> MobileTimelineItem:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        image_url = generated_image_url_from_path(metadata.get("generated_image_path"))
        kind = "generated_image" if image_url else "message"
        return MobileTimelineItem(
            id=f"message:{record.id}",
            kind=kind,
            created_at=record.created_at,
            content=record.content,
            sender_label="你" if record.sender_type == "user" else "学姐",
            message_id=record.id,
            attachments=mobile_timeline_attachments_from_metadata(metadata),
            generated_image_url=image_url,
            metadata={
                "sender_type": record.sender_type,
                "platform": record.platform,
                "request_type": metadata.get("request_type"),
                "scene": metadata.get("scene"),
                "source": metadata.get("source"),
            },
        )

    def mobile_proactive_timeline_item(item: Any) -> MobileTimelineItem:
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        return MobileTimelineItem(
            id=f"proactive:{item.proactive_uid}",
            kind="proactive",
            created_at=item.sent_at,
            content=item.opening_text,
            sender_label="学姐",
            proactive_uid=item.proactive_uid,
            feedback={
                "status": item.status,
                "accepted": item.accepted,
                "cold_response": item.cold_response,
                "response_message_id": item.response_message_id,
                "response_latency_minutes": item.response_latency_minutes,
            },
            metadata={
                **metadata,
                "trigger_type": item.trigger_type,
                "channel_id": item.channel_id,
            },
        )

    def timeline_sort_key(item: MobileTimelineItem) -> tuple[float, str]:
        parsed = parse_iso8601(item.created_at)
        if parsed is None:
            return (0.0, item.id)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (parsed.timestamp(), item.id)

    def mobile_upload_key(upload_uid: str) -> str:
        return f"mobile_upload:{upload_uid}"

    def load_mobile_attachment_insights(upload_uids: list[str]) -> list[AttachmentInsight]:
        insights: list[AttachmentInsight] = []
        for upload_uid in upload_uids:
            value = product_store.get_app_setting(mobile_upload_key(upload_uid), None)
            if not isinstance(value, dict):
                continue
            for item in value.get("items") or []:
                if isinstance(item, dict):
                    insights.append(attachment_insight_from_item(item))
        return insights

    def resolve_mobile_scope() -> tuple[dict[str, Any] | None, ConversationScope]:
        snapshot = current_scope_snapshot()
        if snapshot is not None:
            return snapshot, conversation_scope_from_snapshot(snapshot)
        user_id = settings.single_user_id or "primary_user"
        channel_id = "mobile-main"
        conversation_id = SessionStateManager.build_conversation_id(
            "mobile",
            user_id=user_id,
            channel_id=channel_id,
            guild_id=None,
        )
        scope = ConversationScope(
            platform="mobile",
            conversation_id=conversation_id,
            user_id=user_id,
            channel_id=channel_id,
            guild_id=None,
            session_id="mobile-main",
        )
        return None, scope

    def mobile_sse(event: dict[str, Any]) -> str:
        event_name = str(event.get("event") or "message")
        return f"event: {event_name}\ndata: {json_dumps(event)}\n\n"

    async def fallback_mobile_stream(scope: ConversationScope, body: MobileChatRequest):
        user_text = compact_text(body.content) or "我发了一个附件给你。"
        user_platform_id = body.client_message_id or f"mobile_user_{secrets.token_urlsafe(12)}"
        user_message = memory_store.insert_message(
            scope,
            sender_type="user",
            content=user_text,
            context=MessageContext(
                platform_message_id=user_platform_id,
                author_id="mobile-user",
            ),
            metadata={"display_name": body.display_name, "source": "mobile_fallback"},
        )
        reply_text = "我收到你从手机端发来的消息了。现在完整陪伴服务还没有注入到这个测试 App 里，但这条移动链路是通的。"
        assistant_message = memory_store.insert_message(
            scope,
            sender_type="assistant",
            content=reply_text,
            context=MessageContext(
                platform_message_id=f"mobile_assistant_{secrets.token_urlsafe(12)}",
                author_id="shen-zhiwei",
                reply_to_platform_message_id=user_platform_id,
            ),
            metadata={"source": "mobile_fallback"},
        )
        yield {
            "event": "ack",
            "conversation_id": scope.conversation_id,
            "user_message_id": user_message.id,
        }
        yield {
            "event": "delta",
            "text": reply_text,
            "full_text": reply_text,
            "is_final": True,
        }
        yield {
            "event": "final",
            "text": reply_text,
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message.id,
            "model_name": "mobile-fallback",
            "fallback_used": True,
        }

    @app.get("/login", response_class=HTMLResponse)
    async def dashboard_login(request: Request) -> Response:
        if settings.dashboard_auth_enabled and session_value(request, "dashboard_authenticated"):
            return RedirectResponse("/", status_code=303)
        return render_login_page(request)

    @app.post("/api/login", response_model=LoginResponse)
    async def dashboard_login_api(request: Request, body: LoginRequest) -> LoginResponse:
        username = body.username.strip()
        password = body.password
        source_ip = request_source_ip(request)
        lock_state = product_store.get_dashboard_lock_status(
            source_ip=source_ip,
            window_seconds=settings.dashboard_login_window_seconds,
            max_attempts=settings.dashboard_login_max_attempts,
            lockout_seconds=settings.dashboard_login_lockout_seconds,
        )
        if lock_state["locked"]:
            product_store.record_dashboard_security_event(
                event_type="login_locked",
                username=username or settings.dashboard_auth_username,
                source_ip=source_ip,
                success=False,
                details={"reason": "rate_limited"},
                locked_until=lock_state["locked_until"],
            )
            raise HTTPException(status_code=429, detail="too many login attempts, try again later")
        if not secrets.compare_digest(username, settings.dashboard_auth_username) or not dashboard_password_is_valid(password):
            product_store.record_dashboard_security_event(
                event_type="login_failure",
                username=username or settings.dashboard_auth_username,
                source_ip=source_ip,
                success=False,
                details={"reason": "invalid_credentials"},
            )
            raise HTTPException(status_code=401, detail="invalid dashboard credentials")
        issue_dashboard_session(request)
        product_store.record_dashboard_security_event(
            event_type="login_success",
            username=settings.dashboard_auth_username,
            source_ip=source_ip,
            success=True,
            details={"force_password_change": bool(session_value(request, "force_password_change", False))},
        )
        return LoginResponse(
            ok=True,
            username=settings.dashboard_auth_username,
            csrf_token=session_csrf_token(request),
            force_password_change=bool(session_value(request, "force_password_change", False)),
        )

    @app.post("/api/logout", response_model=ActionResponse)
    async def dashboard_logout(request: Request) -> ActionResponse:
        product_store.record_dashboard_security_event(
            event_type="logout",
            username=session_username(request),
            source_ip=request_source_ip(request),
            success=True,
            details={},
        )
        clear_dashboard_session(request)
        return ActionResponse(ok=True, message="已退出登录。")

    @app.post("/api/account/password", response_model=ActionResponse)
    async def update_dashboard_password(request: Request, body: PasswordChangeRequest) -> ActionResponse:
        if body.new_password != body.confirm_password:
            raise HTTPException(status_code=422, detail="new password confirmation does not match")
        if len(body.new_password.strip()) < settings.dashboard_password_min_length:
            raise HTTPException(
                status_code=422,
                detail=f"new password must be at least {settings.dashboard_password_min_length} characters",
            )
        if not dashboard_password_is_valid(body.old_password):
            raise HTTPException(status_code=401, detail="old password is incorrect")
        if dashboard_password_is_valid(body.new_password):
            raise HTTPException(status_code=422, detail="new password must be different from the current password")
        product_store.set_dashboard_password_hash(hash_dashboard_password(body.new_password.strip()))
        product_store.set_dashboard_password_change_required(False)
        if settings.dashboard_auth_enabled:
            request.session["force_password_change"] = False
        source_ip = request_source_ip(request)
        product_store.record_dashboard_security_event(
            event_type="password_change",
            username=session_username(request),
            source_ip=source_ip,
            success=True,
            details={"force_password_change_cleared": True},
        )
        audit_action(
            request,
            action_type="password_change",
            target_type="dashboard_account",
            target_id=session_username(request),
            details={"source": "dashboard"},
        )
        return ActionResponse(ok=True, message="密码已更新。")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_home(request: Request) -> HTMLResponse:
        return render_dashboard_page(request)

    @app.get("/api/overview", response_model=OverviewResponse)
    async def overview() -> OverviewResponse:
        scope = current_scope_snapshot()
        overview_payload = product_store.get_overview(user_id=None if scope is None else scope["user_id"])
        overview_payload["active_scope_name"] = None if scope is None else scope["display_name"]
        overview_payload["active_scope_id"] = None if scope is None else scope["conversation_id"]
        return OverviewResponse(
            active_scope=None if scope is None else ScopeSnapshotModel.model_validate(scope),
            overview=overview_payload,
            quick_links=[
                {"tab": "search", "label": "全局搜索"},
                {"tab": "memories", "label": "长期记忆"},
                {"tab": "candidates", "label": "候选记忆"},
                {"tab": "shared-diary", "label": "共享日记"},
                {"tab": "performance", "label": "性能成本"},
                {"tab": "errors", "label": "错误闭环"},
            ],
            refreshed_at=iso_utc_now(),
        )

    @app.get("/api/scopes", response_model=ScopesResponse)
    async def scopes() -> ScopesResponse:
        active_scope = current_scope_snapshot()
        items = [ScopeSnapshotModel.model_validate(item) for item in product_store.list_dashboard_scopes(limit=20)]
        return ScopesResponse(
            active_scope=None if active_scope is None else ScopeSnapshotModel.model_validate(active_scope),
            items=items,
            refreshed_at=iso_utc_now(),
        )

    @app.post("/api/scopes/active", response_model=ActionResponse)
    async def update_active_scope(request: Request, body: ScopeUpdateRequest) -> ActionResponse:
        snapshot = product_store.get_scope_snapshot(user_id=body.user_id, conversation_id=body.conversation_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="scope not found")
        product_store.set_dashboard_active_scope(
            user_id=snapshot["user_id"],
            conversation_id=snapshot["conversation_id"],
            channel_id=snapshot["channel_id"],
            guild_id=snapshot["guild_id"],
        )
        audit_action(
            request,
            action_type="scope_change",
            target_type="conversation_scope",
            target_id=snapshot["conversation_id"],
            details={"display_name": snapshot["display_name"]},
            scope=snapshot,
        )
        return ActionResponse(
            ok=True,
            message=f"已切换到 {snapshot['display_name']}。",
            active_scope=ScopeSnapshotModel.model_validate(snapshot),
        )

    @app.get("/api/security", response_model=SecurityResponse)
    async def security() -> SecurityResponse:
        return SecurityResponse(
            metrics=product_store.get_dashboard_security_metrics(
                window_seconds=settings.dashboard_login_window_seconds,
                max_attempts=settings.dashboard_login_max_attempts,
                lockout_seconds=settings.dashboard_login_lockout_seconds,
            ),
            events=product_store.list_dashboard_security_events(limit=40),
            password_policy={
                "min_length": settings.dashboard_password_min_length,
                "change_required": product_store.dashboard_password_change_required(
                    generated_password_in_use=settings.dashboard_auth_password_generated,
                ),
                "session_https_only": settings.dashboard_session_https_only,
                "generated_bootstrap_password": settings.dashboard_auth_password_generated
                and product_store.get_dashboard_password_hash() is None,
            },
            audits=product_store.list_dashboard_action_audits(limit=20),
            refreshed_at=iso_utc_now(),
        )

    @app.get("/api/audits", response_model=PanelEnvelope)
    async def audits(
        q: str = "",
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=60),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size)
        normalized_q = _normalize_q(q)
        clauses = ["1 = 1"]
        params: list[Any] = []
        search_clause, search_params = _build_text_search(
            normalized_q,
            ["actor_username", "action_type", "target_type", "target_id", "details_json"],
        )
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM dashboard_action_audits WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="created_at DESC",
            page=page,
            page_size=page_size,
        )
        items = [_serialize_audit_row(row) for row in rows]
        return _build_panel_response(
            active_scope=current_scope_snapshot(),
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            summary={"undoable_count": sum(1 for item in items if item["undo_available"])},
        )

    @app.get("/api/logs", response_model=PanelEnvelope)
    async def logs(
        q: str = "",
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=400),
        lines: Optional[int] = Query(None, ge=0),
    ) -> PanelEnvelope:
        normalized_q = _normalize_q(q)
        if lines is not None:
            page_size = min(lines, settings.dashboard_log_max_lines)
        page, page_size = _normalize_page(page, page_size, max_size=settings.dashboard_log_max_lines)
        all_lines = product_store.tail_log_file(settings.log_file_path, lines=settings.dashboard_log_max_lines, redact=True)
        line_items = [{"line_no": index + 1, "text": line.rstrip("\n")} for index, line in enumerate(all_lines)]
        if normalized_q:
            line_items = [item for item in line_items if normalized_q.lower() in item["text"].lower()]
        total = len(line_items)
        offset = (page - 1) * page_size
        paged = line_items[offset : offset + page_size]
        return _build_panel_response(
            active_scope=current_scope_snapshot(),
            items=paged,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            summary={
                "download_url": f"/api/logs/download?q={normalized_q}",
                "total_visible": total,
            },
        )

    @app.get("/api/logs/download")
    async def download_logs(q: str = "") -> PlainTextResponse:
        normalized_q = _normalize_q(q)
        lines = product_store.tail_log_file(settings.log_file_path, lines=settings.dashboard_log_max_lines, redact=True)
        if normalized_q:
            lines = [line for line in lines if normalized_q.lower() in line.lower()]
        response = PlainTextResponse("".join(lines))
        response.headers["Content-Disposition"] = 'attachment; filename="zhiwei-dashboard.log"'
        return response

    @app.get("/api/search", response_model=GlobalSearchResponse)
    async def search_everything(q: str = Query("", min_length=0, max_length=120)) -> GlobalSearchResponse:
        normalized_q = _normalize_q(q)
        if not normalized_q:
            return GlobalSearchResponse(query="", groups=[], total_hits=0, refreshed_at=iso_utc_now())
        scope = current_scope_snapshot()
        groups: list[dict[str, Any]] = []

        memory_rows = product_store.db.fetchall(
            """
            SELECT memory_uid, memory_type, category, content, updated_at
            FROM long_term_memories
            WHERE status = 'active' AND user_id = ?
              AND (memory_uid LIKE ? OR memory_type LIKE ? OR category LIKE ? OR content LIKE ?)
            ORDER BY updated_at DESC
            LIMIT 5
            """,
            (scope["user_id"] if scope else "", f"%{normalized_q}%", f"%{normalized_q}%", f"%{normalized_q}%", f"%{normalized_q}%"),
        )
        groups.append(
            {
                "key": "memories",
                "label": "长期记忆",
                "items": [
                    {
                        "id": row["memory_uid"],
                        "title": f"{row['memory_type']} / {row['category']}",
                        "preview": truncate_text(row["content"], 100),
                        "updated_at": row["updated_at"],
                    }
                    for row in memory_rows
                ],
            }
        )

        turn_rows = product_store.db.fetchall(
            """
            SELECT turn_uid, scene, request_type, user_input, assistant_reply, created_at
            FROM turn_traces
            WHERE conversation_id = ?
              AND (turn_uid LIKE ? OR user_input LIKE ? OR assistant_reply LIKE ? OR scene LIKE ?)
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (
                scope["conversation_id"] if scope else "",
                f"%{normalized_q}%",
                f"%{normalized_q}%",
                f"%{normalized_q}%",
                f"%{normalized_q}%",
            ),
        )
        groups.append(
            {
                "key": "turns",
                "label": "对话 Trace",
                "items": [
                    {
                        "id": row["turn_uid"],
                        "title": f"{row['scene']} / {row['request_type']}",
                        "preview": truncate_text(f"{row['user_input']} {row['assistant_reply']}", 100),
                        "updated_at": row["created_at"],
                    }
                    for row in turn_rows
                ],
            }
        )

        error_rows = product_store.db.fetchall(
            """
            SELECT error_uid, component, message, status, created_at
            FROM error_events
            WHERE error_uid LIKE ? OR component LIKE ? OR message LIKE ? OR details_json LIKE ?
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (f"%{normalized_q}%", f"%{normalized_q}%", f"%{normalized_q}%", f"%{normalized_q}%"),
        )
        groups.append(
            {
                "key": "errors",
                "label": "错误事件",
                "items": [
                    {
                        "id": row["error_uid"],
                        "title": f"{row['component']} / {row['status']}",
                        "preview": truncate_text(row["message"], 100),
                        "updated_at": row["created_at"],
                    }
                    for row in error_rows
                ],
            }
        )
        total_hits = sum(len(group["items"]) for group in groups)
        return GlobalSearchResponse(query=normalized_q, groups=groups, total_hits=total_hits, refreshed_at=iso_utc_now())

    @app.get("/api/performance", response_model=PerformanceResponse)
    async def performance(scope_mode: str = "all") -> PerformanceResponse:
        active_scope = current_scope_snapshot()
        conv_id = active_scope["conversation_id"] if scope_mode == "active" and active_scope else None
        turns = product_store.list_recent_turns(
            conversation_id=conv_id,
            limit=160,
        )
        performance_summary = product_store.get_performance_summary(limit=160, conversation_id=conv_id)
        experience_summary = product_store.get_experience_summary(limit=160, conversation_id=conv_id)
        latencies = [turn.latency_ms for turn in turns]
        percentiles = {}
        if latencies:
            sorted_latencies = sorted(latencies)
            for label, ratio in (("p50", 0.5), ("p95", 0.95), ("p99", 0.99)):
                index = min(max(math.ceil(len(sorted_latencies) * ratio) - 1, 0), len(sorted_latencies) - 1)
                percentiles[label] = round(sorted_latencies[index], 2)
        costs_by_model: dict[str, dict[str, float]] = {}
        stage_totals: dict[str, float] = {}
        for turn in turns:
            metrics = turn.metrics
            model_name = turn.model_name or "unknown"
            bucket = costs_by_model.setdefault(model_name, {"turns": 0.0, "cost_usd": 0.0, "tokens": 0.0})
            bucket["turns"] += 1
            bucket["cost_usd"] += float(metrics.get("estimated_cost_usd", 0.0) or 0.0)
            bucket["tokens"] += float(metrics.get("estimated_total_tokens", 0.0) or 0.0)
            for stage, value in (metrics.get("stage_latency_ms") or {}).items():
                stage_totals[stage] = stage_totals.get(stage, 0.0) + float(value)
        performance_summary["percentiles_ms"] = percentiles
        performance_summary["cost_by_model"] = {
            model: {
                "turns": int(values["turns"]),
                "cost_usd": round(values["cost_usd"], 6),
                "avg_tokens": round(values["tokens"] / max(values["turns"], 1), 2),
            }
            for model, values in costs_by_model.items()
        }
        performance_summary["stage_latency_avg_ms"] = {
            stage: round(total / max(len(turns), 1), 2)
            for stage, total in stage_totals.items()
        }
        performance_summary["scope_mode"] = scope_mode
        return PerformanceResponse(
            performance=performance_summary,
            experience=experience_summary,
            json_extraction=get_json_extraction_stats(),
            refreshed_at=iso_utc_now(),
        )

    @app.get("/api/tasks", response_model=PanelEnvelope)
    async def tasks(
        q: str = "",
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        scope_mode: str = "active",
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=60),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size)
        normalized_q = _normalize_q(q)
        scope = current_scope_snapshot()
        clauses = ["1 = 1"]
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if task_type:
            clauses.append("task_type = ?")
            params.append(task_type)
        if scope_mode == "active" and scope:
            clauses.append("conversation_id = ?")
            params.append(scope["conversation_id"])
        search_clause, search_params = _build_text_search(normalized_q, ["task_uid", "task_type", "payload_json", "last_error"])
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM background_tasks WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="created_at DESC",
            page=page,
            page_size=page_size,
        )
        items = [_serialize_task_row(row) for row in rows]
        return _build_panel_response(
            active_scope=scope,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            filters={"status": status or "", "task_type": task_type or "", "scope_mode": scope_mode},
            summary={"retrying": sum(1 for item in items if item["status"] == "retrying")},
        )

    @app.get("/api/memories", response_model=PanelEnvelope)
    async def memories(
        q: str = "",
        sort: str = "importance",
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=60),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size)
        normalized_q = _normalize_q(q)
        scope = current_scope_snapshot()
        if scope is None:
            return _build_panel_response(active_scope=None, items=[], total=0, page=page, page_size=page_size)
        order_map = {
            "importance": "ltm.importance DESC, ltm.updated_at DESC",
            "updated": "ltm.updated_at DESC",
            "hits": "COALESCE(mus.hit_count, 0) DESC, ltm.updated_at DESC",
            "last_used": "ltm.last_used_at DESC, ltm.updated_at DESC",
        }
        order_by = order_map.get(sort, order_map["importance"])
        clauses = ["ltm.status = 'active'", "ltm.user_id = ?"]
        params: list[Any] = [scope["user_id"]]
        search_clause, search_params = _build_text_search(
            normalized_q,
            ["ltm.memory_uid", "ltm.memory_type", "ltm.category", "ltm.content", "ltm.tags_json", "ltm.metadata_json"],
        )
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="ltm.*, mus.hit_count, mus.last_hit_at",
            from_clause=(
                "FROM long_term_memories ltm "
                "LEFT JOIN memory_usage_stats mus ON mus.memory_uid = ltm.memory_uid "
                f"WHERE {' AND '.join(clauses)}"
            ),
            params=params,
            order_by=order_by,
            page=page,
            page_size=page_size,
        )
        items = [_serialize_memory_row(row) for row in rows]
        top_hits = product_store.list_top_memory_hits(scope["user_id"], limit=8)
        return _build_panel_response(
            active_scope=scope,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            sort=sort,
            highlights={"top_hits": top_hits},
            summary={"sort_options": list(order_map.keys())},
        )

    @app.post("/api/memories/{memory_uid}/archive", response_model=ActionResponse)
    async def archive_memory(request: Request, memory_uid: str) -> ActionResponse:
        memory = product_store.get_long_term_memory(memory_uid)
        if memory is None:
            raise HTTPException(status_code=404, detail="memory not found")
        if memory["status"] != "active":
            raise HTTPException(status_code=409, detail="memory is not active")
        if not product_store.archive_long_term_memory(memory_uid):
            raise HTTPException(status_code=409, detail="memory archive failed")
        audit_action(
            request,
            action_type="memory_archive",
            target_type="long_term_memory",
            target_id=memory_uid,
            details={"content_preview": truncate_text(memory["content"], 80)},
            undo_available=True,
            undo_payload={"memory_uid": memory_uid},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(ok=True, message="长期记忆已归档。", item_id=memory_uid)

    @app.post("/api/memories/{memory_uid}/restore", response_model=ActionResponse)
    async def restore_memory(request: Request, memory_uid: str) -> ActionResponse:
        memory = product_store.get_long_term_memory(memory_uid)
        if memory is None:
            raise HTTPException(status_code=404, detail="memory not found")
        if memory["status"] != "archived":
            raise HTTPException(status_code=409, detail="memory is not archived")
        if not product_store.restore_long_term_memory(memory_uid):
            raise HTTPException(status_code=409, detail="memory restore failed")
        audit_action(
            request,
            action_type="memory_restore",
            target_type="long_term_memory",
            target_id=memory_uid,
            details={"content_preview": truncate_text(memory["content"], 80)},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(ok=True, message="长期记忆已恢复。", item_id=memory_uid)

    @app.get("/api/candidates", response_model=PanelEnvelope)
    async def candidates(
        q: str = "",
        status: str = "pending",
        memory_type: Optional[str] = None,
        category: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=60),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size)
        normalized_q = _normalize_q(q)
        scope = current_scope_snapshot()
        clauses = ["1 = 1"]
        params: list[Any] = []
        if scope:
            clauses.append("user_id = ?")
            params.append(scope["user_id"])
            clauses.append("conversation_id = ?")
            params.append(scope["conversation_id"])
        if status != "all":
            clauses.append("status = ?")
            params.append(status)
        if memory_type:
            clauses.append("memory_type = ?")
            params.append(memory_type)
        if category:
            clauses.append("category = ?")
            params.append(category)
        search_clause, search_params = _build_text_search(
            normalized_q,
            ["candidate_uid", "memory_type", "category", "content", "reason", "review_note"],
        )
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM candidate_memories WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="updated_at DESC",
            page=page,
            page_size=page_size,
        )
        items = [_serialize_candidate_row(row) for row in rows]
        dedupe_rows = product_store.db.fetchall(
            f"""
            SELECT dedupe_signature, COUNT(*) AS item_count, MAX(updated_at) AS updated_at
            FROM candidate_memories
            WHERE {' AND '.join(clauses)}
            GROUP BY dedupe_signature
            HAVING COUNT(*) > 1
            ORDER BY item_count DESC, updated_at DESC
            LIMIT 12
            """,
            params,
        )
        groups = [
            {
                "dedupe_signature": row["dedupe_signature"],
                "item_count": int(row["item_count"]),
                "updated_at": row["updated_at"],
            }
            for row in dedupe_rows
        ]
        return _build_panel_response(
            active_scope=scope,
            items=items,
            groups=groups,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            filters={"status": status, "memory_type": memory_type or "", "category": category or ""},
        )

    @app.post("/api/candidates/batch-review", response_model=ActionResponse)
    async def batch_review_candidates(request: Request, body: BatchCandidateReviewRequest) -> ActionResponse:
        action = body.action.strip().lower()
        if action not in ALLOWED_REVIEW_ACTIONS:
            raise HTTPException(status_code=422, detail=f"unsupported review action: {body.action}")
        candidate_uids = [item.strip() for item in body.candidate_uids if item.strip()]
        if not candidate_uids:
            raise HTTPException(status_code=422, detail="candidate_uids cannot be empty")
        processed: list[str] = []
        with product_store.db.transaction() as connection:
            for candidate_uid in candidate_uids:
                if action == "approve":
                    approve_candidate_in_transaction(connection, candidate_uid, body.note)
                else:
                    reject_candidate_in_transaction(connection, candidate_uid, body.note)
                processed.append(candidate_uid)
        audit_action(
            request,
            action_type=f"candidate_batch_{action}",
            target_type="candidate_memory",
            target_id=",".join(processed[:8]),
            details={"count": len(processed), "review_note": body.note},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(
            ok=True,
            message=f"已批量{ '批准' if action == 'approve' else '拒绝' } {len(processed)} 条候选记忆。",
            payload={"candidate_uids": processed},
        )

    @app.post("/api/candidates/{candidate_uid}/approve", response_model=ActionResponse)
    async def approve_candidate_api(request: Request, candidate_uid: str, body: CandidateReviewRequest) -> ActionResponse:
        result = approve_candidate(candidate_uid, body.note)
        audit_action(
            request,
            action_type="candidate_approve",
            target_type="candidate_memory",
            target_id=candidate_uid,
            details={"review_note": body.note},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(
            ok=True,
            message="候选记忆已批准。",
            item_id=candidate_uid,
            payload=result,
        )

    @app.post("/api/candidates/{candidate_uid}/reject", response_model=ActionResponse)
    async def reject_candidate_api(request: Request, candidate_uid: str, body: CandidateReviewRequest) -> ActionResponse:
        reject_candidate(candidate_uid, body.note)
        audit_action(
            request,
            action_type="candidate_reject",
            target_type="candidate_memory",
            target_id=candidate_uid,
            details={"review_note": body.note},
            undo_available=True,
            undo_payload={"candidate_uid": candidate_uid},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(ok=True, message="候选记忆已拒绝。", item_id=candidate_uid)

    @app.post("/api/candidates/{candidate_uid}/reopen", response_model=ActionResponse)
    async def reopen_candidate(request: Request, candidate_uid: str) -> ActionResponse:
        candidate = product_store.get_candidate_memory(candidate_uid)
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        if candidate.status != "rejected":
            raise HTTPException(status_code=409, detail="candidate is not rejected")
        if not product_store.reopen_candidate_memory(candidate_uid):
            raise HTTPException(status_code=409, detail="candidate reopen failed")
        audit_action(
            request,
            action_type="candidate_reopen",
            target_type="candidate_memory",
            target_id=candidate_uid,
            details={"content_preview": truncate_text(candidate.content, 80)},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(ok=True, message="候选记忆已重新打开。", item_id=candidate_uid)

    @app.get("/api/snapshots", response_model=PanelEnvelope)
    async def snapshots(
        q: str = "",
        page: int = Query(1, ge=1),
        page_size: int = Query(12, ge=1, le=40),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size, max_size=40)
        normalized_q = _normalize_q(q)
        scope = current_scope_snapshot()
        clauses = ["1 = 1"]
        params: list[Any] = []
        if scope:
            clauses.append("conversation_id = ?")
            params.append(scope["conversation_id"])
        search_clause, search_params = _build_text_search(normalized_q, ["snapshot_uid", "turn_uid", "snapshot_json"])
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM memory_snapshots WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="created_at DESC",
            page=page,
            page_size=page_size,
        )
        items: list[dict[str, Any]] = []
        previous_snapshot: dict[str, Any] | None = None
        for row in rows:
            item = _serialize_snapshot_row(row, previous_snapshot)
            previous_snapshot = item["snapshot"]
            items.append(item)
        return _build_panel_response(
            active_scope=scope,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
        )

    @app.get("/api/errors", response_model=PanelEnvelope)
    async def errors(
        q: str = "",
        status: Optional[str] = None,
        component: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=60),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size)
        normalized_q = _normalize_q(q)
        clauses = ["1 = 1"]
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if component:
            clauses.append("component = ?")
            params.append(component)
        search_clause, search_params = _build_text_search(normalized_q, ["error_uid", "component", "message", "details_json"])
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM error_events WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="created_at DESC",
            page=page,
            page_size=page_size,
        )
        items = [_serialize_error_row(row) for row in rows]
        status_counts = {
            value: product_store._count("error_events", " WHERE status = ?", (value,))  # noqa: SLF001
            for value in ALLOWED_ERROR_STATUS_VALUES
        }
        return _build_panel_response(
            active_scope=current_scope_snapshot(),
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            filters={"status": status or "", "component": component or ""},
            summary={"status_counts": status_counts},
        )

    @app.post("/api/errors/{error_uid}/status", response_model=ActionResponse)
    async def update_error_status_api(request: Request, error_uid: str, body: ErrorStatusRequest) -> ActionResponse:
        status = body.status.strip().lower()
        if status not in ALLOWED_ERROR_STATUS_VALUES:
            raise HTTPException(status_code=422, detail=f"unsupported error status: {body.status}")
        row = product_store.db.fetchone("SELECT * FROM error_events WHERE error_uid = ? LIMIT 1", (error_uid,))
        if row is None:
            raise HTTPException(status_code=404, detail="error not found")
        if not update_error_status_row(error_uid, status=status):
            raise HTTPException(status_code=409, detail="error status update failed")
        audit_action(
            request,
            action_type="error_status_update",
            target_type="error_event",
            target_id=error_uid,
            details={"status": status, "note": body.note},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(ok=True, message=f"错误已标记为 {status}。", item_id=error_uid)

    @app.get("/api/health", response_model=HealthResponse)
    async def health(history_limit: int = Query(80, ge=10, le=240)) -> HealthResponse:
        latest_items = [asdict(item) for item in product_store.get_latest_health()]
        rows = product_store.db.fetchall(
            """
            SELECT * FROM health_checks
            ORDER BY checked_at DESC
            LIMIT ?
            """,
            (history_limit,),
        )
        trends: dict[str, Any] = {}
        for row in rows:
            bucket = trends.setdefault(
                row["component"],
                {"history": [], "latest_status": row["status"], "latest_message": row["message"]},
            )
            bucket["history"].append(
                {
                    "checked_at": row["checked_at"],
                    "latency_ms": float(row["latency_ms"]),
                    "status": row["status"],
                }
            )
        for bucket in trends.values():
            bucket["history"].reverse()
        return HealthResponse(items=latest_items, trends=trends, refreshed_at=iso_utc_now())

    @app.post("/api/tasks/{task_uid}/retry", response_model=ActionResponse)
    async def retry_task(request: Request, task_uid: str) -> ActionResponse:
        task = product_store.get_task(task_uid)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        if not product_store.retry_task(task_uid):
            raise HTTPException(status_code=409, detail="task cannot be retried")
        audit_action(
            request,
            action_type="task_retry",
            target_type="background_task",
            target_id=task_uid,
            details={"task_type": task.task_type},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(ok=True, message="任务已重新排队。", item_id=task_uid)

    @app.post("/api/tasks/{task_uid}/cancel", response_model=ActionResponse)
    async def cancel_task(request: Request, task_uid: str) -> ActionResponse:
        task = product_store.get_task(task_uid)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        if not product_store.cancel_task(task_uid):
            raise HTTPException(status_code=409, detail="task cannot be cancelled")
        audit_action(
            request,
            action_type="task_cancel",
            target_type="background_task",
            target_id=task_uid,
            details={"task_type": task.task_type},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(ok=True, message="任务已取消。", item_id=task_uid)

    @app.post("/api/tasks/{task_uid}/boost", response_model=ActionResponse)
    async def boost_task(request: Request, task_uid: str, body: TaskPriorityRequest) -> ActionResponse:
        task = product_store.get_task(task_uid)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        priority = max(0.0, min(body.priority, 1.0))
        if not product_store.reprioritize_task(task_uid, priority=priority):
            raise HTTPException(status_code=409, detail="task cannot be reprioritized")
        audit_action(
            request,
            action_type="task_boost",
            target_type="background_task",
            target_id=task_uid,
            details={"task_type": task.task_type, "priority": priority},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(ok=True, message="任务优先级已提升。", item_id=task_uid, payload={"priority": priority})

    @app.get("/api/turns", response_model=PanelEnvelope)
    async def turns(
        q: str = "",
        request_type: Optional[str] = None,
        scene: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=60),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size)
        normalized_q = _normalize_q(q)
        scope = current_scope_snapshot()
        clauses = ["1 = 1"]
        params: list[Any] = []
        if scope:
            clauses.append("conversation_id = ?")
            params.append(scope["conversation_id"])
        if request_type:
            clauses.append("request_type = ?")
            params.append(request_type)
        if scene:
            clauses.append("scene = ?")
            params.append(scene)
        search_clause, search_params = _build_text_search(
            normalized_q,
            ["turn_uid", "scene", "request_type", "user_input", "assistant_reply", "planning_json", "retrieval_json", "metrics_json"],
        )
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM turn_traces WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="created_at DESC",
            page=page,
            page_size=page_size,
        )
        items = [_serialize_turn_row(row) for row in rows]
        return _build_panel_response(
            active_scope=scope,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            filters={"request_type": request_type or "", "scene": scene or ""},
        )

    @app.get("/api/attachments", response_model=PanelEnvelope)
    async def attachments(
        q: str = "",
        artifact_type: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=60),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size)
        normalized_q = _normalize_q(q)
        scope = current_scope_snapshot()
        clauses = ["1 = 1"]
        params: list[Any] = []
        if scope:
            clauses.append("conversation_id = ?")
            params.append(scope["conversation_id"])
        if artifact_type:
            clauses.append("artifact_type = ?")
            params.append(artifact_type)
        search_clause, search_params = _build_text_search(
            normalized_q,
            ["artifact_uid", "filename", "content_type", "artifact_type", "summary_text", "metadata_json"],
        )
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM attachment_artifacts WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="created_at DESC",
            page=page,
            page_size=page_size,
        )
        items = [_serialize_attachment_row(row) for row in rows]
        return _build_panel_response(
            active_scope=scope,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            filters={"artifact_type": artifact_type or ""},
        )

    @app.get("/api/proactive", response_model=PanelEnvelope)
    async def proactive(
        q: str = "",
        status: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=60),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size)
        normalized_q = _normalize_q(q)
        scope = current_scope_snapshot()
        clauses = ["1 = 1"]
        params: list[Any] = []
        if scope:
            clauses.append("user_id = ?")
            params.append(scope["user_id"])
            clauses.append("conversation_id = ?")
            params.append(scope["conversation_id"])
        if status:
            clauses.append("status = ?")
            params.append(status)
        search_clause, search_params = _build_text_search(
            normalized_q,
            ["proactive_uid", "trigger_type", "opening_text", "metadata_json"],
        )
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM proactive_messages WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="sent_at DESC",
            page=page,
            page_size=page_size,
        )
        items = [_serialize_proactive_row(row) for row in rows]
        summary = {}
        if scope:
            _, resolved_scope = current_conversation_scope()
            summary = proactive_preferences_payload(resolved_scope)
        return _build_panel_response(
            active_scope=scope,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            filters={"status": status or ""},
            summary=summary,
        )

    @app.get("/api/proactive/preferences", response_model=ActionResponse)
    async def proactive_preferences() -> ActionResponse:
        scope_snapshot, scope = current_conversation_scope()
        payload = proactive_preferences_payload(scope)
        return ActionResponse(
            ok=True,
            active_scope=ScopeSnapshotModel.model_validate(scope_snapshot),
            payload=payload,
        )

    @app.patch("/api/proactive/preferences", response_model=ActionResponse)
    async def update_proactive_preferences(request: Request, body: ProactivePreferencesRequest) -> ActionResponse:
        scope_snapshot, scope = current_conversation_scope()
        try:
            preferences = set_proactive_preferences(
                settings=settings,
                product_store=product_store,
                memory_store=memory_store,
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                enabled=body.enabled,
                cadence=body.cadence,
                source="dashboard",
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        audit_action(
            request,
            action_type="proactive_preferences_update",
            target_type="proactive_preferences",
            target_id=scope.conversation_id,
            details={"enabled": body.enabled, "cadence": body.cadence},
            scope=scope_snapshot,
        )
        return ActionResponse(
            ok=True,
            message="主动消息设置已更新。",
            item_id=scope.conversation_id,
            active_scope=ScopeSnapshotModel.model_validate(scope_snapshot),
            payload={"preferences": preferences, "gate": proactive_preferences_payload(scope)["gate"]},
        )

    @app.get("/api/presence", response_model=PanelEnvelope)
    async def presence() -> PanelEnvelope:
        scope_snapshot, scope = current_conversation_scope()
        payload = presence_service.build_dashboard_payload(scope)
        trigger_state = payload.get("proactive_trigger_state", {})
        timeline = trigger_state.get("timeline", []) if isinstance(trigger_state, dict) else []
        active_open_loops = list(payload.get("active_open_loops", []))
        return _build_panel_response(
            active_scope=scope_snapshot,
            items=active_open_loops,
            total=len(active_open_loops),
            page=1,
            page_size=max(len(active_open_loops), 1),
            summary={
                "presence_state": payload.get("presence_state", {}),
                "open_loop_state": payload.get("open_loop_state", {}),
                "proactive_trigger_state": trigger_state,
            },
            highlights={"trigger_timeline": timeline[:12]},
        )

    @app.post("/api/presence", response_model=ActionResponse)
    async def update_presence(request: Request, body: PresenceUpdateRequest) -> ActionResponse:
        scope_snapshot, scope = current_conversation_scope()
        patch = body.model_dump(exclude_none=True)
        state = presence_service.apply_manual_update(scope, patch)
        audit_action(
            request,
            action_type="presence_update",
            target_type="presence_state",
            target_id=scope.conversation_id,
            details={key: truncate_text(compact_text(str(value)), 120) for key, value in patch.items()},
            scope=scope_snapshot,
        )
        return ActionResponse(ok=True, message="沉浸状态已更新。", item_id=scope.conversation_id, payload={"presence_state": state})

    @app.get("/api/companion-day", response_model=PanelEnvelope)
    async def companion_day() -> PanelEnvelope:
        scope_snapshot, scope = current_conversation_scope()
        try:
            payload = await day_engine.build_dashboard_payload(scope)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"companion day model unavailable: {type(exc).__name__}") from exc
        events = list(payload.get("events") or [])
        diary = list(payload.get("diary") or [])
        return _build_panel_response(
            active_scope=scope_snapshot,
            items=events,
            total=len(events),
            page=1,
            page_size=max(len(events), 1),
            summary={
                "route": payload.get("route", {}),
                "unanswered_event": payload.get("unanswered_event"),
                "settings": payload.get("settings", {}),
                "diary_count": len(diary),
            },
            highlights={"diary": diary[:12]},
        )

    @app.get("/api/shared-diary", response_model=PanelEnvelope)
    async def shared_diary(
        q: str = "",
        entry_type: Optional[str] = None,
        role_scope: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=60),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size)
        normalized_q = _normalize_q(q)
        scope = current_scope_snapshot()
        clauses = ["1 = 1"]
        params: list[Any] = []
        if scope:
            clauses.append("user_id = ?")
            params.append(scope["user_id"])
            clauses.append("conversation_id = ?")
            params.append(scope["conversation_id"])
        if entry_type:
            clauses.append("entry_type = ?")
            params.append(entry_type)
        if role_scope:
            clauses.append("role_scope = ?")
            params.append(role_scope)
        search_clause, search_params = _build_text_search(
            normalized_q,
            ["diary_uid", "local_date", "entry_type", "title", "content", "role_scope", "source", "tags_json", "metadata_json"],
        )
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM shared_diary_entries WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="created_at DESC, id DESC",
            page=page,
            page_size=page_size,
        )
        items = [_serialize_shared_diary_row(row) for row in rows]
        unique_dates = sorted({item["local_date"] for item in items if item.get("local_date")}, reverse=True)
        type_counts: dict[str, int] = {}
        for item in items:
            item_type = str(item.get("entry_type") or "unknown")
            type_counts[item_type] = type_counts.get(item_type, 0) + 1
        return _build_panel_response(
            active_scope=scope,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            filters={"entry_type": entry_type or "", "role_scope": role_scope or ""},
            summary={
                "visible_dates": unique_dates[:8],
                "visible_type_counts": type_counts,
                "active_scope_name": None if scope is None else scope["display_name"],
            },
        )

    @app.patch("/api/companion-day", response_model=ActionResponse)
    async def update_companion_day(request: Request, body: CompanionDayUpdateRequest) -> ActionResponse:
        scope_snapshot, scope = current_conversation_scope()
        patch = body.model_dump(exclude_none=True)
        try:
            route = await day_engine.apply_manual_update(scope, patch)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"companion day model unavailable: {type(exc).__name__}") from exc
        audit_action(
            request,
            action_type="companion_day_update",
            target_type="companion_day_route",
            target_id=str(route.get("route_uid") or scope.conversation_id),
            details={key: truncate_text(compact_text(str(value)), 120) for key, value in patch.items()},
            scope=scope_snapshot,
        )
        return ActionResponse(ok=True, message="她的一天已更新。", item_id=str(route.get("route_uid")), payload={"route": route})

    @app.post("/api/companion-day/regenerate", response_model=ActionResponse)
    async def regenerate_companion_day(request: Request) -> ActionResponse:
        scope_snapshot, scope = current_conversation_scope()
        try:
            route = await day_engine.get_or_create_route(scope, force_regenerate=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"companion day model unavailable: {type(exc).__name__}") from exc
        audit_action(
            request,
            action_type="companion_day_regenerate",
            target_type="companion_day_route",
            target_id=str(route.get("route_uid") or scope.conversation_id),
            details={"local_date": route.get("local_date"), "note": "manual regenerate"},
            scope=scope_snapshot,
        )
        return ActionResponse(ok=True, message="今天路线已重生成，旧事件仍保留审计。", item_id=str(route.get("route_uid")), payload={"route": route})

    @app.post("/api/companion-day/events/{event_uid}/feedback", response_model=ActionResponse)
    async def companion_day_event_feedback(request: Request, event_uid: str, body: CompanionDayFeedbackRequest) -> ActionResponse:
        feedback = body.feedback.strip().lower()
        if feedback not in {"good", "too_frequent", "bad", "too_much", "not_enough"}:
            raise HTTPException(status_code=422, detail="feedback must be good, too_frequent, bad, too_much, or not_enough")
        try:
            event = day_engine.record_event_feedback(event_uid, feedback=feedback, note=body.note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="companion day event not found") from exc
        audit_action(
            request,
            action_type="companion_day_feedback",
            target_type="companion_day_event",
            target_id=event_uid,
            details={"feedback": feedback, "note": body.note or ""},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(ok=True, message="她的一天反馈已记录。", item_id=event_uid, payload={"event": event})

    @app.get("/api/reality-context", response_model=PanelEnvelope)
    async def reality_context() -> PanelEnvelope:
        scope_snapshot, scope = current_conversation_scope()
        payload = reality_service.build_dashboard_payload(scope)
        events = list(payload.get("items") or [])
        return _build_panel_response(
            active_scope=scope_snapshot,
            items=events,
            total=len(events),
            page=1,
            page_size=max(len(events), 1),
            summary=payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
            highlights=payload.get("highlights") if isinstance(payload.get("highlights"), dict) else {},
        )

    @app.post("/api/reality-context/refresh", response_model=ActionResponse)
    async def refresh_reality_context(request: Request) -> ActionResponse:
        scope_snapshot, scope = current_conversation_scope()
        payload = await reality_service.refresh_now(scope)
        audit_action(
            request,
            action_type="reality_context_refresh",
            target_type="reality_context",
            target_id=scope.conversation_id,
            details={"manual": True},
            scope=scope_snapshot,
        )
        return ActionResponse(ok=True, message="现实锚点已刷新。", item_id=scope.conversation_id, payload=payload)

    @app.patch("/api/reality-context/location", response_model=ActionResponse)
    async def update_reality_location(request: Request, body: RealityLocationRequest) -> ActionResponse:
        scope_snapshot, scope = current_conversation_scope()
        location = reality_service.update_location(
            scope,
            label=body.label,
            latitude=body.latitude,
            longitude=body.longitude,
            note=body.note,
        )
        audit_action(
            request,
            action_type="reality_location_update",
            target_type="reality_location",
            target_id=scope.conversation_id,
            details={"label": location["label"], "latitude": location["latitude"], "longitude": location["longitude"]},
            scope=scope_snapshot,
        )
        return ActionResponse(ok=True, message="现实地点已更新。", item_id=scope.conversation_id, payload={"location": location})

    @app.post("/api/reality-context/calendar-sources", response_model=ActionResponse)
    async def add_reality_calendar_source(request: Request, body: RealityCalendarSourceRequest) -> ActionResponse:
        scope_snapshot, scope = current_conversation_scope()
        try:
            source = reality_service.add_calendar_source(
                scope,
                url=body.url,
                label=body.label or "",
                enabled=body.enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        audit_action(
            request,
            action_type="reality_calendar_source_upsert",
            target_type="calendar_source",
            target_id=str(source.get("source_uid") or scope.conversation_id),
            details={key: source.get(key) for key in ("label", "enabled", "masked_url")},
            scope=scope_snapshot,
        )
        return ActionResponse(ok=True, message="日历订阅已保存。", item_id=str(source.get("source_uid")), payload={"source": source})

    @app.patch("/api/reality-context/calendar-sources/{source_uid}", response_model=ActionResponse)
    async def toggle_reality_calendar_source(
        request: Request,
        source_uid: str,
        body: RealityCalendarSourceToggleRequest,
    ) -> ActionResponse:
        scope_snapshot, scope = current_conversation_scope()
        changed = reality_service.set_calendar_source_enabled(scope, source_uid=source_uid, enabled=body.enabled)
        if not changed:
            raise HTTPException(status_code=404, detail="calendar source not found or read-only")
        audit_action(
            request,
            action_type="reality_calendar_source_toggle",
            target_type="calendar_source",
            target_id=source_uid,
            details={"enabled": body.enabled},
            scope=scope_snapshot,
        )
        return ActionResponse(ok=True, message="日历订阅状态已更新。", item_id=source_uid)

    @app.post("/api/reality-context/manual-events", response_model=ActionResponse)
    async def add_reality_manual_event(request: Request, body: RealityManualEventRequest) -> ActionResponse:
        scope_snapshot, scope = current_conversation_scope()
        try:
            event = reality_service.add_manual_event(
                scope,
                title=body.title,
                start_at=body.start_at,
                end_at=body.end_at,
                location=body.location or "",
                is_all_day=body.is_all_day,
                note=body.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        audit_action(
            request,
            action_type="reality_manual_event_add",
            target_type="calendar_event",
            target_id=str(event.get("event_uid")),
            details={"title": event.get("title"), "start_at": event.get("start_at"), "source": "manual"},
            scope=scope_snapshot,
        )
        return ActionResponse(ok=True, message="手动日程已加入现实锚点。", item_id=str(event.get("event_uid")), payload={"event": event})

    @app.post("/api/proactive/{proactive_uid}/feedback", response_model=ActionResponse)
    async def proactive_feedback(request: Request, proactive_uid: str, body: ProactiveFeedbackRequest) -> ActionResponse:
        feedback = body.feedback.strip().lower()
        feedback = {"accepted": "good", "cold": "bad", "too_much": "too_frequent"}.get(feedback, feedback)
        if feedback not in {"good", "too_frequent", "bad"}:
            raise HTTPException(status_code=422, detail="feedback must be good, too_frequent, or bad")
        proactive_row = product_store.get_proactive_message(proactive_uid)
        if proactive_row is None:
            raise HTTPException(status_code=404, detail="proactive message not found")
        scope = ConversationScope(
            platform="discord",
            conversation_id=proactive_row.conversation_id,
            user_id=proactive_row.user_id,
            channel_id=proactive_row.channel_id,
            guild_id=None,
            session_id="dashboard-proactive-feedback",
        )
        feedback_event = {
            "feedback": feedback,
            "note": truncate_text(compact_text(body.note or ""), 160),
            "at": iso_utc_now(),
            "actor": session_username(request),
        }
        product_store.update_proactive_metadata(proactive_uid, {"dashboard_feedback": feedback_event})
        trigger_state = presence_service.record_proactive_feedback(
            scope,
            proactive_uid=proactive_uid,
            trigger_type=proactive_row.trigger_type,
            feedback=feedback,
            note=body.note,
        )
        if feedback == "too_frequent":
            until = datetime.now(timezone.utc) + timedelta(hours=6)
            product_store.set_app_setting(
                proactive_backoff_key(proactive_row.conversation_id),
                {
                    "until": until.isoformat(),
                    "error": "too_frequent feedback",
                    "updated_at": iso_utc_now(),
                    "source": "proactive_feedback",
                },
            )
            set_proactive_preferences(
                settings=settings,
                product_store=product_store,
                memory_store=memory_store,
                user_id=proactive_row.user_id,
                conversation_id=proactive_row.conversation_id,
                cadence="low",
                source="proactive_feedback",
            )
        audit_action(
            request,
            action_type="proactive_feedback",
            target_type="proactive_message",
            target_id=proactive_uid,
            details={"feedback": feedback, "note": body.note or ""},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(
            ok=True,
            message="主动消息反馈已记录。",
            item_id=proactive_uid,
            payload={"trigger_state": trigger_state, **proactive_preferences_payload(scope)},
        )

    @app.get("/api/facts", response_model=PanelEnvelope)
    async def facts(
        q: str = "",
        namespace: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=60),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size)
        normalized_q = _normalize_q(q)
        scope = current_scope_snapshot()
        clauses = ["status = 'active'"]
        params: list[Any] = []
        if scope:
            clauses.append("user_id = ?")
            params.append(scope["user_id"])
        if namespace:
            clauses.append("namespace = ?")
            params.append(namespace)
        search_clause, search_params = _build_text_search(normalized_q, ["namespace", "key", "value", "metadata_json"])
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM structured_facts WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="confidence DESC, updated_at DESC",
            page=page,
            page_size=page_size,
        )
        items = [_serialize_fact_row(row) for row in rows]
        return _build_panel_response(
            active_scope=scope,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            filters={"namespace": namespace or ""},
        )

    @app.get("/api/relationships", response_model=PanelEnvelope)
    async def relationships(
        q: str = "",
        dimension: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=60),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size)
        normalized_q = _normalize_q(q)
        scope = current_scope_snapshot()
        clauses = ["1 = 1"]
        params: list[Any] = []
        if scope:
            clauses.append("user_id = ?")
            params.append(scope["user_id"])
        if dimension:
            clauses.append("dimension = ?")
            params.append(dimension)
        search_clause, search_params = _build_text_search(normalized_q, ["dimension", "value", "note", "metadata_json"])
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM relationship_states WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="weight DESC, updated_at DESC",
            page=page,
            page_size=page_size,
        )
        items = [_serialize_relationship_row(row) for row in rows]
        return _build_panel_response(
            active_scope=scope,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
            filters={"dimension": dimension or ""},
        )

    @app.get("/api/summaries", response_model=PanelEnvelope)
    async def summaries(
        q: str = "",
        page: int = Query(1, ge=1),
        page_size: int = Query(12, ge=1, le=40),
    ) -> PanelEnvelope:
        page, page_size = _normalize_page(page, page_size, max_size=40)
        normalized_q = _normalize_q(q)
        scope = current_scope_snapshot()
        clauses = ["1 = 1"]
        params: list[Any] = []
        if scope:
            clauses.append("conversation_id = ?")
            params.append(scope["conversation_id"])
        search_clause, search_params = _build_text_search(normalized_q, ["content", "summary_kind", "metadata_json"])
        if search_clause:
            clauses.append(search_clause)
            params.extend(search_params)
        rows, total = _run_paged_select(
            db=product_store.db,
            columns="*",
            from_clause=f"FROM conversation_summaries WHERE {' AND '.join(clauses)}",
            params=params,
            order_by="message_end_id DESC, version DESC",
            page=page,
            page_size=page_size,
        )
        items = [_serialize_summary_row(row) for row in rows]
        return _build_panel_response(
            active_scope=scope,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            q=normalized_q,
        )

    @app.get("/api/modes", response_model=ModeStateResponse)
    async def modes() -> ModeStateResponse:
        resolved = resolve_primary_scope()
        if resolved is None:
            return ModeStateResponse()
        state = product_store.get_mode_state(resolved[0], resolved[1])
        return ModeStateResponse(**asdict(state))

    @app.post("/api/modes", response_model=ModeStateResponse)
    async def update_mode(request: Request, body: ModeUpdateRequest) -> ModeStateResponse:
        resolved = resolve_primary_scope()
        if resolved is None:
            raise HTTPException(status_code=409, detail="no active scope available for mode update")
        if body.user_id and body.user_id != resolved[0]:
            raise HTTPException(status_code=403, detail="mode updates are restricted to the active dashboard scope")
        if body.conversation_id and body.conversation_id != resolved[1]:
            raise HTTPException(status_code=403, detail="mode updates are restricted to the active dashboard scope")
        mode = _normalize_mode_value(body.mode)
        if mode not in ALLOWED_MODE_VALUES:
            raise HTTPException(status_code=422, detail=f"unsupported mode: {body.mode}")
        custom_model = (body.custom_model or "").strip() or None
        backup_model = (body.backup_model or "").strip() or None
        if mode == "custom" and not custom_model:
            raise HTTPException(status_code=422, detail="custom mode requires custom_model")
        state = product_store.upsert_mode_state(
            resolved[0],
            resolved[1],
            mode=mode,
            learning_mode=body.learning_mode,
            custom_model=custom_model,
            backup_model=backup_model,
            metadata={"source": "dashboard"},
        )
        audit_action(
            request,
            action_type="mode_update",
            target_type="mode_state",
            target_id=f"{resolved[0]}:{resolved[1]}",
            details={
                "mode": mode,
                "learning_mode": body.learning_mode,
                "custom_model": custom_model,
                "backup_model": backup_model,
            },
            scope=current_scope_snapshot(),
        )
        return ModeStateResponse(**asdict(state))

    @app.post("/api/audits/{audit_uid}/undo", response_model=ActionResponse)
    async def undo_audit_action(request: Request, audit_uid: str) -> ActionResponse:
        audit = product_store.get_dashboard_action_audit(audit_uid)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit entry not found")
        if not audit["undo_available"] or audit["status"] != "applied":
            raise HTTPException(status_code=409, detail="audit action is not undoable")
        action_type = audit["action_type"]
        target_id = audit["target_id"]
        if action_type == "memory_archive":
            if not product_store.restore_long_term_memory(target_id):
                raise HTTPException(status_code=409, detail="memory undo failed")
        elif action_type == "candidate_reject":
            if not product_store.reopen_candidate_memory(target_id):
                raise HTTPException(status_code=409, detail="candidate undo failed")
        else:
            raise HTTPException(status_code=409, detail="unsupported undo action")
        if not product_store.mark_dashboard_action_undone(audit_uid):
            raise HTTPException(status_code=409, detail="audit undo state update failed")
        audit_action(
            request,
            action_type="undo",
            target_type=audit["target_type"],
            target_id=target_id,
            details={"reverted_action": action_type},
            scope=current_scope_snapshot(),
        )
        return ActionResponse(ok=True, message="撤销已完成。", item_id=audit_uid)

    @app.get("/mobile/bootstrap", response_model=MobileBootstrapResponse)
    async def mobile_bootstrap() -> MobileBootstrapResponse:
        scope_snapshot, scope = resolve_mobile_scope()
        mode = product_store.get_mode_state(scope.user_id, scope.conversation_id)
        presence_payload = presence_service.build_dashboard_payload(scope)
        try:
            companion_payload = await day_engine.build_dashboard_payload(scope)
        except Exception:  # noqa: BLE001
            companion_payload = {}
        reality_payload = reality_service.build_dashboard_payload(scope)
        proactive_items = [
            asdict(item)
            for item in product_store.list_proactive_messages(limit=20)
            if item.user_id == scope.user_id and item.conversation_id == scope.conversation_id
        ]
        proactive_settings = proactive_preferences_payload(scope)
        scene_state = mobile_scene_state(
            presence_payload=presence_payload,
            companion_payload=companion_payload,
            reality_payload=reality_payload,
        )
        latest_records = memory_store.list_recent_messages(scope.conversation_id, limit=1)
        latest_cursor = f"message:{latest_records[-1].id}" if latest_records else None
        return MobileBootstrapResponse(
            active_scope=None if scope_snapshot is None else ScopeSnapshotModel.model_validate(scope_snapshot),
            mode=ModeStateResponse(**asdict(mode)),
            profile=MobileCompanionProfile(),
            scene_state=scene_state,
            timeline_cursor=latest_cursor,
            dashboard_groups=mobile_dashboard_groups(),
            presence=presence_payload,
            companion_day=companion_payload,
            proactive={
                "items": proactive_items,
                "cursor": proactive_items[0]["proactive_uid"] if proactive_items else None,
                **proactive_settings,
            },
            reality_context=reality_payload,
            feature_flags=MobileFeatureFlags(
                authentication_required=bool(settings.mobile_api_token),
                https_required=not _is_local_dev_host(settings.dashboard_host),
            ),
            refreshed_at=iso_utc_now(),
        )

    @app.get("/mobile/messages", response_model=MobileMessagesResponse)
    async def mobile_messages(
        before_id: Optional[int] = None,
        limit: int = Query(40, ge=1, le=120),
    ) -> MobileMessagesResponse:
        scope_snapshot, scope = resolve_mobile_scope()
        fetch_limit = min(limit + 1, 121)
        records = memory_store.list_recent_messages(
            scope.conversation_id,
            limit=fetch_limit,
            before_message_id=before_id,
        )
        has_more = len(records) > limit
        visible = records[-limit:] if has_more else records
        return MobileMessagesResponse(
            active_scope=None if scope_snapshot is None else ScopeSnapshotModel.model_validate(scope_snapshot),
            items=[message_model(record) for record in visible],
            has_more=has_more,
            next_before_id=visible[0].id if has_more and visible else None,
            refreshed_at=iso_utc_now(),
        )

    @app.get("/mobile/timeline", response_model=MobileTimelineResponse)
    async def mobile_timeline(
        before: Optional[str] = None,
        limit: int = Query(60, ge=1, le=160),
    ) -> MobileTimelineResponse:
        scope_snapshot, scope = resolve_mobile_scope()
        messages = memory_store.list_recent_messages(scope.conversation_id, limit=min(limit * 3, 360))
        proactive_items = [
            item
            for item in product_store.list_proactive_messages(limit=min(limit * 3, 360))
            if item.user_id == scope.user_id and item.conversation_id == scope.conversation_id
        ]
        timeline_items: list[MobileTimelineItem] = [
            mobile_message_timeline_item(record) for record in messages
        ] + [
            mobile_proactive_timeline_item(item) for item in proactive_items
        ]
        timeline_items.sort(key=timeline_sort_key)

        if before:
            cursor_item = next((item for item in timeline_items if item.id == before), None)
            if cursor_item is not None:
                cursor_key = timeline_sort_key(cursor_item)
                timeline_items = [item for item in timeline_items if timeline_sort_key(item) < cursor_key]

        has_more = len(timeline_items) > limit
        visible = timeline_items[-limit:] if has_more else timeline_items
        return MobileTimelineResponse(
            active_scope=None if scope_snapshot is None else ScopeSnapshotModel.model_validate(scope_snapshot),
            items=visible,
            has_more=has_more,
            next_cursor=visible[0].id if has_more and visible else None,
            refreshed_at=iso_utc_now(),
        )

    @app.post("/mobile/chat/stream")
    async def mobile_chat_stream(body: MobileChatRequest) -> StreamingResponse:
        scope_snapshot, scope = resolve_mobile_scope()
        if scope_snapshot is not None:
            product_store.set_dashboard_active_scope(
                user_id=scope_snapshot["user_id"],
                conversation_id=scope_snapshot["conversation_id"],
                channel_id=scope_snapshot["channel_id"],
                guild_id=scope_snapshot["guild_id"],
            )
        attachment_insights = load_mobile_attachment_insights(body.attachment_uids)

        async def event_source():
            if companion_service is None:
                async for event in fallback_mobile_stream(scope, body):
                    yield mobile_sse(event)
                return
            async for event in companion_service.stream_mobile_reply(
                scope=scope,
                user_content=body.content,
                platform_message_id=body.client_message_id,
                author_id="mobile-user",
                display_name=body.display_name,
                attachment_insights=attachment_insights,
                tool_overrides=body.tool_overrides.model_dump(),
                metadata={
                    "mobile": body.metadata,
                    "attachment_uids": body.attachment_uids,
                    "client_scene": body.client_scene,
                    "client_timezone": body.client_timezone,
                    "tool_overrides": body.tool_overrides.model_dump(),
                },
            ):
                yield mobile_sse(event)

        return StreamingResponse(event_source(), media_type="text/event-stream")

    @app.post("/mobile/attachments", response_model=MobileAttachmentUploadResponse)
    async def mobile_attachments(files: List[UploadFile] = File(default=[])) -> MobileAttachmentUploadResponse:
        if attachment_service is None:
            raise HTTPException(status_code=503, detail="attachment service is not available")
        if not files:
            raise HTTPException(status_code=422, detail="at least one file is required")
        scope_snapshot, scope = resolve_mobile_scope()
        upload_uid = f"upl_{secrets.token_urlsafe(18)}"
        payloads: list[dict[str, Any]] = []
        for upload in files:
            data = await upload.read()
            payloads.append(
                {
                    "filename": upload.filename or "attachment",
                    "content_type": upload.content_type,
                    "size": len(data),
                    "data": data,
                }
            )
        insights = await attachment_service.analyze_file_payloads(
            files=payloads,
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            platform_message_id=upload_uid,
        )
        items = [attachment_item_from_insight(insight).model_dump() for insight in insights]
        created_at = iso_utc_now()
        product_store.set_app_setting(
            mobile_upload_key(upload_uid),
            {
                "upload_uid": upload_uid,
                "user_id": scope.user_id,
                "conversation_id": scope.conversation_id,
                "active_scope": scope_snapshot,
                "items": items,
                "created_at": created_at,
            },
        )
        return MobileAttachmentUploadResponse(
            upload_uid=upload_uid,
            items=[MobileAttachmentItem.model_validate(item) for item in items],
            created_at=created_at,
        )

    @app.get("/mobile/generated-images/{filename}")
    async def mobile_generated_image(filename: str) -> FileResponse:
        safe_name = Path(filename).name
        image_path = Path("data/generated_images") / safe_name
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="generated image not found")
        return FileResponse(image_path)

    @app.get("/mobile/mode", response_model=ModeStateResponse)
    async def mobile_mode() -> ModeStateResponse:
        return await modes()

    @app.post("/mobile/mode", response_model=ModeStateResponse)
    async def update_mobile_mode(request: Request, body: ModeUpdateRequest) -> ModeStateResponse:
        return await update_mode(request, body)

    @app.get("/mobile/status", response_model=MobileStatusResponse)
    async def mobile_status() -> MobileStatusResponse:
        scope_snapshot, scope = resolve_mobile_scope()
        mode_state = product_store.get_mode_state(scope.user_id, scope.conversation_id)
        recent_turns = product_store.list_recent_turns(conversation_id=scope.conversation_id, limit=50)
        now = math.floor(datetime.now(timezone.utc).timestamp())
        requests_last_hour = 0
        for turn in recent_turns:
            created_at = parse_iso8601(turn.created_at)
            if created_at is None:
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if now - math.floor(created_at.timestamp()) <= 3600:
                requests_last_hour += 1
        if companion_service is not None:
            text = companion_service._render_status(scope, mode_state)  # noqa: SLF001
        else:
            text = (
                f"当前模式：{mode_state.mode}\n"
                f"学习模式：{'开启' if mode_state.learning_mode else '关闭'}\n"
                f"近 1 小时请求数：{requests_last_hour}"
            )
        return MobileStatusResponse(
            active_scope=None if scope_snapshot is None else ScopeSnapshotModel.model_validate(scope_snapshot),
            text=text,
            mode=ModeStateResponse(**asdict(mode_state)),
            requests_last_hour=requests_last_hour,
            refreshed_at=iso_utc_now(),
        )

    @app.get("/mobile/proactive", response_model=MobileProactiveResponse)
    async def mobile_proactive(
        after: Optional[str] = None,
        limit: int = Query(50, ge=1, le=100),
    ) -> MobileProactiveResponse:
        scope_snapshot, scope = resolve_mobile_scope()
        items = [
            asdict(item)
            for item in product_store.list_proactive_messages(limit=limit)
            if item.user_id == scope.user_id and item.conversation_id == scope.conversation_id
        ]
        if after:
            filtered: list[dict[str, Any]] = []
            seen_cursor = False
            for item in reversed(items):
                if item["proactive_uid"] == after:
                    seen_cursor = True
                    continue
                if seen_cursor:
                    filtered.append(item)
            items = list(reversed(filtered))
        return MobileProactiveResponse(
            active_scope=None if scope_snapshot is None else ScopeSnapshotModel.model_validate(scope_snapshot),
            items=items,
            cursor=items[0]["proactive_uid"] if items else after,
            refreshed_at=iso_utc_now(),
        )

    @app.get("/mobile/proactive/preferences", response_model=MobileProactivePreferencesResponse)
    async def mobile_proactive_preferences() -> MobileProactivePreferencesResponse:
        scope_snapshot, scope = resolve_mobile_scope()
        payload = proactive_preferences_payload(scope)
        return MobileProactivePreferencesResponse(
            active_scope=None if scope_snapshot is None else ScopeSnapshotModel.model_validate(scope_snapshot),
            preferences=payload["preferences"],
            gate=payload["gate"],
            refreshed_at=iso_utc_now(),
        )

    @app.patch("/mobile/proactive/preferences", response_model=MobileProactivePreferencesResponse)
    async def update_mobile_proactive_preferences(body: ProactivePreferencesRequest) -> MobileProactivePreferencesResponse:
        scope_snapshot, scope = resolve_mobile_scope()
        try:
            set_proactive_preferences(
                settings=settings,
                product_store=product_store,
                memory_store=memory_store,
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                enabled=body.enabled,
                cadence=body.cadence,
                source="ios",
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload = proactive_preferences_payload(scope)
        return MobileProactivePreferencesResponse(
            active_scope=None if scope_snapshot is None else ScopeSnapshotModel.model_validate(scope_snapshot),
            preferences=payload["preferences"],
            gate=payload["gate"],
            refreshed_at=iso_utc_now(),
        )

    @app.post("/mobile/proactive/{proactive_uid}/feedback", response_model=ActionResponse)
    async def mobile_proactive_feedback(request: Request, proactive_uid: str, body: ProactiveFeedbackRequest) -> ActionResponse:
        return await proactive_feedback(request, proactive_uid, body)

    @app.post("/mobile/device-context", response_model=MobileDeviceContextResponse)
    async def mobile_device_context(body: MobileDeviceContextRequest) -> MobileDeviceContextResponse:
        scope_snapshot, scope = resolve_mobile_scope()
        location_payload = None
        if body.location is not None:
            location_payload = reality_service.update_location(
                scope,
                label=body.location.label,
                latitude=body.location.latitude,
                longitude=body.location.longitude,
                note=body.location.note or "mobile device context",
            )
        event_count = 0
        for event in body.calendar_events[:80]:
            try:
                reality_service.add_manual_event(
                    scope,
                    title=event.title,
                    start_at=event.start_at,
                    end_at=event.end_at,
                    location=event.location or "",
                    is_all_day=event.is_all_day,
                    note=event.note or f"mobile_device_calendar:{body.source}",
                )
                event_count += 1
            except ValueError:
                continue
        payload = reality_service.build_dashboard_payload(scope)
        return MobileDeviceContextResponse(
            ok=True,
            active_scope=None if scope_snapshot is None else ScopeSnapshotModel.model_validate(scope_snapshot),
            location=location_payload,
            calendar_event_count=event_count,
            payload=payload,
            refreshed_at=iso_utc_now(),
        )

    @app.get("/mobile/dashboard/{panel_key}")
    async def mobile_dashboard_panel(
        panel_key: str,
        q: str = "",
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=400),
        sort: str = "",
        status: Optional[str] = None,
        scope_mode: str = "active",
        task_type: Optional[str] = None,
        memory_type: Optional[str] = None,
        category: Optional[str] = None,
        component: Optional[str] = None,
        request_type: Optional[str] = None,
        scene: Optional[str] = None,
        artifact_type: Optional[str] = None,
        namespace: Optional[str] = None,
        dimension: Optional[str] = None,
        entry_type: Optional[str] = None,
        role_scope: Optional[str] = None,
    ):
        key = panel_key.strip().lower().replace("_", "-")
        if key == "overview":
            return await overview()
        if key == "scopes":
            return await scopes()
        if key == "security":
            return await security()
        if key == "audits":
            return await audits(q=q, page=page, page_size=page_size)
        if key == "logs":
            return await logs(q=q, page=page, page_size=page_size)
        if key == "search":
            return await search_everything(q=q)
        if key == "performance":
            return await performance(scope_mode=scope_mode)
        if key == "tasks":
            return await tasks(q=q, status=status, task_type=task_type, scope_mode=scope_mode, page=page, page_size=page_size)
        if key == "memories":
            return await memories(q=q, sort=sort or "importance", page=page, page_size=page_size)
        if key == "candidates":
            return await candidates(q=q, status=status or "pending", memory_type=memory_type, category=category, page=page, page_size=page_size)
        if key == "snapshots":
            return await snapshots(q=q, page=page, page_size=page_size)
        if key == "errors":
            return await errors(q=q, status=status, component=component, page=page, page_size=page_size)
        if key == "health":
            return await health()
        if key == "turns":
            return await turns(q=q, request_type=request_type, scene=scene, page=page, page_size=page_size)
        if key == "attachments":
            return await attachments(q=q, artifact_type=artifact_type, page=page, page_size=page_size)
        if key == "proactive":
            return await proactive(q=q, status=status, page=page, page_size=page_size)
        if key == "presence":
            return await presence()
        if key == "companion-day":
            return await companion_day()
        if key == "shared-diary":
            return await shared_diary(
                q=q,
                entry_type=entry_type,
                role_scope=role_scope,
                page=page,
                page_size=page_size,
            )
        if key == "reality-context":
            return await reality_context()
        if key == "facts":
            return await facts(q=q, namespace=namespace, page=page, page_size=page_size)
        if key == "relationships":
            return await relationships(q=q, dimension=dimension, page=page, page_size=page_size)
        if key == "summaries":
            return await summaries(q=q, page=page, page_size=page_size)
        if key == "modes":
            return await modes()
        raise HTTPException(status_code=404, detail=f"unknown dashboard panel: {panel_key}")

    @app.post("/mobile/dashboard/scopes/active", response_model=ActionResponse)
    async def mobile_update_active_scope(request: Request, body: ScopeUpdateRequest) -> ActionResponse:
        return await update_active_scope(request, body)

    @app.post("/mobile/dashboard/memories/{memory_uid}/archive", response_model=ActionResponse)
    async def mobile_archive_memory(request: Request, memory_uid: str) -> ActionResponse:
        return await archive_memory(request, memory_uid)

    @app.post("/mobile/dashboard/memories/{memory_uid}/restore", response_model=ActionResponse)
    async def mobile_restore_memory(request: Request, memory_uid: str) -> ActionResponse:
        return await restore_memory(request, memory_uid)

    @app.post("/mobile/dashboard/candidates/batch-review", response_model=ActionResponse)
    async def mobile_batch_review_candidates(request: Request, body: BatchCandidateReviewRequest) -> ActionResponse:
        return await batch_review_candidates(request, body)

    @app.post("/mobile/dashboard/candidates/{candidate_uid}/approve", response_model=ActionResponse)
    async def mobile_approve_candidate(request: Request, candidate_uid: str, body: CandidateReviewRequest) -> ActionResponse:
        return await approve_candidate_api(request, candidate_uid, body)

    @app.post("/mobile/dashboard/candidates/{candidate_uid}/reject", response_model=ActionResponse)
    async def mobile_reject_candidate(request: Request, candidate_uid: str, body: CandidateReviewRequest) -> ActionResponse:
        return await reject_candidate_api(request, candidate_uid, body)

    @app.post("/mobile/dashboard/candidates/{candidate_uid}/reopen", response_model=ActionResponse)
    async def mobile_reopen_candidate(request: Request, candidate_uid: str) -> ActionResponse:
        return await reopen_candidate(request, candidate_uid)

    @app.post("/mobile/dashboard/errors/{error_uid}/status", response_model=ActionResponse)
    async def mobile_update_error_status(request: Request, error_uid: str, body: ErrorStatusRequest) -> ActionResponse:
        return await update_error_status_api(request, error_uid, body)

    @app.post("/mobile/dashboard/tasks/{task_uid}/retry", response_model=ActionResponse)
    async def mobile_retry_task(request: Request, task_uid: str) -> ActionResponse:
        return await retry_task(request, task_uid)

    @app.post("/mobile/dashboard/tasks/{task_uid}/cancel", response_model=ActionResponse)
    async def mobile_cancel_task(request: Request, task_uid: str) -> ActionResponse:
        return await cancel_task(request, task_uid)

    @app.post("/mobile/dashboard/tasks/{task_uid}/boost", response_model=ActionResponse)
    async def mobile_boost_task(request: Request, task_uid: str, body: TaskPriorityRequest) -> ActionResponse:
        return await boost_task(request, task_uid, body)

    @app.post("/mobile/dashboard/presence", response_model=ActionResponse)
    async def mobile_update_presence(request: Request, body: PresenceUpdateRequest) -> ActionResponse:
        return await update_presence(request, body)

    @app.patch("/mobile/dashboard/companion-day", response_model=ActionResponse)
    async def mobile_update_companion_day(request: Request, body: CompanionDayUpdateRequest) -> ActionResponse:
        return await update_companion_day(request, body)

    @app.post("/mobile/dashboard/companion-day/regenerate", response_model=ActionResponse)
    async def mobile_regenerate_companion_day(request: Request) -> ActionResponse:
        return await regenerate_companion_day(request)

    @app.post("/mobile/dashboard/companion-day/events/{event_uid}/feedback", response_model=ActionResponse)
    async def mobile_companion_day_event_feedback(request: Request, event_uid: str, body: CompanionDayFeedbackRequest) -> ActionResponse:
        return await companion_day_event_feedback(request, event_uid, body)

    @app.post("/mobile/dashboard/reality-context/refresh", response_model=ActionResponse)
    async def mobile_refresh_reality_context(request: Request) -> ActionResponse:
        return await refresh_reality_context(request)

    @app.patch("/mobile/dashboard/reality-context/location", response_model=ActionResponse)
    async def mobile_update_reality_location(request: Request, body: RealityLocationRequest) -> ActionResponse:
        return await update_reality_location(request, body)

    @app.post("/mobile/dashboard/reality-context/calendar-sources", response_model=ActionResponse)
    async def mobile_add_reality_calendar_source(request: Request, body: RealityCalendarSourceRequest) -> ActionResponse:
        return await add_reality_calendar_source(request, body)

    @app.patch("/mobile/dashboard/reality-context/calendar-sources/{source_uid}", response_model=ActionResponse)
    async def mobile_toggle_reality_calendar_source(
        request: Request,
        source_uid: str,
        body: RealityCalendarSourceToggleRequest,
    ) -> ActionResponse:
        return await toggle_reality_calendar_source(request, source_uid, body)

    @app.post("/mobile/dashboard/reality-context/manual-events", response_model=ActionResponse)
    async def mobile_add_reality_manual_event(request: Request, body: RealityManualEventRequest) -> ActionResponse:
        return await add_reality_manual_event(request, body)

    @app.post("/mobile/dashboard/proactive/{proactive_uid}/feedback", response_model=ActionResponse)
    async def mobile_dashboard_proactive_feedback(request: Request, proactive_uid: str, body: ProactiveFeedbackRequest) -> ActionResponse:
        return await proactive_feedback(request, proactive_uid, body)

    @app.post("/mobile/dashboard/audits/{audit_uid}/undo", response_model=ActionResponse)
    async def mobile_undo_audit_action(request: Request, audit_uid: str) -> ActionResponse:
        return await undo_audit_action(request, audit_uid)

    return app
