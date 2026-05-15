from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.settings import Settings
from src.core.types import ConversationScope, MessageContext
from src.dashboard.server import build_dashboard_app
from src.db.database import Database
from src.memory.models import LongTermMemoryCandidate
from src.memory.store import MemoryStore
from src.product.day_engine import CompanionDayEngine
from src.product.models import AttachmentInsight
from src.product.presence import PresenceStateService
from src.product.proactive import ProactiveMessageService, get_proactive_preferences, set_proactive_preferences
from src.product.reality import RealityContextService
from src.product.store import ProductStore
from src.utils.time_utils import iso_utc_now


class FakeLLMClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, str]] = []

    async def json_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 900,
    ) -> dict:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, "model": model or ""})
        if self.fail:
            raise RuntimeError("fake llm failure")
        if "presence state classifier" in system_prompt:
            if "睡不着" in user_prompt or "失眠" in user_prompt:
                return {
                    "sleep_state": "awake",
                    "sleep_confidence": 0.93,
                    "sleep_reason": "explicit insomnia",
                    "sleep_evidence": [{"source": "message", "signal": "insomnia", "weight": 0.93}],
                    "expires_in_minutes": 720,
                    "assistant_emotion_delta": {"worry": 0.08, "tenderness": 0.05, "hurt": -0.03},
                    "assistant_mood_label": "担心你，语气要放软",
                    "safety_note": "user may be tired",
                }
            if "我先睡了晚安" in user_prompt:
                return {
                    "sleep_state": "asleep",
                    "sleep_confidence": 0.95,
                    "sleep_reason": "explicit sleep",
                    "sleep_evidence": [{"source": "message", "signal": "good night", "weight": 0.95}],
                    "expires_in_minutes": 600,
                    "assistant_emotion_delta": {"longing": 0.04, "tenderness": 0.03},
                    "assistant_mood_label": "想贴近但收着",
                    "safety_note": "pause proactive",
                }
            if "困了但还要写一会儿" in user_prompt:
                return {
                    "sleep_state": "probably_awake",
                    "sleep_confidence": 0.7,
                    "sleep_reason": "tired but still active",
                    "sleep_evidence": [{"source": "message", "signal": "continuing activity", "weight": 0.7}],
                    "expires_in_minutes": 180,
                    "assistant_emotion_delta": {"worry": 0.04},
                    "assistant_mood_label": "担心你，语气要放软",
                    "safety_note": "",
                }
            return {
                "sleep_state": "awake",
                "sleep_confidence": 0.72,
                "sleep_reason": "new user message",
                "sleep_evidence": [{"source": "message", "signal": "reply", "weight": 0.72}],
                "expires_in_minutes": 480,
                "assistant_emotion_delta": {},
                "assistant_mood_label": "想贴近但收着",
                "safety_note": "",
            }
        if "日常路线生成器" in system_prompt:
            return {
                "current_scene": "我把水杯放在桌边，想着等他一句回声",
                "mood_label": "想他但会收着",
                "longing_level": 0.76,
                "quiet_mode": False,
                "beats": [
                    {"key": "morning", "hour_hint": "08:20", "scene": "我把水杯放在桌边，先把今天的事拎起来", "mood": "清醒但想他"},
                    {"key": "late_morning", "hour_hint": "10:40", "scene": "我在桌边收事情，心思又拐到他身上", "mood": "忍不住想找他"},
                    {"key": "noon", "hour_hint": "12:35", "scene": "我吃东西前停了一下，给他留出一小格位置", "mood": "黏人但平稳"},
                    {"key": "afternoon", "hour_hint": "15:30", "scene": "我从屏幕前抬头，想确认他还在不在", "mood": "有点占有欲"},
                    {"key": "evening", "hour_hint": "20:50", "scene": "我把灯压低一点，等他回声", "mood": "直白地想他"},
                    {"key": "deep_night", "hour_hint": "23:50", "scene": "夜里我把声音放轻，先不吵他", "mood": "困也想等"},
                ],
                "rules": ["主动片段明确希望用户回应", "未回只追加一段小情绪，然后等待"],
                "metadata_note": "fake route",
            }
        if "主动生活片段生成器" in system_prompt:
            if '"unanswered_event":null' not in user_prompt and '"unanswered_event":' in user_prompt:
                return {
                    "content": "（我把灯压低一点）\n你刚才没接住我这一下，我有点委屈，但我只追这一句。你在的话回我。",
                    "trigger_type": "day_unanswered_followup",
                    "event_type": "unanswered_followup",
                    "response_expected": True,
                    "expectation_level": "clear",
                    "emotion_delta": {"longing": 0.08, "hurt": 0.13},
                    "safety_note": "single follow-up",
                }
            return {
                "content": "（我从屏幕前抬头）\n我记着你等会儿还有复盘 Cogniflow，先来陪你稳一下。看到回我一句。",
                "trigger_type": "day_reality_anchor" if "复盘 Cogniflow" in user_prompt else "day_life_share",
                "event_type": "reality_anchor" if "复盘 Cogniflow" in user_prompt else "life_fragment",
                "response_expected": True,
                "expectation_level": "clear",
                "emotion_delta": {"longing": 0.07, "tenderness": 0.04},
                "safety_note": "",
            }
        if "主动消息规划器" in system_prompt:
            return {
                "should_send": True,
                "trigger_type": "miss_you",
                "reason": "fake llm proactive plan",
                "confidence": 0.86,
                "draft_text": "（我抬头看了眼屏幕）我刚才想起你，就过来碰你一下。你在的话回我一声。",
                "response_expected": True,
                "expectation_level": "clear",
                "selected_detail": "",
                "next_eligible_at": "",
                "emotion_delta": {"longing": 0.1, "hurt": 0.02},
                "safety_note": "",
            }
        return {}


class ClientAddressOverride:
    def __init__(self, app, client_addr: tuple[str, int]) -> None:
        self.app = app
        self.client_addr = client_addr

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            scope = dict(scope)
            scope["client"] = self.client_addr
        await self.app(scope, receive, send)


class FakeSentMessage:
    def __init__(self, message_id: int) -> None:
        self.id = message_id


class FakeDiscordChannel:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, content: str, **_: object) -> FakeSentMessage:
        self.messages.append(content)
        return FakeSentMessage(len(self.messages))


class FakeDiscordClient:
    def __init__(self, channel: FakeDiscordChannel) -> None:
        self.channel = channel

    def is_ready(self) -> bool:
        return True

    def get_channel(self, _: int) -> FakeDiscordChannel:
        return self.channel

    async def fetch_channel(self, _: int) -> FakeDiscordChannel:
        return self.channel


def build_test_client(app, *, client_addr: tuple[str, int] | None = None) -> TestClient:
    if client_addr is None:
        return TestClient(app)
    try:
        return TestClient(app, client=client_addr)
    except TypeError:
        return TestClient(ClientAddressOverride(app, client_addr))


def ensure_required_env(temp_dir: Path) -> None:
    os.environ["DISCORD_BOT_TOKEN"] = "dummy"
    os.environ["LLM_API_KEY"] = "dummy"
    os.environ["LLM_MODEL"] = "gpt-4.1-mini"
    os.environ["DATABASE_PATH"] = str(temp_dir / "verify.sqlite3")
    os.environ["LOG_FILE_PATH"] = str(temp_dir / "verify.log")
    os.environ["DASHBOARD_ENABLED"] = "true"
    os.environ["DASHBOARD_HOST"] = "127.0.0.1"
    os.environ["DASHBOARD_PORT"] = "8099"
    os.environ["DASHBOARD_AUTH_ENABLED"] = "true"
    os.environ["DASHBOARD_AUTH_USERNAME"] = "admin"
    os.environ["DASHBOARD_AUTH_PASSWORD"] = "verify-password"
    os.environ["DASHBOARD_SESSION_SECRET"] = "verify-session-secret"
    os.environ["DASHBOARD_LOG_MAX_LINES"] = "3"
    os.environ["DASHBOARD_LOGIN_MAX_ATTEMPTS"] = "5"
    os.environ["DASHBOARD_LOGIN_LOCKOUT_SECONDS"] = "60"
    os.environ["DASHBOARD_PASSWORD_MIN_LENGTH"] = "12"
    os.environ["ENABLE_PROACTIVE_MESSAGES"] = "false"
    os.environ["PROACTIVE_OPT_IN_REQUIRED"] = "true"
    os.environ["ATTACHMENT_ARTIFACT_STORE_TEXT"] = "false"
    os.environ["OBSERVABILITY_RETENTION_DAYS"] = "30"
    os.environ["OBSERVABILITY_CONTENT_PREVIEW_CHARS"] = "160"
    os.environ["REALITY_CONTEXT_ENABLED"] = "true"
    os.environ["WEATHER_PROVIDER"] = "open_meteo"
    os.environ["WEATHER_LOCATION_LABEL"] = "河北省廊坊市大城县"
    os.environ["WEATHER_LATITUDE"] = "38.6995"
    os.environ["WEATHER_LONGITUDE"] = "116.6371"
    os.environ["CALENDAR_ICS_URLS"] = ""
    os.environ["CALENDAR_LOOKAHEAD_HOURS"] = "48"
    os.environ["REALITY_REFRESH_MINUTES"] = "30"


