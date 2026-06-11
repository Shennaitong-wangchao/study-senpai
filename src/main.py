from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import uvicorn

from src.bot.discord_client import ShenZhiweiDiscordClient
from src.bot.commands import CommandRouter
from src.bot.handlers import DiscordMessageHandler
from src.bot.message_router import MessageRouter
from src.core.exceptions import ConfigurationError
from src.core.logger import configure_logging
from src.core.settings import Settings
from src.core.types import ConversationScope
from src.dashboard.server import build_dashboard_app
from src.db.database import Database
from src.llm.client import LLMClient
from src.llm.prompt_builder import PromptBuilder
from src.memory.extraction import MemoryExtractor
from src.memory.pipeline import MemoryPipeline
from src.memory.relationship import RelationshipManager
from src.memory.retrieval import MemoryRetriever
from src.memory.session_state import SessionStateManager
from src.memory.store import MemoryStore
from src.memory.summarizer import ConversationSummarizer
from src.memory.writer import MemoryWriter
from src.persona.profile import SHEN_ZHIWEI_PROFILE
from src.persona.registry import PersonaLoadError, load_default_persona, load_persona
from src.product.attachments import AttachmentService
from src.product.health import HealthCheckService
from src.product.metrics import ExperienceMetricsService
from src.product.planner import ReplyPlanner
from src.product.proactive import ProactiveMessageService
from src.product.search import SearchService
from src.product.store import ProductStore
from src.product.tasks import BackgroundTaskManager
from src.services.memory_service import MemoryService
from src.services.companion_service import CompanionService
from src.services.reply_service import ReplyService


logger = logging.getLogger(__name__)


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def _is_public_bind_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"0.0.0.0", "::"}


def _write_dashboard_bootstrap_password_file(settings: Settings) -> str:
    output_path = Path(settings.database_path).resolve().parent / "dashboard_bootstrap_password.txt"
    output_path.write_text(
        (
            "Shen Zhiwei Dashboard bootstrap credentials\n"
            f"username={settings.dashboard_auth_username}\n"
            f"password={settings.dashboard_auth_password}\n"
            "Change this password from the dashboard security panel after first login.\n"
        ),
        encoding="utf-8",
    )
    try:
        output_path.chmod(0o600)
    except OSError:
        logger.warning("Failed to tighten permissions for dashboard bootstrap password file: %s", output_path)
    return str(output_path)


