from __future__ import annotations

import os

import pytest

from src.core.exceptions import ConfigurationError
from src.core.settings import Settings


SETTING_KEYS = (
    "DISCORD_BOT_TOKEN",
    "LLM_API_KEY",
    "LLM_MODEL",
    "RUN_DISCORD_BOT",
    "DATABASE_PATH",
    "LOG_FILE_PATH",
    "LLM_REPLY_MODEL_MODE",
    "DASHBOARD_ENABLED",
    "DASHBOARD_HOST",
    "DASHBOARD_AUTH_ENABLED",
    "DASHBOARD_AUTH_PASSWORD",
    "DASHBOARD_SESSION_SECRET",
    "LLM_REPLY_MODEL_FAST",
    "LLM_REPLY_MODEL_THINKING",
    "LLM_REPLY_REASONING_EFFORT",
    "CALENDAR_ICS_URLS",
    "ALLOWED_CHANNEL_IDS",
)


def clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_load_generates_dashboard_credentials_for_local_auth(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("RUN_DISCORD_BOT", "false")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "data" / "app.sqlite3"))
    monkeypatch.setenv("LOG_FILE_PATH", str(tmp_path / "logs" / "app.log"))
    monkeypatch.setenv("DASHBOARD_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_AUTH_PASSWORD", "")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "")
    monkeypatch.setenv("ALLOWED_CHANNEL_IDS", "1, 2,3")
    monkeypatch.setenv("CALENDAR_ICS_URLS", "https://calendar.example/a.ics, https://calendar.example/b.ics")

    settings = Settings.load()

    assert settings.run_discord_bot is False
    assert settings.dashboard_auth_password_generated is True
    assert settings.dashboard_auth_password
    assert settings.dashboard_session_secret
    assert settings.dashboard_session_https_only is False
    assert settings.allowed_channel_ids == {1, 2, 3}
    assert settings.calendar_ics_urls == ("https://calendar.example/a.ics", "https://calendar.example/b.ics")
    assert os.path.isdir(tmp_path / "data")
    assert os.path.isdir(tmp_path / "logs")


def test_settings_load_requires_discord_token_when_discord_is_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("RUN_DISCORD_BOT", "true")

    with pytest.raises(ConfigurationError, match="DISCORD_BOT_TOKEN"):
        Settings.load()


def test_settings_load_rejects_invalid_reply_model_mode(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("RUN_DISCORD_BOT", "false")
    monkeypatch.setenv("LLM_REPLY_MODEL_MODE", "slow")

    with pytest.raises(ConfigurationError, match="LLM_REPLY_MODEL_MODE"):
        Settings.load()


def test_settings_model_resolution_prefers_mode_specific_models(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("RUN_DISCORD_BOT", "false")
    monkeypatch.setenv("LLM_REPLY_MODEL_MODE", "thinking")
    monkeypatch.setenv("LLM_REPLY_MODEL_FAST", "gpt-fast")
    monkeypatch.setenv("LLM_REPLY_MODEL_THINKING", "gpt-thinking")
    monkeypatch.setenv("LLM_REPLY_REASONING_EFFORT", "medium")

    settings = Settings.load()

    assert settings.resolve_reply_model() == "gpt-thinking"
    assert settings.resolve_backup_model() == "gpt-fast"
    assert settings.resolve_reply_reasoning_effort() == "medium"