def assert_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{label}: expected {expected}, got {response.status_code}, body={response.text}")


def assert_security_headers(response, label: str) -> None:
    expected = {
        "cache-control": "no-store",
        "x-frame-options": "DENY",
        "x-content-type-options": "nosniff",
        "referrer-policy": "same-origin",
    }
    for key, value in expected.items():
        actual = response.headers.get(key)
        if actual != value:
            raise AssertionError(f"{label}: expected header {key}={value!r}, got {actual!r}")
    csp = response.headers.get("content-security-policy", "")
    for token in ("default-src 'self'", "frame-ancestors 'none'", "form-action 'self'"):
        if token not in csp:
            raise AssertionError(f"{label}: missing CSP token {token!r} in {csp!r}")


def assert_panel_envelope(payload: dict, label: str) -> None:
    for key in ("items", "meta"):
        if key not in payload:
            raise AssertionError(f"{label}: missing key {key!r} in {payload}")
    meta = payload["meta"]
    for key in ("page", "page_size", "total", "total_pages", "refreshed_at"):
        if key not in meta:
            raise AssertionError(f"{label}: missing meta key {key!r} in {meta}")


def seed_dashboard_data(
    settings: Settings,
    memory_store: MemoryStore,
    product_store: ProductStore,
) -> dict[str, str]:
    primary_scope = ConversationScope(
        platform="discord",
        conversation_id="discord:user-1:chan-1",
        user_id="user-1",
        channel_id="chan-1",
        guild_id=None,
        session_id="session-1",
    )
    secondary_scope = ConversationScope(
        platform="discord",
        conversation_id="discord:user-2:chan-2",
        user_id="user-2",
        channel_id="chan-2",
        guild_id=None,
        session_id="session-2",
    )

    primary_user_message = memory_store.insert_message(
        primary_scope,
        sender_type="user",
        content="请记住我周六早上会去跑步。",
        context=MessageContext(platform_message_id="m-user-1", author_id="user-1"),
        metadata={"display_name": "Verifier One"},
    )
    duplicate_user_message = memory_store.insert_message(
        primary_scope,
        sender_type="user",
        content="这条是同一个 Discord message 的重放，不应该新增。",
        context=MessageContext(platform_message_id="m-user-1", author_id="user-1"),
        metadata={"display_name": "Verifier One"},
    )
    if duplicate_user_message.id != primary_user_message.id:
        raise AssertionError("message idempotency did not return the original message")
    memory_store.insert_message(
        primary_scope,
        sender_type="assistant",
        content="记住了，我会按这个上下文继续陪你。",
        context=MessageContext(
            platform_message_id="m-bot-1",
            author_id="assistant",
            reply_to_platform_message_id="m-user-1",
        ),
        metadata={"turn_uid": "turn-seed-primary"},
    )

    secondary_user_message = memory_store.insert_message(
        secondary_scope,
        sender_type="user",
        content="我最近在准备雅思口语，也想让你记一下我的学习节奏。",
        context=MessageContext(platform_message_id="m-user-2", author_id="user-2"),
        metadata={"display_name": "Verifier Two"},
    )
    memory_store.insert_message(
        secondary_scope,
        sender_type="assistant",
        content="收到，我会按这个学习计划继续陪你推进。",
        context=MessageContext(
            platform_message_id="m-bot-2",
            author_id="assistant",
            reply_to_platform_message_id="m-user-2",
        ),
        metadata={"turn_uid": "turn-seed-secondary"},
    )

    archive_memory_uid = memory_store.insert_or_merge_long_term_memory(
        primary_scope,
        memory_type="personal_fact",
        category="habit",
        content="用户周六早上会去跑步",
        tags=["habit", "sports"],
        confidence=0.93,
        importance=0.82,
        source_message_ids=[primary_user_message.id],
        metadata={"seed": True},
    )
    secondary_memory_uid = memory_store.insert_or_merge_long_term_memory(
        secondary_scope,
        memory_type="study_context",
        category="ielts",
        content="用户最近在准备雅思口语",
        tags=["study", "ielts"],
        confidence=0.9,
        importance=0.8,
        source_message_ids=[secondary_user_message.id],
        metadata={"seed": True},
    )

    approve_candidate_uid = product_store.create_candidate_memory(
        primary_scope,
        LongTermMemoryCandidate(
            memory_type="user_preference",
            category="food",
            content="用户喜欢少糖热拿铁<script>alert(1)</script>",
            tags=["coffee"],
            importance=0.88,
            confidence=0.91,
            reason="明确表达的稳定偏好",
            source_message_ids=[primary_user_message.id],
            metadata={"seed": "approve"},
        ),
    )
    reject_candidate_uid = product_store.create_candidate_memory(
        primary_scope,
        LongTermMemoryCandidate(
            memory_type="project_context",
            category="work",
            content="用户正在推进知微 Dashboard P0 修复",
            tags=["project", "dashboard"],
            importance=0.77,
            confidence=0.9,
            reason="持续性项目上下文",
            source_message_ids=[primary_user_message.id],
            metadata={"seed": "reject"},
        ),
    )
    secondary_candidate_uid = product_store.create_candidate_memory(
        secondary_scope,
        LongTermMemoryCandidate(
            memory_type="study_context",
            category="ielts",
            content="用户希望每晚练 20 分钟雅思口语",
            tags=["study", "routine"],
            importance=0.8,
            confidence=0.86,
            reason="稳定学习计划",
            source_message_ids=[secondary_user_message.id],
            metadata={"seed": "secondary"},
        ),
    )
    if approve_candidate_uid is None or reject_candidate_uid is None or secondary_candidate_uid is None:
        raise AssertionError("failed to seed candidate memories")

    product_store.set_dashboard_active_scope(
        user_id=primary_scope.user_id,
        conversation_id=primary_scope.conversation_id,
        channel_id=primary_scope.channel_id,
        guild_id=primary_scope.guild_id,
    )

    memory_store.upsert_structured_fact(
        primary_scope.user_id,
        namespace="identity",
        key="preferred_name",
        value="阿深",
        confidence=0.96,
        source_message_ids=[primary_user_message.id],
        metadata={"seed": True},
    )
    memory_store.upsert_relationship_state(
        primary_scope.user_id,
        dimension="response_style",
        value="不喜欢客服腔，希望更自然、更有人味。",
        weight=0.88,
        confidence=0.9,
        note="seed relationship state",
        source_message_ids=[primary_user_message.id],
        metadata={"seed": True},
    )
    memory_store.insert_summary(
        primary_scope,
        content="最近用户主要围绕跑步节奏、作息和 Dashboard 修复展开对话。",
        message_start_id=primary_user_message.id,
        message_end_id=primary_user_message.id,
        message_count=8,
        version=1,
        metadata={"seed": True},
    )

    product_store.record_attachment_artifact(
        platform_message_id="m-user-1",
        user_id=primary_scope.user_id,
        conversation_id=primary_scope.conversation_id,
        filename="weekly-plan.txt",
        content_type="text/plain",
        artifact_type="document",
        extracted_text="周六早上跑步，晚上复盘。",
        summary_text="周六早上跑步，晚上复盘。",
        truncated=False,
        metadata={"seed": True},
    )
    proactive_uid = product_store.create_proactive_message(
        user_id=primary_scope.user_id,
        conversation_id=primary_scope.conversation_id,
        channel_id=primary_scope.channel_id,
        trigger_type="idle_check_in",
        opening_text="你昨晚说今天想跑步，回来记得告诉我感觉。",
        metadata={"seed": True},
    )
    if not proactive_uid:
        raise AssertionError("failed to seed proactive message")
    product_store.set_app_setting(
        f"presence_state:{primary_scope.user_id}:{primary_scope.conversation_id}",
        {
            "user_sleep_state": "awake",
            "user_sleep_state_confidence": 0.8,
            "current_scene_label": "桌边收事情，准备轻轻盯一下他的节奏",
            "daily_detail": "她这边水杯放在手边",
        },
    )
    product_store.set_app_setting(
        f"open_loop_state:{primary_scope.user_id}:{primary_scope.conversation_id}",
        {
            "open_loops": [
                {
                    "loop_uid": "loop_seed_running",
                    "status": "open",
                    "kind": "user_open_loop",
                    "content": "用户说周六早上跑步，回来告诉她感觉",
                    "priority": 0.8,
                    "prompt_count": 0,
                    "updated_at": "2026-04-25T00:00:00+00:00",
                }
            ],
            "history": [],
        },
    )
    product_store.record_health_check(
        component="chat",
        status="ok",
        message="chat ready",
        latency_ms=82.5,
        details={"seed": True},
    )
    product_store.record_health_check(
        component="search",
        status="degraded",
        message="search slower than usual",
        latency_ms=245.0,
        details={"seed": True},
    )
    product_store.record_turn_trace(
        turn_uid="turn-seed-primary",
        user_id=primary_scope.user_id,
        conversation_id=primary_scope.conversation_id,
        session_id=primary_scope.session_id,
        user_message_id=primary_user_message.id,
        assistant_message_id=primary_user_message.id + 1,
        request_type="chat",
        reply_goal="陪伴",
        scene="日常闲聊",
        mode_text="auto",
        model_name="gpt-4.1-mini",
        backup_model_name="gpt-4.1-mini",
        fallback_used=False,
        latency_ms=420.0,
        user_input="请记住我周六早上会去跑步。",
        assistant_reply="记住了，我会继续按这个节奏陪你。",
        attachments=[{"filename": "weekly-plan.txt"}],
        search_context=[{"query": "running routine", "note": "seed search note"}],
        planning={"request_id": "req_seed_primary", "scene": "日常闲聊"},
        retrieval={
            "used_prompt": {
                "long_term_memory_uids": [archive_memory_uid],
                "summary_included": True,
            }
        },
        metrics={
            "request_id": "req_seed_primary",
            "prompt_char_count": 340,
            "estimated_input_tokens": 96,
            "estimated_output_tokens": 72,
            "estimated_total_tokens": 168,
            "estimated_cost_usd": 0.00015,
            "attachment_count": 1,
            "search_count": 1,
            "stage_latency_ms": {"generation": 300.0, "retrieval": 60.0},
        },
    )

    retry_task_uid = product_store.enqueue_task(
        task_type="turn_postprocess",
        payload={"seed": "retry"},
        dedupe_key=None,
        user_id=primary_scope.user_id,
        conversation_id=primary_scope.conversation_id,
        session_id=primary_scope.session_id,
        priority=0.2,
    )
    boost_task_uid = product_store.enqueue_task(
        task_type="health_check",
        payload={"deep": False},
        dedupe_key=None,
        user_id=primary_scope.user_id,
        conversation_id=primary_scope.conversation_id,
        session_id=primary_scope.session_id,
        priority=0.2,
    )
    cancel_task_uid = product_store.enqueue_task(
        task_type="observability_cleanup",
        payload={},
        dedupe_key=None,
        user_id=primary_scope.user_id,
        conversation_id=primary_scope.conversation_id,
        session_id=primary_scope.session_id,
        priority=0.3,
    )
    if retry_task_uid is None or boost_task_uid is None or cancel_task_uid is None:
        raise AssertionError("failed to seed tasks")
    product_store.db.execute(
        """
        UPDATE background_tasks
        SET status = 'failed', attempts = max_attempts, finished_at = updated_at, last_error = 'seed failure'
        WHERE task_uid = ?
        """,
        (retry_task_uid,),
    )

    log_file = Path(settings.log_file_path)
    log_file.write_text(
        "\n".join(
            [
                "INFO Authorization: Bearer super-secret-token",
                "INFO password=topsecret",
                "INFO Prompt context for conversation-1: private raw prompt",
                "INFO ordinary line",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "primary_user_id": primary_scope.user_id,
        "primary_conversation_id": primary_scope.conversation_id,
        "secondary_user_id": secondary_scope.user_id,
        "secondary_conversation_id": secondary_scope.conversation_id,
        "archive_memory_uid": archive_memory_uid,
        "secondary_memory_uid": secondary_memory_uid,
        "approve_candidate_uid": approve_candidate_uid,
        "reject_candidate_uid": reject_candidate_uid,
        "secondary_candidate_uid": secondary_candidate_uid,
        "proactive_uid": proactive_uid,
        "retry_task_uid": retry_task_uid,
        "boost_task_uid": boost_task_uid,
        "cancel_task_uid": cancel_task_uid,
    }


def verify_reality_context(
    settings: Settings,
    product_store: ProductStore,
    memory_store: MemoryStore,
    client: TestClient,
    auth_headers: dict[str, str],
    artifacts: dict[str, str],
) -> RealityContextService:
    scope = ConversationScope(
        platform="discord",
        conversation_id=artifacts["primary_conversation_id"],
        user_id=artifacts["primary_user_id"],
        channel_id="chan-1",
        guild_id=None,
        session_id="verify-reality",
    )
    service = RealityContextService(settings=settings, product_store=product_store)
    tz = ZoneInfo(settings.bot_timezone)
    now = datetime.now(tz)

    async def fake_weather_payload(location: dict) -> dict:
        return {
            "current": {
                "time": now.isoformat(),
                "temperature_2m": 9.4,
                "apparent_temperature": 6.8,
                "precipitation": 0.2,
                "rain": 0.2,
                "snowfall": 0,
                "weather_code": 61,
                "wind_speed_10m": 22.0,
            },
            "daily": {
                "time": [now.strftime("%Y-%m-%d")],
                "temperature_2m_max": [12.0],
                "temperature_2m_min": [3.0],
                "precipitation_probability_max": [60],
            },
        }

    def ics_timestamp(value: datetime) -> str:
        return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    timed_start = now + timedelta(hours=2)
    timed_end = timed_start + timedelta(hours=1)
    repeat_start = now + timedelta(hours=4)
    repeat_end = repeat_start + timedelta(minutes=30)
    all_day = (now + timedelta(days=1)).date()
    ics_text = f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:timed-verify
SUMMARY:复盘 Cogniflow
DTSTART:{ics_timestamp(timed_start)}
DTEND:{ics_timestamp(timed_end)}
LOCATION:线上
END:VEVENT
BEGIN:VEVENT
UID:allday-verify
SUMMARY:全天整理
DTSTART;VALUE=DATE:{all_day.strftime('%Y%m%d')}
DTEND;VALUE=DATE:{(all_day + timedelta(days=1)).strftime('%Y%m%d')}
END:VEVENT
BEGIN:VEVENT
UID:repeat-verify
SUMMARY:喝水伸展
DTSTART:{ics_timestamp(repeat_start)}
DTEND:{ics_timestamp(repeat_end)}
RRULE:FREQ=DAILY;COUNT=2
END:VEVENT
END:VCALENDAR
"""
    raw_url = "https://calendar.example/private.ics?token=secret-token"

    async def fake_ics_text(url: str) -> str:
        if "secret-token" not in url:
            raise AssertionError(f"unexpected calendar URL requested: {url}")
        return ics_text

    service._fetch_weather_payload = fake_weather_payload  # type: ignore[method-assign]
    service._fetch_ics_text = fake_ics_text  # type: ignore[method-assign]
    service.add_calendar_source(scope, url=raw_url, label="verify private calendar")
    manual = service.add_manual_event(
        scope,
        title="手动补的晚间收尾",
        start_at=(now + timedelta(hours=6)).isoformat(),
        note="verify manual event",
    )
    if not manual.get("event_uid"):
        raise AssertionError(f"manual reality event did not persist: {manual}")

    asyncio.run(service.refresh_now(scope))
    payload = service.build_dashboard_payload(scope)
    if not payload["summary"]["weather"].get("summary_text"):
        raise AssertionError(f"weather summary missing: {payload}")
    events = payload["items"]
    titles = {item["title"] for item in events}
    for expected in {"复盘 Cogniflow", "全天整理", "喝水伸展", "手动补的晚间收尾"}:
        if expected not in titles:
            raise AssertionError(f"calendar event {expected!r} missing from reality context: {events}")
    context_block = service.build_context_block(scope)
    for forbidden in (raw_url, "secret-token", "open_meteo", "http://", "https://"):
        if forbidden in context_block:
            raise AssertionError(f"reality prompt leaked source detail {forbidden!r}: {context_block}")
    if "Reality Anchors" not in context_block or "复盘" not in context_block:
        raise AssertionError(f"reality context block missing usable anchors: {context_block}")
    sources = payload["summary"].get("sources") or []
    if not sources or any("secret-token" in str(source) for source in sources):
        raise AssertionError(f"dashboard sources leaked raw ICS token: {sources}")

    reality_payload = client.get("/api/reality-context").json()
    assert_panel_envelope(reality_payload, "reality context endpoint")
    location_response = client.patch(
        "/api/reality-context/location",
        json={"label": "河北省廊坊市大城县", "latitude": 38.6995, "longitude": 116.6371},
        headers=auth_headers,
    )
    assert_status(location_response, 200, "reality location patch")
    manual_response = client.post(
        "/api/reality-context/manual-events",
        json={"title": "Dashboard 补充事项", "start_at": (now + timedelta(hours=8)).isoformat()},
        headers=auth_headers,
    )
    assert_status(manual_response, 200, "reality manual event")

    day_engine = CompanionDayEngine(
        settings=settings,
        product_store=product_store,
        memory_store=memory_store,
        llm_client=FakeLLMClient(),
        reality_context=service,
    )
    plan = asyncio.run(day_engine.plan_next_event(scope))
    if plan is None:
        raise AssertionError("reality-aware day planner returned no event")
    if not plan.get("reality_anchor"):
        raise AssertionError(f"day planner did not use cached reality anchor: {plan}")
    for forbidden in ("API", "ICS", "http", "她说话", "她这边"):
        if forbidden in plan["content"]:
            raise AssertionError(f"reality-aware proactive content leaked tool/stage voice: {plan['content']}")
    if "（" not in plan["content"] or "）" not in plan["content"]:
        raise AssertionError(f"reality-aware proactive content should wrap action beats in parentheses: {plan['content']}")
    return service


def login_dashboard(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/api/login", json={"username": username, "password": password})
    assert_status(response, 200, "dashboard login")
    payload = response.json()
    csrf_token = payload.get("csrf_token")
    if not csrf_token:
        raise AssertionError("dashboard login did not return csrf_token")
    return payload


def verify_login_lockout(settings: Settings) -> None:
    with TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        lockout_settings = replace(
            settings,
            database_path=str(temp_dir / "lockout.sqlite3"),
            log_file_path=str(temp_dir / "lockout.log"),
        )
        database = Database(lockout_settings.database_path)
        database.initialize()
        memory_store = MemoryStore(database)
        product_store = ProductStore(database)
        app = build_dashboard_app(
            settings=lockout_settings,
            product_store=product_store,
            memory_store=memory_store,
            llm_client=FakeLLMClient(),
        )
        client = build_test_client(app, client_addr=("198.51.100.77", 50000))
        admin_client = build_test_client(app, client_addr=("203.0.113.88", 50000))

        try:
            _verify_login_lockout_clients(client, admin_client, lockout_settings)
        finally:
            database.close()


def _verify_login_lockout_clients(client: TestClient, admin_client: TestClient, settings: Settings) -> None:
    for attempt in range(settings.dashboard_login_max_attempts):
        response = client.post(
            "/api/login",
            json={"username": settings.dashboard_auth_username, "password": "wrong-password"},
        )
        assert_status(response, 401, f"lockout pre-threshold attempt {attempt + 1}")
    locked = client.post(
        "/api/login",
        json={"username": settings.dashboard_auth_username, "password": "wrong-password"},
    )
    assert_status(locked, 429, "login lockout threshold")
    payload = login_dashboard(admin_client, settings.dashboard_auth_username, settings.dashboard_auth_password)
    csrf_token = str(payload["csrf_token"])
    security_payload = admin_client.get("/api/security", headers={"x-csrf-token": csrf_token}).json()
    metrics = security_payload["metrics"]
    if metrics["failed_last_window"] < settings.dashboard_login_max_attempts:
        raise AssertionError(f"expected recorded login failures, got {metrics}")
    if metrics["lockouts_last_window"] < 1:
        raise AssertionError(f"expected at least one lockout, got {metrics}")
    if not any(item["source_ip"] == "198.51.100.77" for item in metrics["locked_sources"]):
        raise AssertionError(f"expected locked source IP in security metrics, got {metrics['locked_sources']}")


def verify_secure_session_cookie(
    settings: Settings,
    product_store: ProductStore,
    memory_store: MemoryStore,
) -> None:
    secure_settings = replace(settings, dashboard_session_https_only=True)
    app = build_dashboard_app(
        settings=secure_settings,
        product_store=product_store,
        memory_store=memory_store,
        llm_client=FakeLLMClient(),
    )
    client = TestClient(app)
    response = client.post(
        "/api/login",
        json={"username": settings.dashboard_auth_username, "password": settings.dashboard_auth_password},
    )
    assert_status(response, 200, "secure cookie login")
    set_cookie = response.headers.get("set-cookie", "")
    if "secure" not in set_cookie.lower():
        raise AssertionError(f"expected Secure attribute in session cookie, got {set_cookie!r}")


def verify_dashboard_endpoints(
    client: TestClient,
    settings: Settings,
    memory_store: MemoryStore,
    product_store: ProductStore,
    artifacts: dict[str, str],
) -> None:
    unauthorized = client.get("/api/overview", headers={"accept": "application/json"}, follow_redirects=False)
    assert_status(unauthorized, 401, "dashboard auth gate")
    assert_security_headers(unauthorized, "unauthorized overview headers")

    login_page = client.get("/login")
    assert_status(login_page, 200, "login page")
    assert_security_headers(login_page, "login page headers")

    verify_login_lockout(settings)
    payload = login_dashboard(client, settings.dashboard_auth_username, settings.dashboard_auth_password)
    csrf_token = str(payload["csrf_token"])
    auth_headers = {"x-csrf-token": csrf_token, "origin": "http://testserver"}

    home = client.get("/")
    assert_status(home, 200, "dashboard home")
    assert_security_headers(home, "dashboard home headers")

    overview_payload = client.get("/api/overview").json()
    if "overview" not in overview_payload or "active_scope" not in overview_payload:
        raise AssertionError(f"overview response shape mismatch: {overview_payload}")
    health_payload = client.get("/api/health").json()
    if "items" not in health_payload or "trends" not in health_payload:
        raise AssertionError(f"health response shape mismatch: {health_payload}")
    memories_payload = client.get("/api/memories").json()
    candidates_payload = client.get("/api/candidates").json()
    assert_panel_envelope(memories_payload, "memories after login")
    assert_panel_envelope(candidates_payload, "candidates after login")

    negative_logs = client.get("/api/logs?lines=-1")
    assert_status(negative_logs, 422, "negative log lines rejected")

    logs_response = client.get("/api/logs?lines=999")
    assert_status(logs_response, 200, "logs endpoint")
    logs_payload = logs_response.json()
    assert_panel_envelope(logs_payload, "logs envelope")
    log_lines = [item["text"] for item in logs_payload["items"]]
    if len(log_lines) != settings.dashboard_log_max_lines:
        raise AssertionError(f"log line clamp failed: expected {settings.dashboard_log_max_lines}, got {len(log_lines)}")
    joined_logs = "".join(log_lines)
    for secret in ("super-secret-token", "topsecret", "private raw prompt"):
        if secret in joined_logs:
            raise AssertionError(f"log redaction failed for secret: {secret}")

    security_payload = client.get("/api/security").json()
    metrics = security_payload["metrics"]
    if not any(event["event_type"] == "login_success" for event in security_payload["events"]):
        raise AssertionError("security event list did not record successful login")

    scopes_payload = client.get("/api/scopes").json()
    if scopes_payload["active_scope"]["conversation_id"] != artifacts["primary_conversation_id"]:
        raise AssertionError(f"unexpected initial active scope: {scopes_payload['active_scope']}")
    if len(scopes_payload["items"]) < 2:
        raise AssertionError(f"expected at least two scopes, got {scopes_payload['items']}")

    memory_items = memories_payload["items"]
    if {item["user_id"] for item in memory_items} != {artifacts["primary_user_id"]}:
        raise AssertionError(f"memories were not filtered to active scope: {memory_items}")
    top_hits = memories_payload["highlights"].get("top_hits", [])
    if not isinstance(top_hits, list):
        raise AssertionError(f"memories top_hits missing: {memories_payload}")

    candidate_items = candidates_payload["items"]
    candidate_ids = {item["candidate_uid"] for item in candidate_items}
    expected_primary_candidates = {artifacts["approve_candidate_uid"], artifacts["reject_candidate_uid"]}
    if candidate_ids != expected_primary_candidates:
        raise AssertionError(f"unexpected primary pending candidates: {candidate_ids}")

    before_day_long_term_count = product_store.db.fetchone("SELECT COUNT(*) AS count FROM long_term_memories")["count"]
    companion_day_payload = client.get("/api/companion-day").json()
    assert_panel_envelope(companion_day_payload, "companion day endpoint")
    route = companion_day_payload["summary"].get("route") or {}
    if not route.get("route_uid") or not route.get("current_scene"):
        raise AssertionError(f"companion day route missing from endpoint: {companion_day_payload}")
    if "她说话" in route.get("current_scene", ""):
        raise AssertionError(f"companion day route leaked third-person self narration: {route}")

    companion_patch = client.patch(
        "/api/companion-day",
        json={"current_scene": "我这边刚把灯压低一点，等他回声", "mood_label": "想他但不催太急", "longing_level": 0.73, "quiet_mode": False},
        headers=auth_headers,
    )
    assert_status(companion_patch, 200, "companion day patch")
    updated_day = client.get("/api/companion-day").json()["summary"]["route"]
    if updated_day.get("current_scene") != "我这边刚把灯压低一点，等他回声":
        raise AssertionError(f"companion day manual patch did not persist: {updated_day}")

    reality_service = verify_reality_context(settings, product_store, memory_store, client, auth_headers, artifacts)
    day_engine = CompanionDayEngine(
        settings=settings,
        product_store=product_store,
        memory_store=memory_store,
        llm_client=FakeLLMClient(),
        reality_context=reality_service,
    )
    day_scope = ConversationScope(
        platform="discord",
        conversation_id=artifacts["primary_conversation_id"],
        user_id=artifacts["primary_user_id"],
        channel_id="chan-1",
        guild_id=None,
        session_id="verify-companion-day",
    )
    plan = asyncio.run(day_engine.plan_next_event(day_scope))
    if plan is None:
        raise AssertionError("companion day planner unexpectedly returned no event")
    if any(token in plan["content"] for token in ("她说话", "她这边", "脑子里就很自然")):
        raise AssertionError(f"companion day event should stay first-person: {plan['content']}")
    if "（" not in plan["content"] or "）" not in plan["content"]:
        raise AssertionError(f"companion day event should wrap action beats in full-width parentheses: {plan['content']}")
    event = day_engine.record_event_sent(day_scope, plan=plan, proactive_uid="verify-proactive-day")
    product_store.update_companion_day_event(event["event_uid"], {"response_deadline_at": "2000-01-01T00:00:00+00:00"})
    followup = asyncio.run(day_engine.plan_next_event(day_scope))
    if followup is None or followup.get("event_type") != "unanswered_followup":
        raise AssertionError(f"companion day unanswered follow-up did not plan once: {followup}")
    followup_event = day_engine.record_event_sent(day_scope, plan=followup, proactive_uid="verify-proactive-followup")
    feedback_response = client.post(
        f"/api/companion-day/events/{followup_event['event_uid']}/feedback",
        json={"feedback": "good", "note": "verify day feedback"},
        headers=auth_headers,
    )
    assert_status(feedback_response, 200, "companion day event feedback")
    day_engine.record_user_turn(
        day_scope,
        user_text="我回来了，刚才在收东西。",
        assistant_text="我这边刚把杯子放下，继续等你说完。",
        user_message_id=12345,
        attachment_insights=[
            AttachmentInsight(
                filename="voice.ogg",
                artifact_type="audio",
                content_type="audio/ogg",
                extracted_text="我刚刚在路上，马上回你。",
                summary_text="用户用语音说马上回你。",
            )
        ],
    )
    diary_entries = product_store.list_shared_diary_entries(
        user_id=artifacts["primary_user_id"],
        conversation_id=artifacts["primary_conversation_id"],
        limit=20,
    )
    if not diary_entries or not any(item["entry_type"] == "voice_input" for item in diary_entries):
        raise AssertionError(f"shared diary did not record day/voice entries: {diary_entries}")
    after_day_long_term_count = product_store.db.fetchone("SELECT COUNT(*) AS count FROM long_term_memories")["count"]
    if after_day_long_term_count != before_day_long_term_count:
        raise AssertionError("companion day engine wrote role daily events into long_term_memories")
    regenerate_day = client.post("/api/companion-day/regenerate", headers=auth_headers)
    assert_status(regenerate_day, 200, "companion day regenerate")

    missing_csrf = client.post(f"/api/candidates/{artifacts['approve_candidate_uid']}/approve", json={"note": "missing csrf"})
    assert_status(missing_csrf, 403, "approve candidate requires csrf")

    wrong_origin = client.post(
        f"/api/candidates/{artifacts['approve_candidate_uid']}/approve",
        json={"note": "wrong origin"},
        headers={"x-csrf-token": csrf_token, "origin": "http://evil.example"},
    )
    assert_status(wrong_origin, 403, "approve candidate requires same origin")

    failed_batch = client.post(
        "/api/candidates/batch-review",
        json={
            "candidate_uids": [artifacts["approve_candidate_uid"], "cand_missing"],
            "action": "approve",
            "note": "should rollback",
        },
        headers=auth_headers,
    )
    assert_status(failed_batch, 404, "batch candidate approval missing id rolls back")
    rolled_back_candidate = product_store.get_candidate_memory(artifacts["approve_candidate_uid"])
    if rolled_back_candidate is None or rolled_back_candidate.status != "pending" or rolled_back_candidate.approved_memory_uid:
        raise AssertionError(f"batch approval partially committed: {rolled_back_candidate}")

    approve_response = client.post(
        f"/api/candidates/{artifacts['approve_candidate_uid']}/approve",
        json={"note": "verified approve"},
        headers=auth_headers,
    )
    assert_status(approve_response, 200, "approve candidate")
    approved_candidate = product_store.get_candidate_memory(artifacts["approve_candidate_uid"])
    if approved_candidate is None or approved_candidate.status != "approved" or not approved_candidate.approved_memory_uid:
        raise AssertionError("candidate approval did not persist approved state")
    approved_memory = product_store.get_long_term_memory(approved_candidate.approved_memory_uid)
    if approved_memory is None or approved_memory["status"] != "active":
        raise AssertionError("candidate approval did not create active long-term memory")

    second_review = client.post(
        f"/api/candidates/{artifacts['approve_candidate_uid']}/reject",
        json={"note": "should fail"},
        headers=auth_headers,
    )
    assert_status(second_review, 409, "approved candidate cannot be rejected again")

    reject_response = client.post(
        f"/api/candidates/{artifacts['reject_candidate_uid']}/reject",
        json={"note": "verified reject"},
        headers=auth_headers,
    )
    assert_status(reject_response, 200, "reject pending candidate")
    rejected_candidate = product_store.get_candidate_memory(artifacts["reject_candidate_uid"])
    if rejected_candidate is None or rejected_candidate.status != "rejected":
        raise AssertionError("candidate rejection did not persist rejected state")

    pending_candidates = client.get("/api/candidates").json()["items"]
    if pending_candidates:
        raise AssertionError(f"default candidate list should only contain pending items, got {pending_candidates}")
    all_candidates = client.get("/api/candidates?status=all").json()["items"]
    all_statuses = sorted(item["status"] for item in all_candidates)
    if all_statuses != ["approved", "rejected"]:
        raise AssertionError(f"candidate all-status view mismatch: {all_statuses}")

    missing_archive = client.post("/api/memories/mem_missing/archive", headers=auth_headers)
    assert_status(missing_archive, 404, "archive missing memory")

    archive_response = client.post(f"/api/memories/{artifacts['archive_memory_uid']}/archive", headers=auth_headers)
    assert_status(archive_response, 200, "archive active memory")
    archived_memory = product_store.get_long_term_memory(artifacts["archive_memory_uid"])
    if archived_memory is None or archived_memory["status"] != "archived":
        raise AssertionError("memory archive did not persist archived state")

    archive_again = client.post(f"/api/memories/{artifacts['archive_memory_uid']}/archive", headers=auth_headers)
    assert_status(archive_again, 409, "cannot archive memory twice")

    audits_response = client.get("/api/audits")
    assert_status(audits_response, 200, "audit endpoint")
    audits = audits_response.json()["items"]
    archive_audit = next((item for item in audits if item["action_type"] == "memory_archive"), None)
    reject_audit = next((item for item in audits if item["action_type"] == "candidate_reject"), None)
    if archive_audit is None or reject_audit is None:
        raise AssertionError(f"expected archive/reject audits, got {audits}")
    if not archive_audit["actor_username"]:
        raise AssertionError(f"expected actor in audit trail, got {archive_audit}")

    undo_archive = client.post(f"/api/audits/{archive_audit['audit_uid']}/undo", headers=auth_headers)
    assert_status(undo_archive, 200, "undo archived memory")
    restored_memory = product_store.get_long_term_memory(artifacts["archive_memory_uid"])
    if restored_memory is None or restored_memory["status"] != "active":
        raise AssertionError("undo did not restore archived memory")

    undo_reject = client.post(f"/api/audits/{reject_audit['audit_uid']}/undo", headers=auth_headers)
    assert_status(undo_reject, 200, "undo rejected candidate")
    reopened_candidate = product_store.get_candidate_memory(artifacts["reject_candidate_uid"])
    if reopened_candidate is None or reopened_candidate.status != "pending":
        raise AssertionError("undo did not reopen rejected candidate")

    scopes_update = client.post(
        "/api/scopes/active",
        json={
            "user_id": artifacts["secondary_user_id"],
            "conversation_id": artifacts["secondary_conversation_id"],
        },
        headers=auth_headers,
    )
    assert_status(scopes_update, 200, "update active scope")
    active_scope = scopes_update.json()["active_scope"]
    if active_scope["conversation_id"] != artifacts["secondary_conversation_id"]:
        raise AssertionError(f"scope update did not switch conversation: {active_scope}")

    secondary_memories = client.get("/api/memories").json()["items"]
    secondary_memory_ids = {item["memory_uid"] for item in secondary_memories}
    if secondary_memory_ids != {artifacts["secondary_memory_uid"]}:
        raise AssertionError(f"secondary scope memory filter mismatch: {secondary_memories}")
    secondary_candidates = client.get("/api/candidates").json()["items"]
    secondary_candidate_ids = {item["candidate_uid"] for item in secondary_candidates}
    if secondary_candidate_ids != {artifacts["secondary_candidate_uid"]}:
        raise AssertionError(f"secondary scope candidate filter mismatch: {secondary_candidates}")

    invalid_mode = client.post(
        "/api/modes",
        json={"mode": "turbo"},
        headers=auth_headers,
    )
    assert_status(invalid_mode, 422, "invalid mode rejected")

    missing_custom_model = client.post(
        "/api/modes",
        json={"mode": "custom"},
        headers=auth_headers,
    )
    assert_status(missing_custom_model, 422, "custom mode requires custom_model")

    wrong_scope = client.post(
        "/api/modes",
        json={"mode": "fast", "user_id": artifacts["primary_user_id"]},
        headers=auth_headers,
    )
    assert_status(wrong_scope, 403, "mode update scope restriction")

    valid_mode = client.post(
        "/api/modes",
        json={"mode": "custom", "custom_model": "gpt-4.1-mini", "learning_mode": True},
        headers=auth_headers,
    )
    assert_status(valid_mode, 200, "valid custom mode update")
    mode_payload = client.get("/api/modes").json()
    if mode_payload.get("mode") != "custom" or mode_payload.get("custom_model") != "gpt-4.1-mini":
        raise AssertionError(f"mode update result mismatch: {mode_payload}")

    retry_response = client.post(f"/api/tasks/{artifacts['retry_task_uid']}/retry", headers=auth_headers)
    assert_status(retry_response, 200, "retry failed task")
    if product_store.get_task(artifacts["retry_task_uid"]).status != "pending":
        raise AssertionError("retry endpoint did not reopen failed task")

    boost_response = client.post(
        f"/api/tasks/{artifacts['boost_task_uid']}/boost",
        json={"priority": 1.0},
        headers=auth_headers,
    )
    assert_status(boost_response, 200, "boost pending task")
    boosted_task = product_store.get_task(artifacts["boost_task_uid"])
    if boosted_task is None or boosted_task.priority != 1.0:
        raise AssertionError(f"boost endpoint did not update priority: {boosted_task}")

    cancel_response = client.post(f"/api/tasks/{artifacts['cancel_task_uid']}/cancel", headers=auth_headers)
    assert_status(cancel_response, 200, "cancel pending task")
    if product_store.get_task(artifacts["cancel_task_uid"]).status != "cancelled":
        raise AssertionError("cancel endpoint did not cancel task")

    password_change = client.post(
        "/api/account/password",
        json={
            "old_password": settings.dashboard_auth_password,
            "new_password": "verify-password-updated",
            "confirm_password": "verify-password-updated",
        },
        headers=auth_headers,
    )
    assert_status(password_change, 200, "password change")

    logout_response = client.post("/api/logout", headers=auth_headers)
    assert_status(logout_response, 200, "dashboard logout")
    locked_overview = client.get("/api/overview", headers={"accept": "application/json"}, follow_redirects=False)
    assert_status(locked_overview, 401, "dashboard requires auth after logout")

    old_password_login = client.post(
        "/api/login",
        json={"username": settings.dashboard_auth_username, "password": settings.dashboard_auth_password},
    )
    assert_status(old_password_login, 401, "old password rejected after password change")
    new_password_payload = login_dashboard(client, settings.dashboard_auth_username, "verify-password-updated")
    if not new_password_payload.get("csrf_token"):
        raise AssertionError("new dashboard password login did not return csrf token")
    csrf_token = str(new_password_payload["csrf_token"])
    auth_headers = {"x-csrf-token": csrf_token, "origin": "http://testserver"}
    client.post(
        "/api/scopes/active",
        json={
            "user_id": artifacts["primary_user_id"],
            "conversation_id": artifacts["primary_conversation_id"],
        },
        headers=auth_headers,
    )

    attachments_payload = client.get("/api/attachments").json()
    facts_payload = client.get("/api/facts").json()
    relationships_payload = client.get("/api/relationships").json()
    summaries_payload = client.get("/api/summaries").json()
    turns_payload = client.get("/api/turns").json()
    tasks_payload = client.get("/api/tasks").json()
    errors_payload = client.get("/api/errors").json()
    audits_payload = client.get("/api/audits").json()
    proactive_payload = client.get("/api/proactive").json()
    presence_payload = client.get("/api/presence").json()
    reality_payload = client.get("/api/reality-context").json()
    performance_payload = client.get("/api/performance").json()
    search_payload = client.get("/api/search?q=跑步").json()
    snapshots_payload = client.get("/api/snapshots").json()

    for label, payload in {
        "attachments": attachments_payload,
        "facts": facts_payload,
        "relationships": relationships_payload,
        "summaries": summaries_payload,
        "turns": turns_payload,
        "tasks": tasks_payload,
        "errors": errors_payload,
        "audits": audits_payload,
        "proactive": proactive_payload,
        "presence": presence_payload,
        "reality": reality_payload,
        "snapshots": snapshots_payload,
    }.items():
        assert_panel_envelope(payload, f"{label} endpoint")

    if not attachments_payload["items"]:
        raise AssertionError("attachments endpoint did not expose seeded artifact")
    if not facts_payload["items"]:
        raise AssertionError("facts endpoint did not expose seeded structured fact")
    if not relationships_payload["items"]:
        raise AssertionError("relationships endpoint did not expose seeded relationship state")
    if not summaries_payload["items"]:
        raise AssertionError("summaries endpoint did not expose seeded summary")
    if not turns_payload["items"] or "request_id" not in turns_payload["items"][0]:
        raise AssertionError(f"turn endpoint missing request_id observability: {turns_payload}")
    if not tasks_payload["items"]:
        raise AssertionError("tasks endpoint missing items")
    if "status_counts" not in errors_payload["summary"]:
        raise AssertionError(f"errors endpoint missing status summary: {errors_payload}")
    if not presence_payload["items"] or presence_payload["items"][0]["loop_uid"] != "loop_seed_running":
        raise AssertionError(f"presence endpoint did not expose open-loop ledger: {presence_payload}")
    presence_update = client.post(
        "/api/presence",
        json={"current_scene_label": "刚把灯压低一点，准备陪他收尾", "note": "verify manual update"},
        headers=auth_headers,
    )
    assert_status(presence_update, 200, "presence update")
    updated_presence = client.get("/api/presence").json()["summary"]["presence_state"]
    if updated_presence.get("current_scene_label") != "刚把灯压低一点，准备陪他收尾":
        raise AssertionError(f"presence manual update did not persist: {updated_presence}")
    proactive_feedback = client.post(
        f"/api/proactive/{artifacts['proactive_uid']}/feedback",
        json={"feedback": "too_frequent", "note": "verify feedback"},
        headers=auth_headers,
    )
    assert_status(proactive_feedback, 200, "proactive feedback")
    proactive_record = product_store.get_proactive_message(artifacts["proactive_uid"])
    if proactive_record is None or proactive_record.metadata.get("dashboard_feedback", {}).get("feedback") != "too_frequent":
        raise AssertionError(f"proactive feedback did not update metadata: {proactive_record}")
    prefs_after_feedback = get_proactive_preferences(
        settings=settings,
        product_store=product_store,
        memory_store=memory_store,
        user_id=proactive_record.user_id,
        conversation_id=proactive_record.conversation_id,
    )
    if prefs_after_feedback.get("cadence") != "low":
        raise AssertionError(f"too_frequent feedback should lower cadence to low: {prefs_after_feedback}")
    backoff = product_store.get_app_setting(f"proactive_backoff:{proactive_record.conversation_id}", {})
    if not isinstance(backoff, dict) or not backoff.get("until"):
        raise AssertionError(f"too_frequent feedback should write proactive backoff: {backoff}")
    prefs_get = client.get("/api/proactive/preferences", headers=auth_headers)
    assert_status(prefs_get, 200, "proactive preferences get")
    prefs_patch = client.patch(
        "/api/proactive/preferences",
        json={"enabled": True, "cadence": "normal"},
        headers=auth_headers,
    )
    assert_status(prefs_patch, 200, "proactive preferences patch")
    mobile_prefs = client.patch("/mobile/proactive/preferences", json={"enabled": False, "cadence": "low"})
    assert_status(mobile_prefs, 200, "mobile proactive preferences patch")
    if mobile_prefs.json()["preferences"].get("enabled") is not False:
        raise AssertionError(f"mobile proactive preferences did not update enabled: {mobile_prefs.json()}")
    legacy_scope = ConversationScope(
        platform="discord",
        conversation_id="discord:legacy-proactive:legacy-channel",
        user_id="legacy-proactive",
        channel_id="legacy-channel",
        guild_id=None,
        session_id="legacy-proactive",
    )
    memory_store.upsert_structured_fact(
        legacy_scope.user_id,
        namespace="support",
        key="proactive_opt_in",
        value="off",
        confidence=1.0,
        source_message_ids=[],
        metadata={"source": "verify_legacy"},
    )
    legacy_prefs = get_proactive_preferences(
        settings=settings,
        product_store=product_store,
        memory_store=memory_store,
        user_id=legacy_scope.user_id,
        conversation_id=legacy_scope.conversation_id,
    )
    if legacy_prefs.get("enabled") is not False or legacy_prefs.get("legacy") is not True:
        raise AssertionError(f"legacy proactive opt-in should map to preferences: {legacy_prefs}")
    if "performance" not in performance_payload or "json_extraction" not in performance_payload:
        raise AssertionError(f"performance response missing sections: {performance_payload}")
    if search_payload["total_hits"] < 1:
        raise AssertionError(f"global search did not return seeded hit: {search_payload}")


def verify_auth_disabled_dashboard(
    settings: Settings,
    product_store: ProductStore,
    memory_store: MemoryStore,
) -> None:
    auth_disabled_settings = replace(
        settings,
        dashboard_auth_enabled=False,
        dashboard_auth_password="",
        dashboard_auth_password_generated=False,
        dashboard_session_secret="",
    )
    auth_disabled_app = build_dashboard_app(
        settings=auth_disabled_settings,
        product_store=product_store,
        memory_store=memory_store,
        llm_client=FakeLLMClient(),
    )
    auth_disabled_client = TestClient(auth_disabled_app)
    home_response = auth_disabled_client.get("/")
    assert_status(home_response, 200, "dashboard home without auth middleware")
    assert_security_headers(home_response, "auth disabled dashboard headers")


def verify_proactive_planner_sanitizes_abstract_commitment(
    settings: Settings,
    product_store: ProductStore,
    memory_store: MemoryStore,
) -> None:
    scope = ConversationScope(
        platform="discord",
        conversation_id="discord:user-abstract:chan-abstract",
        user_id="user-abstract",
        channel_id="chan-abstract",
        guild_id=None,
        session_id="session-abstract",
    )
    user_message = memory_store.insert_message(
        scope,
        sender_type="user",
        content="今天普通聊两句。",
        context=MessageContext(platform_message_id="m-abstract-user", author_id=scope.user_id),
        metadata={},
    )
    memory_uid = memory_store.insert_or_merge_long_term_memory(
        scope,
        memory_type="commitment_record",
        category="relationship",
        content="沈知微承诺成为用户最稳固的后方和确定感，无论外部世界如何变化或Cogniflow面临困难，她都会是他的依靠。",
        tags=["relationship"],
        confidence=0.9,
        importance=0.9,
        source_message_ids=[user_message.id],
        metadata={"seed": "abstract_commitment"},
    )
    product_store.record_memory_hits(scope.user_id, [memory_uid], context_type="verify")
    service = ProactiveMessageService(settings=settings, memory_store=memory_store, product_store=product_store, llm_client=FakeLLMClient())
    plan = asyncio.run(service._plan_trigger(scope, []))  # noqa: SLF001
    message = plan["content"]
    if plan["trigger_type"] == "open_loop_follow_up":
        raise AssertionError(f"abstract commitment should not become open-loop trigger: {plan}")
    if message != "（我抬头看了眼屏幕）我刚才想起你，就过来碰你一下。你在的话回我一声。":
        raise AssertionError(f"proactive did not use the model draft exactly: {message}")
    for forbidden in ("沈知微承诺", "用户最稳固", "Cogniflow面临困难", "依靠。。"):
        if forbidden in message:
            raise AssertionError(f"proactive message leaked abstract commitment memory: {message}")

    failing = ProactiveMessageService(settings=settings, memory_store=memory_store, product_store=product_store, llm_client=FakeLLMClient(fail=True))
    try:
        asyncio.run(failing._plan_trigger(scope, []))  # noqa: SLF001
    except RuntimeError as exc:
        failing._record_model_failure(scope.conversation_id, "verify_proactive_plan", exc)  # noqa: SLF001
    else:
        raise AssertionError("expected fake proactive model failure")
    failure_record = product_store.get_app_setting(f"proactive_model_failure:{scope.conversation_id}", {})
    backoff_record = product_store.get_app_setting(f"proactive_backoff:{scope.conversation_id}", {})
    if failure_record.get("stage") != "verify_proactive_plan" or not backoff_record.get("until"):
        raise AssertionError(f"proactive model failure was not recorded: failure={failure_record}, backoff={backoff_record}")


def verify_proactive_preferences_cadence_and_context(
    settings: Settings,
    product_store: ProductStore,
    memory_store: MemoryStore,
) -> None:
    active_settings = replace(
        settings,
        enable_proactive_messages=True,
        proactive_opt_in_required=False,
        companion_day_engine_enabled=False,
        human_presence_enabled=False,
        proactive_response_window_hours=1,
    )
    scope = ConversationScope(
        platform="discord",
        conversation_id="discord:user-proactive-cadence:123",
        user_id="user-proactive-cadence",
        channel_id="123",
        guild_id=None,
        session_id="session-proactive-cadence",
    )
    user_message = memory_store.insert_message(
        scope,
        sender_type="user",
        content="我等会儿要继续写 Cogniflow，先记一下。",
        context=MessageContext(platform_message_id="proactive-cadence-user", author_id=scope.user_id),
        metadata={},
    )
    old_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    product_store.db.execute("UPDATE messages SET created_at = ? WHERE id = ?", (old_at, user_message.id))
    memory_store.insert_summary(
        scope,
        content="用户最近在推进 Cogniflow，也希望沈知微提醒得克制一点。",
        message_start_id=user_message.id,
        message_end_id=user_message.id,
        message_count=1,
        version=1,
    )
    memory_store.insert_or_merge_long_term_memory(
        scope,
        memory_type="project_context",
        category="project",
        content="用户正在推进 Cogniflow，需要提醒但不希望太频繁。",
        tags=["project", "cogniflow"],
        confidence=0.9,
        importance=0.8,
        source_message_ids=[user_message.id],
    )
    memory_store.upsert_relationship_state(
        scope.user_id,
        dimension="interaction_rhythm",
        value="主动关心要有，但需要低频、克制、承接上下文。",
        weight=0.9,
        confidence=0.9,
        note="verify proactive rhythm",
        source_message_ids=[user_message.id],
    )

    service_llm = FakeLLMClient()
    service = ProactiveMessageService(
        settings=active_settings,
        memory_store=memory_store,
        product_store=product_store,
        llm_client=service_llm,
    )
    channel = FakeDiscordChannel()
    client = FakeDiscordClient(channel)
    result = asyncio.run(service.scan_and_send(client))  # type: ignore[arg-type]
    if result.get("sent") != 1 or len(channel.messages) != 1:
        raise AssertionError(f"first proactive scan should send once: result={result}, messages={channel.messages}")
    prompt = service_llm.calls[-1]["user_prompt"]
    for expected in ("proactive_context", "recent_messages", "summary", "long_term_memories", "relationship_states", "presence_state"):
        if expected not in prompt:
            raise AssertionError(f"proactive prompt missing {expected}: {prompt}")

    second = asyncio.run(service.scan_and_send(client))  # type: ignore[arg-type]
    if second.get("sent") != 0 or second.get("skipped_unanswered", 0) + second.get("skipped_interval", 0) < 1:
        raise AssertionError(f"low cadence should block immediate repeat: {second}")

    set_proactive_preferences(
        settings=active_settings,
        product_store=product_store,
        memory_store=memory_store,
        user_id=scope.user_id,
        conversation_id=scope.conversation_id,
        enabled=False,
        source="verify",
    )
    disabled = asyncio.run(service.scan_and_send(client))  # type: ignore[arg-type]
    if disabled.get("sent") != 0 or disabled.get("skipped_disabled", 0) < 1:
        raise AssertionError(f"disabled proactive preferences should skip scan: {disabled}")

    set_proactive_preferences(
        settings=active_settings,
        product_store=product_store,
        memory_store=memory_store,
        user_id=scope.user_id,
        conversation_id=scope.conversation_id,
        enabled=True,
        source="verify",
    )
    for index in range(4):
        uid = product_store.create_proactive_message(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            channel_id=scope.channel_id,
            trigger_type="verify_daily_limit",
            opening_text=f"verify daily limit {index}",
        )
        product_store.db.execute(
            "UPDATE proactive_messages SET status = 'responded', sent_at = ?, updated_at = ? WHERE proactive_uid = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=200 + index)).isoformat(), iso_utc_now(), uid),
        )
    daily_limited = asyncio.run(service.scan_and_send(client))  # type: ignore[arg-type]
    if daily_limited.get("sent") != 0 or daily_limited.get("skipped_daily_limit", 0) < 1:
        raise AssertionError(f"daily cap should skip proactive scan: {daily_limited}")

    expired_uid = product_store.create_proactive_message(
        user_id=scope.user_id,
        conversation_id=scope.conversation_id,
        channel_id=scope.channel_id,
        trigger_type="miss_you",
        opening_text="（我轻轻碰了下屏幕）你在的话回我一下。",
    )
    expired_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    product_store.db.execute(
        "UPDATE proactive_messages SET sent_at = ?, updated_at = ? WHERE proactive_uid = ?",
        (expired_at, expired_at, expired_uid),
    )
    asyncio.run(service.scan_and_send(client))  # type: ignore[arg-type]
    state = service.presence_state.get_state(scope)
    proactive_context = state.get("proactive_context") or {}
    if proactive_context.get("last_status") != "expired" or int(proactive_context.get("unanswered_count") or 0) < 1:
        raise AssertionError(f"expired proactive should sync presence context: {proactive_context}")
    before_response_hurt = float((state.get("assistant_emotion_state") or {}).get("hurt") or 0)
    service.presence_state.record_proactive_response(scope, proactive_uid=expired_uid, response_message_id=999, response_latency_minutes=120)
    responded = service.presence_state.get_state(scope)
    if int((responded.get("proactive_context") or {}).get("unanswered_count") or 0) != 0:
        raise AssertionError(f"proactive response should clear unanswered count: {responded.get('proactive_context')}")
    after_response_hurt = float((responded.get("assistant_emotion_state") or {}).get("hurt") or 0)
    if after_response_hurt >= before_response_hurt:
        raise AssertionError(f"proactive response should soften hurt: before={before_response_hurt}, after={after_response_hurt}")


def verify_presence_sleep_and_emotion_state(
    settings: Settings,
    product_store: ProductStore,
    memory_store: MemoryStore,
) -> None:
    scope = ConversationScope(
        platform="discord",
        conversation_id="discord:user-presence:chan-presence",
        user_id="user-presence",
        channel_id="chan-presence",
        guild_id=None,
        session_id="session-presence",
    )
    service = PresenceStateService(settings=settings, product_store=product_store, memory_store=memory_store, llm_client=FakeLLMClient())

    def insert_and_update(text: str, platform_id: str) -> dict:
        message = memory_store.insert_message(
            scope,
            sender_type="user",
            content=text,
            context=MessageContext(platform_message_id=platform_id, author_id=scope.user_id),
            metadata={},
        )
        return asyncio.run(service.update_from_user_message(scope, text, message_id=message.id))

    asleep = insert_and_update("我先睡了晚安", "presence-sleep")
    if asleep.get("user_sleep_state") != "asleep":
        raise AssertionError(f"explicit sleep should mark asleep: {asleep}")
    insomnia = insert_and_update("睡不着，有点烦。", "presence-insomnia")
    if insomnia.get("user_sleep_state") != "awake":
        raise AssertionError(f"insomnia should mark awake: {insomnia}")
    tired = insert_and_update("困了但还要写一会儿。", "presence-tired")
    if tired.get("user_sleep_state") == "asleep":
        raise AssertionError(f"tired but active should not mark asleep: {tired}")

    expired_state = dict(tired)
    expired_state["user_sleep_state"] = "asleep"
    expired_state["user_sleep_state_confidence"] = 0.91
    expired_state["sleep_state_expires_at"] = "2000-01-01T00:00:00+00:00"
    product_store.set_app_setting(f"presence_state:{scope.user_id}:{scope.conversation_id}", expired_state)
    expired = service.get_state(scope)
    if expired.get("user_sleep_state") not in {"unknown", "probably_awake", "probably_asleep"}:
        raise AssertionError(f"expired sleep state should degrade: {expired}")

    before = service.get_state(scope)["assistant_emotion_state"]
    service.record_unanswered_proactive(scope, source_id="verify")
    unanswered = service.get_state(scope)["assistant_emotion_state"]
    if float(unanswered.get("hurt") or 0) <= float(before.get("hurt") or 0):
        raise AssertionError(f"unanswered proactive should raise hurt: before={before}, after={unanswered}")
    service.record_proactive_feedback(scope, proactive_uid="pro-verify", trigger_type="miss_you", feedback="good")
    good = service.get_state(scope)["assistant_emotion_state"]
    if float(good.get("hurt") or 0) >= float(unanswered.get("hurt") or 0):
        raise AssertionError(f"good feedback should lower hurt: before={unanswered}, after={good}")
    service.record_proactive_feedback(scope, proactive_uid="pro-verify", trigger_type="miss_you", feedback="bad")
    bad = service.get_state(scope)["assistant_emotion_state"]
    if float(bad.get("caution") or 0) <= float(good.get("caution") or 0):
        raise AssertionError(f"bad feedback should raise caution: before={good}, after={bad}")

    vulnerable = insert_and_update("我有点崩溃，撑不住了。", "presence-vulnerable")
    emotion = vulnerable["assistant_emotion_state"]
    if float(emotion.get("caution") or 0) < 0.1 or float(emotion.get("worry") or 0) <= float(bad.get("worry") or 0):
        raise AssertionError(f"vulnerable user state should soften assistant emotion: {emotion}")


def main() -> None:
    with TemporaryDirectory(prefix="zhiwei-verify-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        ensure_required_env(temp_dir)
        settings = Settings.load()
        database = Database(settings.database_path)
        database.initialize()
        memory_store = MemoryStore(database)
        product_store = ProductStore(database)
        artifacts = seed_dashboard_data(settings, memory_store, product_store)

        fake_llm = FakeLLMClient()
        app = build_dashboard_app(settings=settings, product_store=product_store, memory_store=memory_store, llm_client=fake_llm)
        client = TestClient(app)
        verify_secure_session_cookie(settings, product_store, memory_store)
        verify_dashboard_endpoints(client, settings, memory_store, product_store, artifacts)
        verify_auth_disabled_dashboard(settings, product_store, memory_store)
        verify_proactive_planner_sanitizes_abstract_commitment(settings, product_store, memory_store)
        verify_proactive_preferences_cadence_and_context(settings, product_store, memory_store)
        verify_presence_sleep_and_emotion_state(settings, product_store, memory_store)
        database.close()
        print("verify_product.py: all dashboard P0/P1 regression checks passed.")


if __name__ == "__main__":
    main()