async def run() -> None:
    settings = Settings.load()
    configure_logging(settings.log_level, settings.log_file_path)

    logger.info("Initializing Shen Zhiwei bot")
    if settings.single_user_mode:
        logger.warning(
            "SINGLE_USER_MODE=true is enabled. This will merge all conversations into the shared user slot %s.",
            settings.single_user_id,
        )
    if not settings.run_discord_bot and not settings.run_background_worker and not settings.dashboard_enabled:
        raise ConfigurationError(
            "Nothing to run: enable at least one of RUN_DISCORD_BOT, RUN_BACKGROUND_WORKER, or DASHBOARD_ENABLED"
        )

    # 加载人格配置：优先读取环境变量 PERSONA_FILE 指定的 YAML 文件，
    # 其次尝试加载默认的 personas/shen_zhiwei.yaml，
    # 最后回退到 Python 内联定义（保证兼容性）
    persona_file_env = os.environ.get("PERSONA_FILE", "").strip()
    if persona_file_env:
        try:
            active_persona = load_persona(persona_file_env)
            logger.info("已从环境变量 PERSONA_FILE 加载人格：%s（文件：%s）", active_persona.name, persona_file_env)
        except PersonaLoadError as exc:
            logger.warning("无法从 PERSONA_FILE='%s' 加载人格，回退到 Python 内联定义。原因：%s", persona_file_env, exc)
            active_persona = SHEN_ZHIWEI_PROFILE
    else:
        try:
            active_persona = load_default_persona()
            logger.info("已加载默认 YAML 人格：%s", active_persona.name)
        except PersonaLoadError as exc:
            logger.warning("无法加载默认 YAML 人格，回退到 Python 内联定义。原因：%s", exc)
            active_persona = SHEN_ZHIWEI_PROFILE

    database = Database(settings.database_path)
    database.initialize()

    llm_client = LLMClient(settings)
    store = MemoryStore(database)
    product_store = ProductStore(database)
    relationship_manager = RelationshipManager()
    session_manager = SessionStateManager(
        store,
        settings.session_timeout_minutes,
        single_user_mode=settings.single_user_mode,
        single_user_id=settings.single_user_id,
    )
    extractor = MemoryExtractor(llm_client)
    writer = MemoryWriter(store, settings, relationship_manager, product_store=product_store)
    retriever = MemoryRetriever(store, settings)
    summarizer = ConversationSummarizer(store, llm_client, settings)
    pipeline = MemoryPipeline(
        store=store,
        session_manager=session_manager,
        extractor=extractor,
        writer=writer,
        retriever=retriever,
        summarizer=summarizer,
        summary_trigger_message_count=settings.summary_trigger_message_count,
    )
    memory_service = MemoryService(pipeline)
    prompt_builder = PromptBuilder(active_persona)
    reply_service = ReplyService(
        settings=settings,
        memory_service=memory_service,
        llm_client=llm_client,
        prompt_builder=prompt_builder,
    )
    attachment_service = AttachmentService(settings=settings, llm_client=llm_client, product_store=product_store)
    search_service = SearchService(settings)
    metrics_service = ExperienceMetricsService()
    planner = ReplyPlanner()
    task_manager = BackgroundTaskManager(settings=settings, product_store=product_store)
    health_service = HealthCheckService(
        settings=settings,
        database=database,
        llm_client=llm_client,
        product_store=product_store,
    )
    proactive_service = ProactiveMessageService(
        settings=settings,
        memory_store=store,
        product_store=product_store,
        llm_client=llm_client,
    )
    if settings.dashboard_enabled and settings.dashboard_auth_enabled and settings.dashboard_auth_password_generated:
        if product_store.get_dashboard_password_hash() is None:
            product_store.set_dashboard_password_change_required(True)
            bootstrap_path = _write_dashboard_bootstrap_password_file(settings)
            logger.warning(
                "Dashboard auth password was auto-generated for this process. Bootstrap credentials were written to %s",
                bootstrap_path,
            )
    companion_service = CompanionService(
        settings=settings,
        memory_service=memory_service,
        memory_store=store,
        reply_service=reply_service,
        product_store=product_store,
        attachment_service=attachment_service,
        search_service=search_service,
        metrics_service=metrics_service,
        planner=planner,
        task_manager=task_manager,
    )
    router = MessageRouter(settings)
    command_router = CommandRouter(db=database) if settings.run_discord_bot else None
    handler = DiscordMessageHandler(
        router=router,
        companion_service=companion_service,
        command_router=command_router,
    )
    client = ShenZhiweiDiscordClient(handler=handler) if settings.run_discord_bot else None
    dashboard_server: uvicorn.Server | None = None
    dashboard_task: asyncio.Task | None = None
    worker_started = False

    async def handle_turn_postprocess(payload: dict) -> dict:
        scope_data = payload["scope"]
        scope = ConversationScope(
            platform=scope_data["platform"],
            conversation_id=scope_data["conversation_id"],
            user_id=scope_data["user_id"],
            channel_id=scope_data["channel_id"],
            guild_id=scope_data.get("guild_id"),
            session_id=scope_data["session_id"],
        )
        user_message = store.get_message_by_id(int(payload["user_message_id"]))
        assistant_message = store.get_message_by_id(int(payload["assistant_message_id"]))
        if user_message is None or assistant_message is None:
            raise RuntimeError("turn messages missing for postprocess")
        analysis = await memory_service.process_completed_turn(
            scope,
            turn_messages=[user_message, assistant_message],
        )
        return {
            "request_id": payload.get("request_id"),
            "turn_uid": payload.get("turn_uid"),
            "extraction_method": analysis.extraction_method,
            "session_memories": len(analysis.session_memories),
            "long_term_memories": len(analysis.long_term_memories),
            "structured_facts": len(analysis.structured_facts),
            "relationship_updates": len(analysis.relationship_updates),
            "summary_hint": analysis.summary_hint,
        }

    async def handle_health_check(payload: dict) -> dict:
        deep = bool(payload.get("deep"))
        results = await health_service.run_all(deep=deep)
        return {"count": len(results), "deep": deep}

    async def handle_proactive_scan(_: dict) -> dict:
        if client is None:
            return {"sent": 0, "skipped": True, "reason": "discord bot disabled"}
        return await proactive_service.scan_and_send(client)

    task_manager.register_handler("turn_postprocess", handle_turn_postprocess)
    task_manager.register_handler("health_check", handle_health_check)
    task_manager.register_handler("proactive_scan", handle_proactive_scan)

    async def handle_observability_cleanup(_: dict) -> dict:
        return product_store.purge_old_observability(
            retention_days=settings.observability_retention_days,
        )

    task_manager.register_handler("observability_cleanup", handle_observability_cleanup)

    try:
        if settings.run_background_worker:
            await task_manager.start()
            worker_started = True
            task_manager.schedule_periodic(
                task_type="health_check",
                payload_factory=lambda: {"deep": False},
                dedupe_key="health-check-shallow",
                interval_seconds=settings.healthcheck_interval_minutes * 60,
                priority=0.7,
            )
            task_manager.schedule_periodic(
                task_type="health_check",
                payload_factory=lambda: {"deep": True},
                dedupe_key="health-check-deep",
                interval_seconds=settings.healthcheck_deep_interval_hours * 60 * 60,
                priority=0.35,
            )
            if settings.run_discord_bot:
                task_manager.schedule_periodic(
                    task_type="proactive_scan",
                    payload_factory=lambda: {},
                    dedupe_key="proactive-scan",
                    interval_seconds=max(settings.proactive_scan_minutes, 1) * 60,
                    priority=0.45,
                )
            task_manager.schedule_periodic(
                task_type="observability_cleanup",
                payload_factory=lambda: {},
                dedupe_key="observability-cleanup",
                interval_seconds=24 * 60 * 60,
                priority=0.2,
            )
        else:
            logger.warning(
                "RUN_BACKGROUND_WORKER=false: background tasks will queue in SQLite until a worker process is started."
            )
        purged = product_store.purge_old_observability(
            retention_days=settings.observability_retention_days,
        )
        if purged:
            logger.info("Observability retention cleanup: %s", purged)
        await health_service.run_all(deep=True)

        if settings.dashboard_enabled:
            logger.info(
                "Dashboard enabled on http://%s:%s",
                settings.dashboard_host,
                settings.dashboard_port,
            )
            if settings.dashboard_auth_enabled:
                logger.info("Dashboard auth enabled for user %s", settings.dashboard_auth_username)
            if settings.mobile_api_token:
                logger.info("Mobile API bearer token auth is enabled.")
            else:
                logger.warning(
                    "MOBILE_API_TOKEN is not set. /mobile/* will accept localhost/dev requests only; "
                    "set MOBILE_API_TOKEN before exposing the mobile API."
                )
            if _is_loopback_host(settings.dashboard_host):
                logger.warning(
                    "Dashboard is bound to %s, so it is only reachable from the server itself. "
                    "Use SSH tunneling or set DASHBOARD_HOST=0.0.0.0 for remote access.",
                    settings.dashboard_host,
                )
            elif _is_public_bind_host(settings.dashboard_host):
                if not settings.dashboard_auth_enabled:
                    raise ConfigurationError(
                        "Dashboard public bind requires DASHBOARD_AUTH_ENABLED=true"
                    )
                if not settings.dashboard_public_bind_acknowledged:
                    raise ConfigurationError(
                        "Dashboard public bind requires DASHBOARD_PUBLIC_BIND_ACKNOWLEDGED=true"
                    )
                logger.warning(
                    "Dashboard is bound to %s. Keep auth enabled and still protect it with a firewall, "
                    "reverse proxy, or private network before exposing it.",
                    settings.dashboard_host,
                )
            if settings.dashboard_session_https_only:
                logger.info("Dashboard session cookies are configured as Secure-only.")
            elif not _is_loopback_host(settings.dashboard_host):
                logger.warning(
                    "Dashboard session cookies are not Secure-only while host=%s is not loopback. "
                    "Prefer TLS termination and DASHBOARD_SESSION_HTTPS_ONLY=true.",
                    settings.dashboard_host,
                )
            dashboard_app = build_dashboard_app(
                settings=settings,
                product_store=product_store,
                memory_store=store,
                llm_client=llm_client,
                companion_service=companion_service,
                attachment_service=attachment_service,
            )
            dashboard_server = uvicorn.Server(
                uvicorn.Config(
                    dashboard_app,
                    host=settings.dashboard_host,
                    port=settings.dashboard_port,
                    log_level=settings.log_level.lower(),
                )
            )
            dashboard_task = asyncio.create_task(dashboard_server.serve(), name="dashboard-server")
        if settings.run_discord_bot and client is not None:
            await client.start(settings.discord_bot_token)
        elif dashboard_task is not None:
            await dashboard_task
        elif worker_started:
            logger.info("Worker-only mode is active. Waiting for background tasks and signals.")
            await asyncio.Event().wait()
    finally:
        if dashboard_server is not None:
            dashboard_server.should_exit = True
        if dashboard_task is not None:
            await asyncio.wait([dashboard_task], timeout=5)
        if worker_started:
            await task_manager.stop()
        await search_service.aclose()
        await llm_client.aclose()
        database.close()


if __name__ == "__main__":
    asyncio.run(run())
