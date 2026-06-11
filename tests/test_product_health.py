from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.core.settings import Settings
from src.product.health import HealthCheckService, _dashboard_message


HEALTH_ENV_KEYS = (
    "DISCORD_BOT_TOKEN",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_BACKUP_MODEL",
    "LLM_REPLY_MODEL_FAST",
    "LLM_REPLY_MODEL_THINKING",
    "LLM_REPLY_MODEL_MODE",
    "LLM_VISION_MODEL",
    "LLM_AUDIO_MODEL",
    "LLM_IMAGE_MODEL",
    "RUN_DISCORD_BOT",
    "DATABASE_PATH",
    "LOG_FILE_PATH",
    "DASHBOARD_ENABLED",
    "DASHBOARD_HOST",
    "DASHBOARD_AUTH_ENABLED",
    "SEARCH_TIMEOUT_SECONDS",
    "SEARCH_MAX_RESULTS",
)


class FakeDatabase:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.queries: list[str] = []

    def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, int]:
        self.queries.append(query)
        if self.should_fail:
            raise RuntimeError("database unavailable")
        return {"ok": 1}


class FakeLLMClient:
    def __init__(self, *, models: list[str] | None = None, list_error: Exception | None = None) -> None:
        self.models = models or []
        self.list_error = list_error
        self.list_calls = 0
        self.chat_models: list[str] = []

    async def list_models(self) -> list[str]:
        self.list_calls += 1
        if self.list_error:
            raise self.list_error
        return self.models

    async def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        self.chat_models.append(str(kwargs["model"]))
        return {"choices": [{"message": {"content": "pong"}}]}


class FakeProductStore:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_health_check(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


def load_health_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    for key in HEALTH_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    env = {
        "LLM_API_KEY": "dummy-key",
        "LLM_BASE_URL": "https://api.example.test/v1",
        "LLM_MODEL": "gpt-main",
        "RUN_DISCORD_BOT": "false",
        "DATABASE_PATH": str(tmp_path / "data" / "app.sqlite3"),
        "LOG_FILE_PATH": str(tmp_path / "logs" / "app.log"),
        "DASHBOARD_ENABLED": "true",
        "DASHBOARD_AUTH_ENABLED": "false",
        "DASHBOARD_HOST": "127.0.0.1",
        "SEARCH_TIMEOUT_SECONDS": "4",
        "SEARCH_MAX_RESULTS": "3",
    }
    env.update(overrides)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings.load()


def by_component(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["component"]): item for item in results}


def test_dashboard_message_distinguishes_local_public_and_disabled_hosts() -> None:
    assert _dashboard_message(False, "0.0.0.0") == "管理面板未启用。"
    assert "本机地址" in _dashboard_message(True, " LOCALHOST ")
    assert "全部网卡地址" in _dashboard_message(True, "::")
    assert _dashboard_message(True, "10.0.0.2") == "管理面板配置已启用。"


def test_shallow_health_check_records_results_without_llm_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_health_settings(tmp_path, monkeypatch, DASHBOARD_HOST="0.0.0.0")
    llm_client = FakeLLMClient()
    product_store = FakeProductStore()
    service = HealthCheckService(
        settings=settings,
        database=FakeDatabase(),
        llm_client=llm_client,  # type: ignore[arg-type]
        product_store=product_store,  # type: ignore[arg-type]
    )

    results = asyncio.run(service.run_all(deep=False))
    components = by_component(results)

    assert components["database"]["status"] == "healthy"
    assert components["dashboard"]["status"] == "healthy"
    assert "全部网卡地址" in components["dashboard"]["message"]
    assert components["search"]["details"] == {"timeout_seconds": 4, "max_results": 3}
    assert components["auth"]["details"] == {"base_url": "https://api.example.test/v1"}
    assert components["chat"]["details"] == {"model": "gpt-main", "probe": "deferred"}
    assert components["fallback"]["details"] == {"model": "gpt-main"}
    assert llm_client.list_calls == 0
    assert llm_client.chat_models == []
    assert product_store.records == results


def test_deep_health_check_validates_registry_and_pings_chat_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_health_settings(
        tmp_path,
        monkeypatch,
        LLM_BACKUP_MODEL="gpt-backup",
        LLM_VISION_MODEL="gpt-vision",
    )
    llm_client = FakeLLMClient(models=["gpt-main", "gpt-backup", "gpt-vision", "whisper-1", "gpt-image-1"])
    product_store = FakeProductStore()
    service = HealthCheckService(
        settings=settings,
        database=FakeDatabase(),
        llm_client=llm_client,  # type: ignore[arg-type]
        product_store=product_store,  # type: ignore[arg-type]
    )

    results = asyncio.run(service.run_all(deep=True))
    components = by_component(results)

    assert components["auth"]["status"] == "healthy"
    assert components["vision_registry"]["status"] == "healthy"
    assert components["audio_registry"]["status"] == "healthy"
    assert components["image_registry"]["status"] == "healthy"
    assert components["chat"]["status"] == "healthy"
    assert components["fallback"]["status"] == "healthy"
    assert llm_client.chat_models == ["gpt-main", "gpt-backup"]
    assert product_store.records == results


def test_deep_health_check_degrades_when_model_registry_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_health_settings(tmp_path, monkeypatch)
    llm_client = FakeLLMClient(list_error=RuntimeError("registry offline"))
    service = HealthCheckService(
        settings=settings,
        database=FakeDatabase(),
        llm_client=llm_client,  # type: ignore[arg-type]
        product_store=FakeProductStore(),  # type: ignore[arg-type]
    )

    results = asyncio.run(service.run_all(deep=True))
    components = by_component(results)

    assert components["auth"]["status"] == "degraded"
    assert components["auth"]["message"] == "鉴权或模型探测失败：RuntimeError"
    assert components["auth"]["details"] == {"error": "registry offline"}
    assert "chat" not in components
    assert llm_client.chat_models == []
