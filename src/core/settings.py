from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from src.core.exceptions import ConfigurationError


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None, default: int) -> int:
    if value in (None, ""):
        return default
    return int(value)


def _parse_float(value: str | None, default: float) -> float:
    if value in (None, ""):
        return default
    return float(value)


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _parse_channel_ids(value: str | None) -> set[int]:
    if value in (None, ""):
        return set()
    return {int(part.strip()) for part in value.split(",") if part.strip()}


@dataclass
class Settings:
    discord_bot_token: str
    discord_application_id: str | None
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_reply_model_fast: str | None
    llm_reply_model_thinking: str | None
    llm_reply_model_mode: str
    llm_reply_reasoning_effort: str | None
    llm_extraction_model: str | None
    llm_summary_model: str | None
    llm_backup_model: str | None
    llm_search_model: str | None
    llm_native_search_enabled: bool
    llm_native_search_tool_type: str
    llm_vision_model: str | None
    llm_audio_model: str | None
    llm_image_model: str | None
    llm_image_size: str
    llm_timeout_seconds: int
    database_path: str
    log_level: str
    log_file_path: str
    history_message_limit: int
    recent_turn_window: int
    session_memory_limit: int
    long_term_memory_limit: int
    fact_limit: int
    summary_trigger_message_count: int
    session_timeout_minutes: int
    allowed_channel_ids: set[int]
    debug_prompts: bool
    single_user_mode: bool
    single_user_id: str
    bot_timezone: str
    dashboard_enabled: bool
    dashboard_host: str
    dashboard_port: int
    dashboard_auth_enabled: bool
    dashboard_auth_username: str
    dashboard_auth_password: str
    dashboard_auth_password_generated: bool
    dashboard_session_secret: str
    dashboard_session_ttl_seconds: int
    dashboard_session_https_only: bool
    dashboard_public_bind_acknowledged: bool
    dashboard_log_max_lines: int
    dashboard_login_window_seconds: int
    dashboard_login_max_attempts: int
    dashboard_login_lockout_seconds: int
    dashboard_password_min_length: int
    mobile_api_token: str
    run_discord_bot: bool
    run_background_worker: bool
    background_poll_seconds: int
    background_task_timeout_seconds: int
    background_task_max_attempts: int
    healthcheck_interval_minutes: int
    healthcheck_deep_interval_hours: int
    enable_proactive_messages: bool
    proactive_opt_in_required: bool
    proactive_idle_hours: int
    proactive_scan_minutes: int
    proactive_response_window_hours: int
    proactive_min_idle_minutes: int
    proactive_min_interval_minutes: int
    proactive_trigger_dedupe_hours: int
    proactive_failure_backoff_minutes: int
    attachment_text_char_limit: int
    attachment_total_char_limit: int
    attachment_max_bytes: int
    attachment_image_max_bytes: int
    attachment_audio_max_bytes: int
    attachment_document_max_bytes: int
    attachment_artifact_store_text: bool
    human_presence_enabled: bool
    human_message_max_parts: int
    human_typing_min_ms: int
    human_typing_max_ms: int
    human_part_delay_min_ms: int
    human_part_delay_max_ms: int
    companion_day_engine_enabled: bool
    day_stream_min_interval_minutes: int
    day_stream_max_interval_minutes: int
    day_deep_night_quiet_enabled: bool
    day_status_cards_enabled: bool
    day_tts_enabled: bool
    day_generated_image_enabled: bool
    reality_context_enabled: bool
    weather_provider: str
    weather_location_label: str
    weather_latitude: float
    weather_longitude: float
    calendar_ics_urls: tuple[str, ...]
    calendar_lookahead_hours: int
    reality_refresh_minutes: int
    streaming_flush_chars: int
    streaming_max_silence_ms: int
    observability_retention_days: int
    observability_content_preview_chars: int
    search_timeout_seconds: int
    search_max_results: int

    def resolve_reply_model(self) -> str:
        if self.llm_reply_model_mode == "thinking":
            return self.llm_reply_model_thinking or self.llm_reply_model_fast or self.llm_model
        return self.llm_reply_model_fast or self.llm_model

    def resolve_backup_model(self) -> str | None:
        return self.llm_backup_model or self.llm_reply_model_fast or self.llm_model

    def resolve_reply_reasoning_effort(self) -> str | None:
        if self.llm_reply_model_mode != "thinking":
            return None
        return self.llm_reply_reasoning_effort or None

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()

        discord_bot_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        llm_api_key = os.getenv("LLM_API_KEY", "").strip()
        llm_model = os.getenv("LLM_MODEL", "").strip()
        run_discord_bot = _parse_bool(os.getenv("RUN_DISCORD_BOT"), True)

        required_values = {
            "LLM_API_KEY": llm_api_key,
            "LLM_MODEL": llm_model,
        }
        if run_discord_bot:
            required_values["DISCORD_BOT_TOKEN"] = discord_bot_token
        missing = [name for name, value in required_values.items() if not value]
        if missing:
            raise ConfigurationError(f"Missing required environment variables: {', '.join(missing)}")

        database_path = os.getenv("DATABASE_PATH", "data/shen_zhiwei.sqlite3")
        log_file_path = os.getenv("LOG_FILE_PATH", "logs/shen_zhiwei.log")
        reply_model_mode = (os.getenv("LLM_REPLY_MODEL_MODE", "fast") or "fast").strip().lower()
        if reply_model_mode not in {"fast", "thinking"}:
            raise ConfigurationError("LLM_REPLY_MODEL_MODE must be either 'fast' or 'thinking'")
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_file_path).parent.mkdir(parents=True, exist_ok=True)

        dashboard_enabled = _parse_bool(os.getenv("DASHBOARD_ENABLED"), True)
        dashboard_host = (os.getenv("DASHBOARD_HOST", "127.0.0.1") or "127.0.0.1").strip()
        dashboard_auth_enabled = _parse_bool(os.getenv("DASHBOARD_AUTH_ENABLED"), True)
        dashboard_auth_password = (os.getenv("DASHBOARD_AUTH_PASSWORD", "") or "").strip()
        dashboard_auth_password_generated = False
        if dashboard_enabled and dashboard_auth_enabled and not dashboard_auth_password:
            dashboard_auth_password = secrets.token_urlsafe(18)
            dashboard_auth_password_generated = True
        dashboard_session_secret = (os.getenv("DASHBOARD_SESSION_SECRET", "") or "").strip()
        if dashboard_enabled and dashboard_auth_enabled and not dashboard_session_secret:
            dashboard_session_secret = secrets.token_urlsafe(32)

        return cls(
            discord_bot_token=discord_bot_token,
            discord_application_id=os.getenv("DISCORD_APPLICATION_ID"),
            llm_api_key=llm_api_key,
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            llm_model=llm_model,
            llm_reply_model_fast=os.getenv("LLM_REPLY_MODEL_FAST") or None,
            llm_reply_model_thinking=os.getenv("LLM_REPLY_MODEL_THINKING") or None,
            llm_reply_model_mode=reply_model_mode,
            llm_reply_reasoning_effort=os.getenv("LLM_REPLY_REASONING_EFFORT") or None,
            llm_extraction_model=os.getenv("LLM_EXTRACTION_MODEL") or None,
            llm_summary_model=os.getenv("LLM_SUMMARY_MODEL") or None,
            llm_backup_model=os.getenv("LLM_BACKUP_MODEL") or None,
            llm_search_model=os.getenv("LLM_SEARCH_MODEL") or None,
            llm_native_search_enabled=_parse_bool(os.getenv("LLM_NATIVE_SEARCH_ENABLED"), True),
            llm_native_search_tool_type=os.getenv("LLM_NATIVE_SEARCH_TOOL_TYPE", "web_search_preview"),
            llm_vision_model=os.getenv("LLM_VISION_MODEL") or None,
            llm_audio_model=os.getenv("LLM_AUDIO_MODEL") or None,
            llm_image_model=os.getenv("LLM_IMAGE_MODEL") or None,
            llm_image_size=os.getenv("LLM_IMAGE_SIZE", "1024x1024"),
            llm_timeout_seconds=_parse_int(os.getenv("LLM_TIMEOUT_SECONDS"), 60),
            database_path=database_path,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file_path=log_file_path,
            history_message_limit=_parse_int(os.getenv("HISTORY_MESSAGE_LIMIT"), 20),
            recent_turn_window=_parse_int(os.getenv("RECENT_TURN_WINDOW"), 10),
            session_memory_limit=_parse_int(os.getenv("SESSION_MEMORY_LIMIT"), 6),
            long_term_memory_limit=_parse_int(os.getenv("LONG_TERM_MEMORY_LIMIT"), 8),
            fact_limit=_parse_int(os.getenv("FACT_LIMIT"), 12),
            summary_trigger_message_count=_parse_int(os.getenv("SUMMARY_TRIGGER_MESSAGE_COUNT"), 16),
            session_timeout_minutes=_parse_int(os.getenv("SESSION_TIMEOUT_MINUTES"), 180),
            allowed_channel_ids=_parse_channel_ids(os.getenv("ALLOWED_CHANNEL_IDS")),
            debug_prompts=_parse_bool(os.getenv("DEBUG_PROMPTS"), False),
            single_user_mode=_parse_bool(os.getenv("SINGLE_USER_MODE"), False),
            single_user_id=(os.getenv("SINGLE_USER_ID", "primary_user") or "primary_user").strip(),
            bot_timezone=(os.getenv("BOT_TIMEZONE", "Asia/Shanghai") or "Asia/Shanghai").strip(),
            dashboard_enabled=dashboard_enabled,
            dashboard_host=dashboard_host,
            dashboard_port=_parse_int(os.getenv("DASHBOARD_PORT"), 8099),
            dashboard_auth_enabled=dashboard_auth_enabled,
            dashboard_auth_username=(os.getenv("DASHBOARD_AUTH_USERNAME", "admin") or "admin").strip(),
            dashboard_auth_password=dashboard_auth_password,
            dashboard_auth_password_generated=dashboard_auth_password_generated,
            dashboard_session_secret=dashboard_session_secret,
            dashboard_session_ttl_seconds=_parse_int(os.getenv("DASHBOARD_SESSION_TTL_SECONDS"), 28800),
            dashboard_session_https_only=_parse_bool(
                os.getenv("DASHBOARD_SESSION_HTTPS_ONLY"),
                dashboard_host not in {"127.0.0.1", "localhost", "::1"},
            ),
            dashboard_public_bind_acknowledged=_parse_bool(os.getenv("DASHBOARD_PUBLIC_BIND_ACKNOWLEDGED"), False),
            dashboard_log_max_lines=_parse_int(os.getenv("DASHBOARD_LOG_MAX_LINES"), 400),
            dashboard_login_window_seconds=_parse_int(os.getenv("DASHBOARD_LOGIN_WINDOW_SECONDS"), 900),
            dashboard_login_max_attempts=_parse_int(os.getenv("DASHBOARD_LOGIN_MAX_ATTEMPTS"), 5),
            dashboard_login_lockout_seconds=_parse_int(os.getenv("DASHBOARD_LOGIN_LOCKOUT_SECONDS"), 1800),
            dashboard_password_min_length=_parse_int(os.getenv("DASHBOARD_PASSWORD_MIN_LENGTH"), 12),
            mobile_api_token=(os.getenv("MOBILE_API_TOKEN", "") or "").strip(),
            run_discord_bot=run_discord_bot,
            run_background_worker=_parse_bool(os.getenv("RUN_BACKGROUND_WORKER"), True),
            background_poll_seconds=_parse_int(os.getenv("BACKGROUND_POLL_SECONDS"), 2),
            background_task_timeout_seconds=_parse_int(os.getenv("BACKGROUND_TASK_TIMEOUT_SECONDS"), 180),
            background_task_max_attempts=_parse_int(os.getenv("BACKGROUND_TASK_MAX_ATTEMPTS"), 3),
            healthcheck_interval_minutes=_parse_int(os.getenv("HEALTHCHECK_INTERVAL_MINUTES"), 20),
            healthcheck_deep_interval_hours=_parse_int(os.getenv("HEALTHCHECK_DEEP_INTERVAL_HOURS"), 12),
            enable_proactive_messages=_parse_bool(os.getenv("ENABLE_PROACTIVE_MESSAGES"), True),
            proactive_opt_in_required=_parse_bool(os.getenv("PROACTIVE_OPT_IN_REQUIRED"), False),
            proactive_idle_hours=_parse_int(os.getenv("PROACTIVE_IDLE_HOURS"), 18),
            proactive_scan_minutes=_parse_int(os.getenv("PROACTIVE_SCAN_MINUTES"), 20),
            proactive_response_window_hours=_parse_int(os.getenv("PROACTIVE_RESPONSE_WINDOW_HOURS"), 8),
            proactive_min_idle_minutes=_parse_int(os.getenv("PROACTIVE_MIN_IDLE_MINUTES"), 12),
            proactive_min_interval_minutes=_parse_int(os.getenv("PROACTIVE_MIN_INTERVAL_MINUTES"), 25),
            proactive_trigger_dedupe_hours=_parse_int(os.getenv("PROACTIVE_TRIGGER_DEDUPE_HOURS"), 6),
            proactive_failure_backoff_minutes=_parse_int(os.getenv("PROACTIVE_FAILURE_BACKOFF_MINUTES"), 30),
            attachment_text_char_limit=_parse_int(os.getenv("ATTACHMENT_TEXT_CHAR_LIMIT"), 2200),
            attachment_total_char_limit=_parse_int(os.getenv("ATTACHMENT_TOTAL_CHAR_LIMIT"), 4200),
            attachment_max_bytes=_parse_int(os.getenv("ATTACHMENT_MAX_BYTES"), 25 * 1024 * 1024),
            attachment_image_max_bytes=_parse_int(os.getenv("ATTACHMENT_IMAGE_MAX_BYTES"), 8 * 1024 * 1024),
            attachment_audio_max_bytes=_parse_int(os.getenv("ATTACHMENT_AUDIO_MAX_BYTES"), 20 * 1024 * 1024),
            attachment_document_max_bytes=_parse_int(os.getenv("ATTACHMENT_DOCUMENT_MAX_BYTES"), 6 * 1024 * 1024),
            attachment_artifact_store_text=_parse_bool(os.getenv("ATTACHMENT_ARTIFACT_STORE_TEXT"), False),
            human_presence_enabled=_parse_bool(os.getenv("HUMAN_PRESENCE_ENABLED"), True),
            human_message_max_parts=_parse_int(os.getenv("HUMAN_MESSAGE_MAX_PARTS"), 3),
            human_typing_min_ms=_parse_int(os.getenv("HUMAN_TYPING_MIN_MS"), 650),
            human_typing_max_ms=_parse_int(os.getenv("HUMAN_TYPING_MAX_MS"), 3800),
            human_part_delay_min_ms=_parse_int(os.getenv("HUMAN_PART_DELAY_MIN_MS"), 450),
            human_part_delay_max_ms=_parse_int(os.getenv("HUMAN_PART_DELAY_MAX_MS"), 1800),
            companion_day_engine_enabled=_parse_bool(os.getenv("COMPANION_DAY_ENGINE_ENABLED"), True),
            day_stream_min_interval_minutes=_parse_int(os.getenv("DAY_STREAM_MIN_INTERVAL_MINUTES"), 180),
            day_stream_max_interval_minutes=_parse_int(os.getenv("DAY_STREAM_MAX_INTERVAL_MINUTES"), 240),
            day_deep_night_quiet_enabled=_parse_bool(os.getenv("DAY_DEEP_NIGHT_QUIET_ENABLED"), True),
            day_status_cards_enabled=_parse_bool(os.getenv("DAY_STATUS_CARDS_ENABLED"), False),
            day_tts_enabled=_parse_bool(os.getenv("DAY_TTS_ENABLED"), False),
            day_generated_image_enabled=_parse_bool(os.getenv("DAY_GENERATED_IMAGE_ENABLED"), False),
            reality_context_enabled=_parse_bool(os.getenv("REALITY_CONTEXT_ENABLED"), True),
            weather_provider=(os.getenv("WEATHER_PROVIDER", "open_meteo") or "open_meteo").strip().lower(),
            weather_location_label=(os.getenv("WEATHER_LOCATION_LABEL", "河北省廊坊市大城县") or "河北省廊坊市大城县").strip(),
            weather_latitude=_parse_float(os.getenv("WEATHER_LATITUDE"), 38.6995),
            weather_longitude=_parse_float(os.getenv("WEATHER_LONGITUDE"), 116.6371),
            calendar_ics_urls=_parse_csv(os.getenv("CALENDAR_ICS_URLS")),
            calendar_lookahead_hours=_parse_int(os.getenv("CALENDAR_LOOKAHEAD_HOURS"), 48),
            reality_refresh_minutes=_parse_int(os.getenv("REALITY_REFRESH_MINUTES"), 30),
            streaming_flush_chars=_parse_int(os.getenv("STREAMING_FLUSH_CHARS"), 72),
            streaming_max_silence_ms=_parse_int(os.getenv("STREAMING_MAX_SILENCE_MS"), 2200),
            observability_retention_days=_parse_int(os.getenv("OBSERVABILITY_RETENTION_DAYS"), 30),
            observability_content_preview_chars=_parse_int(os.getenv("OBSERVABILITY_CONTENT_PREVIEW_CHARS"), 220),
            search_timeout_seconds=_parse_int(os.getenv("SEARCH_TIMEOUT_SECONDS"), 8),
            search_max_results=_parse_int(os.getenv("SEARCH_MAX_RESULTS"), 5),
        )
