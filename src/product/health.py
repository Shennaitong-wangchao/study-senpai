from __future__ import annotations

import time
from typing import Any

from src.core.settings import Settings
from src.db.database import Database
from src.llm.client import LLMClient
from src.product.store import ProductStore


def _dashboard_message(enabled: bool, host: str) -> str:
    normalized = host.strip().lower()
    if not enabled:
        return "管理面板未启用。"
    if normalized in {"127.0.0.1", "localhost", "::1"}:
        return "管理面板已启用，但当前只监听本机地址，远程浏览器无法直接访问。"
    if normalized in {"0.0.0.0", "::"}:
        return "管理面板已启用，并监听全部网卡地址；请确认已配置防火墙或反向代理。"
    return "管理面板配置已启用。"


class HealthCheckService:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        llm_client: LLMClient,
        product_store: ProductStore,
    ) -> None:
        self.settings = settings
        self.database = database
        self.llm_client = llm_client
        self.product_store = product_store

    async def run_all(self, *, deep: bool = False) -> list[dict[str, Any]]:
        results = [
            self._check_database(),
            self._check_dashboard(),
            self._check_document_parser(),
            self._check_search_capability(),
            self._check_capability_config("vision", self.settings.llm_vision_model or self.settings.llm_model),
            self._check_capability_config("audio", self.settings.llm_audio_model or "whisper-1"),
            self._check_capability_config("image", self.settings.llm_image_model or "gpt-image-1"),
        ]
        results.extend(await self._check_llm_stack(deep=deep))
        for result in results:
            self.product_store.record_health_check(**result)
        return results

    async def _check_llm_stack(self, *, deep: bool) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if not deep:
            results.append(
                {
                    "component": "auth",
                    "status": "healthy" if self.settings.llm_api_key and self.settings.llm_base_url else "degraded",
                    "message": "已加载 LLM 鉴权配置；深度探测延后到低频任务或启动时执行。",
                    "latency_ms": 0.0,
                    "details": {"base_url": self.settings.llm_base_url},
                }
            )
            results.append(
                {
                    "component": "chat",
                    "status": "healthy",
                    "message": "浅巡检不再周期性调用真实聊天模型，以降低成本。",
                    "latency_ms": 0.0,
                    "details": {"model": self.settings.resolve_reply_model(), "probe": "deferred"},
                }
            )
            backup_model = self.settings.resolve_backup_model()
            results.append(
                {
                    "component": "fallback",
                    "status": "healthy" if backup_model else "degraded",
                    "message": "浅巡检仅检查备用模型配置是否存在。",
                    "latency_ms": 0.0,
                    "details": {"model": backup_model},
                }
            )
            return results

        started = time.perf_counter()
        try:
            models = await self.llm_client.list_models()
            elapsed = (time.perf_counter() - started) * 1000
            results.append(
                {
                    "component": "auth",
                    "status": "healthy",
                    "message": "模型列表可访问，鉴权正常。",
                    "latency_ms": elapsed,
                    "details": {"models": models[:10]},
                }
            )
            results.extend(self._check_configured_models_against_registry(models))
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - started) * 1000
            results.append(
                {
                    "component": "auth",
                    "status": "degraded",
                    "message": f"鉴权或模型探测失败：{type(exc).__name__}",
                    "latency_ms": elapsed,
                    "details": {"error": str(exc)},
                }
            )
            return results

        results.append(await self._ping_chat_model("chat", self.settings.resolve_reply_model()))
        backup_model = self.settings.resolve_backup_model()
        if backup_model:
            results.append(await self._ping_chat_model("fallback", backup_model))
        else:
            results.append(
                {
                    "component": "fallback",
                    "status": "degraded",
                    "message": "未配置独立备用模型，将退回主模型或启发式回复。",
                    "latency_ms": 0.0,
                    "details": {},
                }
            )
        return results

    def _check_capability_config(self, component: str, model_name: str | None) -> dict[str, Any]:
        if model_name:
            return {
                "component": component,
                "status": "healthy",
                "message": f"{component} 能力已配置模型。",
                "latency_ms": 0.0,
                "details": {"model": model_name},
            }
        return {
            "component": component,
            "status": "degraded",
            "message": f"{component} 能力未配置独立模型，将依赖默认回退。",
            "latency_ms": 0.0,
            "details": {"model": model_name},
        }

    def _check_search_capability(self) -> dict[str, Any]:
        return {
            "component": "search",
            "status": "healthy",
            "message": "外部搜索链路已启用 DuckDuckGo HTML 检索。",
            "latency_ms": 0.0,
            "details": {
                "timeout_seconds": self.settings.search_timeout_seconds,
                "max_results": self.settings.search_max_results,
            },
        }

    def _check_configured_models_against_registry(self, models: list[str]) -> list[dict[str, Any]]:
        known = set(models)
        results: list[dict[str, Any]] = []
        capability_models = {
            "vision": self.settings.llm_vision_model or self.settings.llm_model,
            "audio": self.settings.llm_audio_model or "whisper-1",
            "image": self.settings.llm_image_model or "gpt-image-1",
        }
        for component, model_name in capability_models.items():
            results.append(
                {
                    "component": f"{component}_registry",
                    "status": "healthy" if model_name in known else "degraded",
                    "message": (
                        f"{component} 模型已在模型列表中发现。"
                        if model_name in known
                        else f"{component} 模型未在模型列表中发现，请核对配置。"
                    ),
                    "latency_ms": 0.0,
                    "details": {"model": model_name},
                }
            )
        return results

    async def _ping_chat_model(self, component: str, model: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            await self.llm_client.chat_completion(
                [
                    {"role": "system", "content": "你只需要回复 pong。"},
                    {"role": "user", "content": "ping"},
                ],
                model=model,
                temperature=0.0,
                max_tokens=8,
            )
            elapsed = (time.perf_counter() - started) * 1000
            return {
                "component": component,
                "status": "healthy",
                "message": f"{component} 能力可用。",
                "latency_ms": elapsed,
                "details": {"model": model},
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - started) * 1000
            return {
                "component": component,
                "status": "degraded",
                "message": f"{component} 能力异常：{type(exc).__name__}",
                "latency_ms": elapsed,
                "details": {"model": model, "error": str(exc)},
            }

    def _check_database(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            self.database.fetchone("SELECT 1 AS ok")
            elapsed = (time.perf_counter() - started) * 1000
            return {
                "component": "database",
                "status": "healthy",
                "message": "数据库可读写。",
                "latency_ms": elapsed,
                "details": {},
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - started) * 1000
            return {
                "component": "database",
                "status": "degraded",
                "message": f"数据库异常：{type(exc).__name__}",
                "latency_ms": elapsed,
                "details": {"error": str(exc)},
            }

    def _check_dashboard(self) -> dict[str, Any]:
        return {
            "component": "dashboard",
            "status": "healthy" if self.settings.dashboard_enabled else "degraded",
            "message": _dashboard_message(self.settings.dashboard_enabled, self.settings.dashboard_host),
            "latency_ms": 0.0,
            "details": {"host": self.settings.dashboard_host, "port": self.settings.dashboard_port},
        }

    def _check_document_parser(self) -> dict[str, Any]:
        try:
            from docx import Document  # noqa: F401
            from pypdf import PdfReader  # noqa: F401

            return {
                "component": "document_parser",
                "status": "healthy",
                "message": "文档解析组件可用。",
                "latency_ms": 0.0,
                "details": {},
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "component": "document_parser",
                "status": "degraded",
                "message": f"文档解析组件异常：{type(exc).__name__}",
                "latency_ms": 0.0,
                "details": {"error": str(exc)},
            }
