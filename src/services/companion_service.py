from __future__ import annotations

import logging
import asyncio
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import discord

from src.core.settings import Settings
from src.core.types import ConversationScope, MessageContext
from src.memory.store import MemoryStore
from src.product.attachments import AttachmentService
from src.product.day_engine import CompanionDayEngine
from src.product.human_delivery import send_human_message_parts
from src.product.metrics import ExperienceMetricsService
from src.product.models import AttachmentInsight, ModeState, ReplyPlan, SearchDigest
from src.product.presence import PresenceStateService
from src.product.planner import ReplyPlanner
from src.product.proactive import (
    get_proactive_preferences,
    normalize_proactive_cadence,
    proactive_backoff_key,
    proactive_cadence_policy,
    set_proactive_preferences,
)
from src.product.reality import RealityContextService
from src.product.search import SearchService
from src.product.store import ProductStore
from src.product.streaming import ProgressiveReleaseState, split_markdown_chunks
from src.product.tasks import BackgroundTaskManager
from src.services.memory_service import MemoryService
from src.services.reply_service import PreparedReply, ReplyGenerationResult, ReplyService
from src.utils.text_utils import compact_text, truncate_text
from src.utils.time_utils import build_current_time_context, parse_iso8601


logger = logging.getLogger(__name__)


class DiscordReplyPublisher:
    def __init__(self, *, source_message: discord.Message, settings: Settings, limit: int = 1800) -> None:
        self.source_message = source_message
        self.settings = settings
        self.limit = limit
        self.sent_messages: list[discord.Message] = []
        self.last_text = ""
        self.last_chunks: list[str] = []

    async def publish(self, text: str) -> list[discord.Message]:
        if text == self.last_text:
            return self.sent_messages
        chunks = split_markdown_chunks(text, limit=self.limit)
        if not chunks:
            chunks = ["..."]

        for index, chunk in enumerate(chunks):
            if index < len(self.sent_messages):
                if index < len(self.last_chunks) and self.last_chunks[index] == chunk:
                    continue
                await self.sent_messages[index].edit(content=chunk)
                continue
            chunk = chunks[index]
            sent = await self.source_message.channel.send(
                chunk,
                reference=self.source_message if index == 0 else None,
                mention_author=False,
            )
            self.sent_messages.append(sent)

        while len(self.sent_messages) > len(chunks):
            message_to_remove = self.sent_messages.pop()
            await message_to_remove.delete()

        self.last_chunks = chunks
        self.last_text = text
        return self.sent_messages

    async def publish_human(self, text: str) -> list[discord.Message]:
        self.sent_messages = await send_human_message_parts(
            self.source_message.channel,
            text,
            settings=self.settings,
            reference=self.source_message,
            mention_author=False,
            limit=self.limit,
        )
        self.last_text = text
        self.last_chunks = [message.content for message in self.sent_messages]
        return self.sent_messages


class CompanionService:
    MODEL_COST_HINTS: dict[str, tuple[float, float]] = {
        "gpt-4.1-mini": (0.0004, 0.0016),
        "gpt-4.1": (0.0020, 0.0080),
        "gpt-4o-mini": (0.00015, 0.0006),
        "gpt-4o": (0.0025, 0.0100),
        "heuristic-fallback": (0.0, 0.0),
    }

    def __init__(
        self,
        *,
        settings: Settings,
        memory_service: MemoryService,
        memory_store: MemoryStore,
        reply_service: ReplyService,
        product_store: ProductStore,
        attachment_service: AttachmentService,
        search_service: SearchService,
        metrics_service: ExperienceMetricsService,
        planner: ReplyPlanner,
        task_manager: BackgroundTaskManager,
    ) -> None:
        self.settings = settings
        self.memory_service = memory_service
        self.memory_store = memory_store
        self.reply_service = reply_service
        self.product_store = product_store
        self.attachment_service = attachment_service
        self.search_service = search_service
        self.metrics_service = metrics_service
        self.planner = planner
        self.task_manager = task_manager
        self.presence_state = PresenceStateService(
            settings=settings,
            product_store=product_store,
            memory_store=memory_store,
            llm_client=reply_service.llm_client,
        )
        self.reality_context = RealityContextService(
            settings=settings,
            product_store=product_store,
        )
        self.day_engine = CompanionDayEngine(
            settings=settings,
            product_store=product_store,
            memory_store=memory_store,
            llm_client=reply_service.llm_client,
            reality_context=self.reality_context,
        )

    async def handle_message(
        self,
        client: discord.Client,
        message: discord.Message,
        *,
        user_content: str | None = None,
    ) -> None:
        human_user_id = str(message.author.id)
        channel_id = str(message.channel.id)
        guild_id = str(message.guild.id) if message.guild else None
        scope = self.memory_service.build_scope(
            platform="discord",
            user_id=human_user_id,
            channel_id=channel_id,
            guild_id=guild_id,
        )

        command_text = (user_content if user_content is not None else message.content.strip()).strip()
        if await self._maybe_handle_command(message, scope, command_text):
            return

        if not command_text and message.attachments:
            command_text = "我发了一个附件给你。"
        user_content = command_text
        user_context = MessageContext(
            platform_message_id=str(message.id),
            author_id=str(message.author.id),
            reply_to_platform_message_id=str(message.reference.message_id) if message.reference else None,
            thread_id=str(message.channel.id) if isinstance(message.channel, discord.Thread) else None,
        )
        existing_user_message = self.memory_store.get_message_by_platform_id(scope.platform, str(message.id))
        if existing_user_message is not None and existing_user_message.sender_type == "user":
            logger.info(
                "Duplicate user message ignored | platform_message_id=%s conversation=%s",
                message.id,
                scope.conversation_id,
            )
            return
        user_metadata = {
            "display_name": message.author.display_name,
            "attachments": [
                {
                    "filename": attachment.filename,
                    "content_type": attachment.content_type,
                    "size": attachment.size,
                    "url": attachment.url,
                }
                for attachment in message.attachments
            ],
            "channel_name": getattr(message.channel, "name", None),
            "guild_name": message.guild.name if message.guild else None,
        }

        request_id = f"req_{uuid.uuid4().hex}"
        turn_uid = f"turn_{uuid.uuid4().hex}"
        started = time.perf_counter()
        logger.info("Reply request %s started | conversation=%s", request_id, scope.conversation_id)

        attachment_started = time.perf_counter()
        attachment_insights = await self.attachment_service.analyze_attachments(
            attachments=list(message.attachments),
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            platform_message_id=str(message.id),
        )
        attachment_latency_ms = (time.perf_counter() - attachment_started) * 1000

        retrieval_started = time.perf_counter()
        user_message = self.memory_service.ingest_message(
            scope,
            sender_type="user",
            content=user_content,
            context=user_context,
            metadata=user_metadata,
        )
        await self.presence_state.update_from_user_message(scope, user_content, message_id=user_message.id)
        memory_context = self.memory_service.retrieve_for_reply(
            scope,
            current_user_input=user_content,
            before_message_id=user_message.id,
        )
        retrieval_latency_ms = (time.perf_counter() - retrieval_started) * 1000

        planning_started = time.perf_counter()
        mode_state = self.product_store.get_mode_state(scope.user_id, scope.conversation_id)
        reply_plan = self.planner.plan(
            user_input=user_content,
            memory_context=memory_context,
            mode_state=mode_state,
            attachment_count=len(attachment_insights),
        )
        planning_latency_ms = (time.perf_counter() - planning_started) * 1000
        logger.info(
            "Reply request %s planned | type=%s scene=%s search=%s draw=%s",
            request_id,
            reply_plan.request_type,
            reply_plan.scene,
            reply_plan.should_search,
            reply_plan.should_draw,
        )

        search_digest = None
        search_latency_ms = 0.0
        if reply_plan.should_search:
            search_started = time.perf_counter()
            search_digest = await self.search_service.search(user_content)
            search_latency_ms = (time.perf_counter() - search_started) * 1000
            logger.info(
                "Reply request %s search note | %s",
                request_id,
                search_digest.note or "no-note",
            )

        if self.settings.reality_context_enabled:
            await self.reality_context.refresh_if_stale(scope)

        extra_context_blocks = self._build_extra_context_blocks(
            scope,
            attachment_insights,
            search_digest,
            user_text=user_content,
            memory_context=memory_context,
        )
        prompt_started = time.perf_counter()
        prepared = self.reply_service.build_prepared_reply(
            scope=scope,
            user_content=user_content,
            user_message=user_message,
            memory_context=memory_context,
            mode_state=mode_state,
            reply_plan=reply_plan,
            extra_context_blocks=extra_context_blocks,
        )
        prompt_latency_ms = (time.perf_counter() - prompt_started) * 1000

        generation_started = time.perf_counter()
        if reply_plan.should_draw:
            generation = await self._handle_draw_request(
                message,
                prepared,
                attachment_insights,
                request_id=request_id,
                turn_uid=turn_uid,
            )
            assistant_messages = generation["messages"]
            assistant_text = generation["assistant_text"]
            generated_file = generation.get("image_path")
            generation_result = generation["reply_generation"]
        else:
            generation_result, assistant_messages = await self._stream_text_reply(message, prepared)
            assistant_text = generation_result.text
            generated_file = None
        generation_latency_ms = (time.perf_counter() - generation_started) * 1000
        presence_lint = getattr(generation_result, "presence_lint", {})

        finalize_started = time.perf_counter()
        assistant_context = MessageContext(
            platform_message_id=str(assistant_messages[0].id),
            author_id=str(client.user.id if client.user else "assistant"),
            reply_to_platform_message_id=str(message.id),
            thread_id=str(message.channel.id) if isinstance(message.channel, discord.Thread) else None,
        )
        assistant_metadata: dict[str, Any] = {
            "sent_message_ids": [str(sent.id) for sent in assistant_messages],
            "mode": mode_state.mode,
            "learning_mode": mode_state.learning_mode,
            "request_type": reply_plan.request_type,
            "scene": reply_plan.scene,
            "reply_goal": reply_plan.reply_goal,
            "model_name": generation_result.model_name,
            "backup_model_name": generation_result.backup_model_name,
            "fallback_used": generation_result.fallback_used,
            "search_used": bool(search_digest),
            "generated_image_path": generated_file,
            "request_id": request_id,
            "turn_uid": turn_uid,
            "presence_lint": presence_lint,
        }
        assistant_message = await self.reply_service.finalize_reply(
            prepared,
            assistant_content=assistant_text,
            assistant_context=assistant_context,
            assistant_metadata=assistant_metadata,
        )

        prompt_used = generation_result.prompt_used
        if prompt_used and prompt_used.usage.long_term_memory_uids:
            self.product_store.record_memory_hits(
                scope.user_id,
                prompt_used.usage.long_term_memory_uids,
                context_type="reply",
            )
            self.memory_store.touch_long_term_memories(prompt_used.usage.long_term_memory_uids)

        self._mark_proactive_response(scope, user_message.id)
        open_loop_ledger = self.presence_state.update_after_turn(
            scope,
            user_text=user_content,
            assistant_text=assistant_text,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
        )
        companion_day_update = self.day_engine.record_user_turn(
            scope,
            user_text=user_content,
            assistant_text=assistant_text,
            user_message_id=user_message.id,
            attachment_insights=attachment_insights,
        )
        finalize_latency_ms = (time.perf_counter() - finalize_started) * 1000
        latency_ms = (time.perf_counter() - started) * 1000
        stage_latency_ms = {
            "attachments": round(attachment_latency_ms, 2),
            "retrieval": round(retrieval_latency_ms, 2),
            "planning": round(planning_latency_ms, 2),
            "search": round(search_latency_ms, 2),
            "prompt_build": round(prompt_latency_ms, 2),
            "generation": round(generation_latency_ms, 2),
            "finalize": round(finalize_latency_ms, 2),
            "total": round(latency_ms, 2),
        }
        prompt_char_count = prompt_used.usage.prompt_char_count if prompt_used else 0
        estimated_input_tokens = prompt_used.usage.estimated_input_tokens if prompt_used else 0
        estimated_output_tokens = self._estimate_tokens(assistant_text)
        estimated_total_tokens = estimated_input_tokens + estimated_output_tokens
        estimated_cost_usd = self._estimate_model_cost_usd(
            generation_result.model_name,
            input_tokens=estimated_input_tokens,
            output_tokens=estimated_output_tokens,
        )
        metrics = self.metrics_service.evaluate(
            reply_text=assistant_text,
            memory_context=memory_context,
            plan=reply_plan,
            search_used=bool(search_digest),
            proactive_acceptance=self._recent_proactive_acceptance_rate(),
            proactive_cold_response_rate=self._recent_proactive_cold_rate(),
        )
        observability_metrics = {
            **metrics,
            "request_id": request_id,
            "turn_uid": turn_uid,
            "prompt_char_count": prompt_char_count,
            "estimated_input_tokens": estimated_input_tokens,
            "estimated_output_tokens": estimated_output_tokens,
            "estimated_total_tokens": estimated_total_tokens,
            "estimated_cost_usd": round(estimated_cost_usd, 6),
            "attachment_count": len(attachment_insights),
            "search_count": 0 if search_digest is None else len(search_digest.items),
            "search_note": None if search_digest is None else search_digest.note,
            "stage_latency_ms": stage_latency_ms,
        }
        self.product_store.record_experience_metrics(
            turn_uid,
            persona_consistency=float(metrics["persona_consistency"]),
            memory_hit_quality=float(metrics["memory_hit_quality"]),
            memory_usage_rate=float(metrics["memory_usage_rate"]),
            proactive_acceptance=float(metrics["proactive_acceptance"]),
            repeated_comfort_rate=float(metrics["repeated_comfort_rate"]),
            over_explaining_rate=float(metrics["over_explaining_rate"]),
            tool_trace_leakage_rate=float(metrics["tool_trace_leakage_rate"]),
            proactive_cold_response_rate=float(metrics["proactive_cold_response_rate"]),
            structure_type=str(metrics["structure_type"]),
            metadata={
                "scene": reply_plan.scene,
                "request_type": reply_plan.request_type,
                "request_id": request_id,
                "estimated_cost_usd": round(estimated_cost_usd, 6),
                "presence_lint": presence_lint,
                "open_loop_count": len(open_loop_ledger.get("open_loops", [])),
                "companion_day": companion_day_update,
            },
        )
        self.product_store.record_turn_trace(
            turn_uid=turn_uid,
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            session_id=scope.session_id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            request_type=reply_plan.request_type,
            reply_goal=reply_plan.reply_goal,
            scene=reply_plan.scene,
            mode_text=reply_plan.mode_text,
            model_name=generation_result.model_name,
            backup_model_name=generation_result.backup_model_name,
            fallback_used=generation_result.fallback_used,
            latency_ms=latency_ms,
            user_input=self._observability_preview(user_content),
            assistant_reply=self._observability_preview(assistant_text),
            attachments=[self._sanitize_attachment_insight(item) for item in attachment_insights],
            search_context=[] if search_digest is None else [self._sanitize_search_context(search_digest)],
            planning={
                **asdict(reply_plan),
                "request_id": request_id,
                "turn_uid": turn_uid,
                "search_note": None if search_digest is None else search_digest.note,
            },
            retrieval=self._build_retrieval_snapshot(
                memory_context,
                prompt_usage=None if prompt_used is None else prompt_used.usage,
                request_id=request_id,
            ),
            metrics=observability_metrics,
        )
        self.product_store.create_memory_snapshot(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            session_id=scope.session_id,
            turn_uid=turn_uid,
            snapshot=self._build_memory_snapshot(
                memory_context,
                prompt_usage=None if prompt_used is None else prompt_used.usage,
                request_id=request_id,
            ),
        )
        self.task_manager.enqueue(
            task_type="turn_postprocess",
            payload={
                "request_id": request_id,
                "scope": {
                    "platform": scope.platform,
                    "conversation_id": scope.conversation_id,
                    "user_id": scope.user_id,
                    "channel_id": scope.channel_id,
                    "guild_id": scope.guild_id,
                    "session_id": scope.session_id,
                },
                "user_message_id": user_message.id,
                "assistant_message_id": assistant_message.id,
                "turn_uid": turn_uid,
            },
            dedupe_key=f"turn:{assistant_message.id}",
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            session_id=scope.session_id,
            priority=0.9,
        )
        logger.info(
            "Reply request %s completed | turn=%s model=%s cost=%.6f latency_ms=%.2f",
            request_id,
            turn_uid,
            generation_result.model_name,
            estimated_cost_usd,
            latency_ms,
        )

    async def stream_mobile_reply(
        self,
        *,
        scope: ConversationScope,
        user_content: str,
        platform_message_id: str | None = None,
        author_id: str = "mobile-user",
        display_name: str = "Lover",
        attachment_insights: list[AttachmentInsight] | None = None,
        tool_overrides: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        async def produce() -> None:
            try:
                await self._produce_mobile_reply(
                    scope=scope,
                    user_content=user_content,
                    platform_message_id=platform_message_id,
                    author_id=author_id,
                    display_name=display_name,
                    attachment_insights=list(attachment_insights or []),
                    tool_overrides=tool_overrides or {},
                    metadata=metadata or {},
                    emit=emit,
                )
            except Exception as exc:  # noqa: BLE001
                self.product_store.record_error(
                    component="mobile_chat",
                    message=f"Mobile reply failed: {type(exc).__name__}",
                    details={"error": str(exc), "conversation_id": scope.conversation_id},
                )
                await emit(
                    {
                        "event": "error",
                        "message": "这次手机端回复没有顺利接上，我已经把错误记下来了。",
                        "error_type": type(exc).__name__,
                    }
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(produce())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
            await task
        finally:
            if not task.done():
                task.cancel()

    async def _produce_mobile_reply(
        self,
        *,
        scope: ConversationScope,
        user_content: str,
        platform_message_id: str | None,
        author_id: str,
        display_name: str,
        attachment_insights: list[AttachmentInsight],
        tool_overrides: dict[str, Any],
        metadata: dict[str, Any],
        emit,
    ) -> None:
        if not user_content.strip() and attachment_insights:
            if any(item.artifact_type == "audio" for item in attachment_insights):
                user_content = "我发了一条语音给你。"
            else:
                user_content = "我发了一个附件给你。"
        user_content = user_content.strip()
        if not user_content:
            raise ValueError("mobile chat content or attachment is required")

        request_id = f"mreq_{uuid.uuid4().hex}"
        turn_uid = f"turn_{uuid.uuid4().hex}"
        user_platform_message_id = platform_message_id or f"mobile_user_{uuid.uuid4().hex}"
        started = time.perf_counter()
        await emit(
            {
                "event": "ack",
                "request_id": request_id,
                "turn_uid": turn_uid,
                "conversation_id": scope.conversation_id,
            }
        )

        retrieval_started = time.perf_counter()
        user_context = MessageContext(
            platform_message_id=user_platform_message_id,
            author_id=author_id,
        )
        user_metadata = {
            "display_name": display_name,
            "source": "mobile",
            "attachments": [self._sanitize_attachment_insight(item) for item in attachment_insights],
            **metadata,
        }
        user_message = self.memory_service.ingest_message(
            scope,
            sender_type="user",
            content=user_content,
            context=user_context,
            metadata=user_metadata,
        )
        await self.presence_state.update_from_user_message(scope, user_content, message_id=user_message.id)
        memory_context = self.memory_service.retrieve_for_reply(
            scope,
            current_user_input=user_content,
            before_message_id=user_message.id,
        )
        retrieval_latency_ms = (time.perf_counter() - retrieval_started) * 1000

        planning_started = time.perf_counter()
        mode_state = self.product_store.get_mode_state(scope.user_id, scope.conversation_id)
        reply_plan = self.planner.plan(
            user_input=user_content,
            memory_context=memory_context,
            mode_state=mode_state,
            attachment_count=len(attachment_insights),
        )
        override_notes: list[str] = []
        if isinstance(tool_overrides.get("search"), bool):
            reply_plan.should_search = bool(tool_overrides["search"])
            override_notes.append(f"search={reply_plan.should_search}")
        if isinstance(tool_overrides.get("draw"), bool):
            reply_plan.should_draw = bool(tool_overrides["draw"])
            override_notes.append(f"draw={reply_plan.should_draw}")
        if reply_plan.should_draw:
            reply_plan.request_type = "draw"
        elif reply_plan.should_search:
            reply_plan.request_type = "search"
        else:
            reply_plan.request_type = "chat"
        if override_notes:
            note = "手机端工具菜单显式设置：" + "，".join(override_notes) + "。"
            reply_plan.system_note = f"{reply_plan.system_note} {note}"
            reply_plan.user_note = f"{reply_plan.user_note} {note}"
        planning_latency_ms = (time.perf_counter() - planning_started) * 1000
        await emit(
            {
                "event": "plan",
                "request_type": reply_plan.request_type,
                "scene": reply_plan.scene,
                "reply_goal": reply_plan.reply_goal,
                "should_search": reply_plan.should_search,
                "should_draw": reply_plan.should_draw,
                "mode": mode_state.mode,
                "learning_mode": mode_state.learning_mode,
                "tool_overrides": tool_overrides,
            }
        )

        search_digest = None
        search_latency_ms = 0.0
        if reply_plan.should_search:
            search_started = time.perf_counter()
            search_digest = await self.search_service.search(user_content)
            search_latency_ms = (time.perf_counter() - search_started) * 1000
            await emit(
                {
                    "event": "search",
                    "query": search_digest.query,
                    "items": [asdict(item) for item in search_digest.items],
                    "note": search_digest.note,
                }
            )

        if self.settings.reality_context_enabled:
            await self.reality_context.refresh_if_stale(scope)

        extra_context_blocks = self._build_extra_context_blocks(
            scope,
            attachment_insights,
            search_digest,
            user_text=user_content,
            memory_context=memory_context,
        )
        prompt_started = time.perf_counter()
        prepared = self.reply_service.build_prepared_reply(
            scope=scope,
            user_content=user_content,
            user_message=user_message,
            memory_context=memory_context,
            mode_state=mode_state,
            reply_plan=reply_plan,
            extra_context_blocks=extra_context_blocks,
        )
        prompt_latency_ms = (time.perf_counter() - prompt_started) * 1000

        generation_started = time.perf_counter()
        generated_file = None
        if reply_plan.should_draw:
            generation_result = await self.reply_service.generate_reply(prepared)
            if self.settings.human_presence_enabled:
                repaired_text, lint_info = self.presence_state.lint_reply(prepared.scope, generation_result.text)
                generation_result.text = repaired_text
                setattr(generation_result, "presence_lint", lint_info)
            await emit({"event": "delta", "text": generation_result.text, "full_text": generation_result.text})
            image_prompt = self._build_image_prompt(prepared.user_message.content, attachment_insights)
            try:
                output_path = str(Path("data/generated_images") / f"{uuid.uuid4().hex}.png")
                generated_file = await self.reply_service.llm_client.generate_image(prompt=image_prompt, output_path=output_path)
                await emit(
                    {
                        "event": "draw_result",
                        "file_path": generated_file,
                        "image_url": f"/mobile/generated-images/{Path(generated_file).name}",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                self.product_store.record_error(
                    component="mobile_draw",
                    message=f"Image generation failed: {type(exc).__name__}",
                    details={"error": str(exc), "request_id": request_id, "prompt_chars": len(image_prompt)},
                    related_turn_uid=turn_uid,
                )
                await emit(
                    {
                        "event": "draw_error",
                        "message": "这张图我先没顺利出出来，但画面设定我已经接住了。",
                        "error_type": type(exc).__name__,
                    }
                )
            assistant_text = generation_result.text
        else:
            last_text = ""

            async def on_progress(text: str, is_final: bool) -> None:
                nonlocal last_text
                if text == last_text:
                    return
                delta = text[len(last_text) :] if text.startswith(last_text) else text
                last_text = text
                await emit(
                    {
                        "event": "delta",
                        "text": delta,
                        "full_text": text,
                        "is_final": is_final,
                    }
                )

            if self.settings.human_presence_enabled:
                generation_result = await self.reply_service.generate_reply(prepared)
                repaired_text, lint_info = self.presence_state.lint_reply(prepared.scope, generation_result.text)
                generation_result.text = repaired_text
                setattr(generation_result, "presence_lint", lint_info)
                await on_progress(generation_result.text, True)
            else:
                generation_result = await self.reply_service.stream_reply(prepared, on_progress=on_progress)
                if not last_text:
                    await on_progress(generation_result.text, True)
            assistant_text = generation_result.text
        generation_latency_ms = (time.perf_counter() - generation_started) * 1000
        presence_lint = getattr(generation_result, "presence_lint", {})

        finalize_started = time.perf_counter()
        assistant_platform_message_id = f"mobile_assistant_{uuid.uuid4().hex}"
        assistant_context = MessageContext(
            platform_message_id=assistant_platform_message_id,
            author_id="shen-zhiwei",
            reply_to_platform_message_id=user_platform_message_id,
        )
        assistant_metadata: dict[str, Any] = {
            "source": "mobile",
            "mode": mode_state.mode,
            "learning_mode": mode_state.learning_mode,
            "request_type": reply_plan.request_type,
            "scene": reply_plan.scene,
            "reply_goal": reply_plan.reply_goal,
            "model_name": generation_result.model_name,
            "backup_model_name": generation_result.backup_model_name,
            "fallback_used": generation_result.fallback_used,
            "search_used": bool(search_digest),
            "generated_image_path": generated_file,
            "request_id": request_id,
            "turn_uid": turn_uid,
            "presence_lint": presence_lint,
        }
        assistant_message = await self.reply_service.finalize_reply(
            prepared,
            assistant_content=assistant_text,
            assistant_context=assistant_context,
            assistant_metadata=assistant_metadata,
        )

        prompt_used = generation_result.prompt_used
        if prompt_used and prompt_used.usage.long_term_memory_uids:
            self.product_store.record_memory_hits(
                scope.user_id,
                prompt_used.usage.long_term_memory_uids,
                context_type="reply",
            )
            self.memory_store.touch_long_term_memories(prompt_used.usage.long_term_memory_uids)

        self._mark_proactive_response(scope, user_message.id)
        open_loop_ledger = self.presence_state.update_after_turn(
            scope,
            user_text=user_content,
            assistant_text=assistant_text,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
        )
        companion_day_update = self.day_engine.record_user_turn(
            scope,
            user_text=user_content,
            assistant_text=assistant_text,
            user_message_id=user_message.id,
            attachment_insights=attachment_insights,
        )
        finalize_latency_ms = (time.perf_counter() - finalize_started) * 1000
        latency_ms = (time.perf_counter() - started) * 1000
        stage_latency_ms = {
            "attachments": 0.0,
            "retrieval": round(retrieval_latency_ms, 2),
            "planning": round(planning_latency_ms, 2),
            "search": round(search_latency_ms, 2),
            "prompt_build": round(prompt_latency_ms, 2),
            "generation": round(generation_latency_ms, 2),
            "finalize": round(finalize_latency_ms, 2),
            "total": round(latency_ms, 2),
        }
        prompt_char_count = prompt_used.usage.prompt_char_count if prompt_used else 0
        estimated_input_tokens = prompt_used.usage.estimated_input_tokens if prompt_used else 0
        estimated_output_tokens = self._estimate_tokens(assistant_text)
        estimated_total_tokens = estimated_input_tokens + estimated_output_tokens
        estimated_cost_usd = self._estimate_model_cost_usd(
            generation_result.model_name,
            input_tokens=estimated_input_tokens,
            output_tokens=estimated_output_tokens,
        )
        metrics = self.metrics_service.evaluate(
            reply_text=assistant_text,
            memory_context=memory_context,
            plan=reply_plan,
            search_used=bool(search_digest),
            proactive_acceptance=self._recent_proactive_acceptance_rate(),
            proactive_cold_response_rate=self._recent_proactive_cold_rate(),
        )
        observability_metrics = {
            **metrics,
            "request_id": request_id,
            "turn_uid": turn_uid,
            "prompt_char_count": prompt_char_count,
            "estimated_input_tokens": estimated_input_tokens,
            "estimated_output_tokens": estimated_output_tokens,
            "estimated_total_tokens": estimated_total_tokens,
            "estimated_cost_usd": round(estimated_cost_usd, 6),
            "attachment_count": len(attachment_insights),
            "search_count": 0 if search_digest is None else len(search_digest.items),
            "search_note": None if search_digest is None else search_digest.note,
            "stage_latency_ms": stage_latency_ms,
        }
        self.product_store.record_experience_metrics(
            turn_uid,
            persona_consistency=float(metrics["persona_consistency"]),
            memory_hit_quality=float(metrics["memory_hit_quality"]),
            memory_usage_rate=float(metrics["memory_usage_rate"]),
            proactive_acceptance=float(metrics["proactive_acceptance"]),
            repeated_comfort_rate=float(metrics["repeated_comfort_rate"]),
            over_explaining_rate=float(metrics["over_explaining_rate"]),
            tool_trace_leakage_rate=float(metrics["tool_trace_leakage_rate"]),
            proactive_cold_response_rate=float(metrics["proactive_cold_response_rate"]),
            structure_type=str(metrics["structure_type"]),
            metadata={
                "scene": reply_plan.scene,
                "request_type": reply_plan.request_type,
                "request_id": request_id,
                "estimated_cost_usd": round(estimated_cost_usd, 6),
                "presence_lint": presence_lint,
                "open_loop_count": len(open_loop_ledger.get("open_loops", [])),
                "companion_day": companion_day_update,
                "source": "mobile",
            },
        )
        self.product_store.record_turn_trace(
            turn_uid=turn_uid,
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            session_id=scope.session_id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            request_type=reply_plan.request_type,
            reply_goal=reply_plan.reply_goal,
            scene=reply_plan.scene,
            mode_text=reply_plan.mode_text,
            model_name=generation_result.model_name,
            backup_model_name=generation_result.backup_model_name,
            fallback_used=generation_result.fallback_used,
            latency_ms=latency_ms,
            user_input=self._observability_preview(user_content),
            assistant_reply=self._observability_preview(assistant_text),
            attachments=[self._sanitize_attachment_insight(item) for item in attachment_insights],
            search_context=[] if search_digest is None else [self._sanitize_search_context(search_digest)],
            planning={
                **asdict(reply_plan),
                "request_id": request_id,
                "turn_uid": turn_uid,
                "search_note": None if search_digest is None else search_digest.note,
                "source": "mobile",
            },
            retrieval=self._build_retrieval_snapshot(
                memory_context,
                prompt_usage=None if prompt_used is None else prompt_used.usage,
                request_id=request_id,
            ),
            metrics=observability_metrics,
        )
        self.product_store.create_memory_snapshot(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            session_id=scope.session_id,
            turn_uid=turn_uid,
            snapshot=self._build_memory_snapshot(
                memory_context,
                prompt_usage=None if prompt_used is None else prompt_used.usage,
                request_id=request_id,
            ),
        )
        self.task_manager.enqueue(
            task_type="turn_postprocess",
            payload={
                "request_id": request_id,
                "scope": {
                    "platform": scope.platform,
                    "conversation_id": scope.conversation_id,
                    "user_id": scope.user_id,
                    "channel_id": scope.channel_id,
                    "guild_id": scope.guild_id,
                    "session_id": scope.session_id,
                },
                "user_message_id": user_message.id,
                "assistant_message_id": assistant_message.id,
                "turn_uid": turn_uid,
            },
            dedupe_key=f"turn:{assistant_message.id}",
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            session_id=scope.session_id,
            priority=0.9,
        )
        await emit(
            {
                "event": "final",
                "request_id": request_id,
                "turn_uid": turn_uid,
                "text": assistant_text,
                "user_message_id": user_message.id,
                "assistant_message_id": assistant_message.id,
                "model_name": generation_result.model_name,
                "fallback_used": generation_result.fallback_used,
                "latency_ms": round(latency_ms, 2),
                "generated_image_path": generated_file,
                "image_url": None if generated_file is None else f"/mobile/generated-images/{Path(generated_file).name}",
            }
        )

    async def _maybe_handle_command(
        self,
        message: discord.Message,
        scope: ConversationScope,
        text: str,
    ) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        mode_state = self.product_store.get_mode_state(scope.user_id, scope.conversation_id)

        if normalized in {"/status", "状态", "当前模式", "模式状态"}:
            await message.channel.send(self._render_status(scope, mode_state))
            return True

        if normalized == "/reality":
            await self.reality_context.refresh_if_stale(scope)
            await message.channel.send(self._render_reality_status(scope))
            return True

        if normalized in {"/pause", "暂停主动", "先别主动找我"}:
            self.presence_state.apply_manual_update(
                scope,
                {
                    "user_sleep_state": "asleep",
                    "user_sleep_state_confidence": 0.85,
                    "note": "chat pause command",
                },
            )
            await message.channel.send("好，我先放轻一点不主动吵你。你回我一句，我就知道你回来了。")
            return True

        if normalized in {"/resume", "恢复主动"}:
            self.presence_state.apply_manual_update(
                scope,
                {
                    "user_sleep_state": "awake",
                    "user_sleep_state_confidence": 0.9,
                    "note": "chat resume command",
                },
            )
            await message.channel.send("嗯，我知道你回来了。那我继续陪着你。")
            return True

        if normalized == "/model":
            await message.channel.send(self._render_model_status(mode_state))
            return True

        if normalized.startswith("/model ") or normalized.startswith("模式 "):
            parts = normalized.split(maxsplit=2)
            if len(parts) < 2:
                await message.channel.send(self._render_model_status(mode_state))
                return True
            selected = parts[1].lower()
            custom_model = parts[2].strip() if len(parts) >= 3 else None
            mode = self._normalize_mode(selected)
            if mode is None:
                await message.channel.send(
                    f"没认出这个模式：`{selected}`。\n{self._render_model_status(mode_state)}"
                )
                return True
            if mode == "custom" and not custom_model:
                await message.channel.send(
                    "自定义模式还缺模型名，比如：`/model custom gpt-4.1-mini`。\n"
                    f"{self._render_model_status(mode_state)}"
                )
                return True
            updated = self.product_store.upsert_mode_state(
                scope.user_id,
                scope.conversation_id,
                mode=mode,
                learning_mode=mode_state.learning_mode,
                custom_model=custom_model if mode == "custom" else mode_state.custom_model,
                backup_model=mode_state.backup_model or self.settings.resolve_backup_model(),
                metadata={"source": "chat_command"},
            )
            await message.channel.send(self._render_model_status(updated))
            return True

        if normalized == "/study":
            await message.channel.send(self._render_study_status(mode_state))
            return True

        if normalized in {"/study on", "学习模式 开启", "开启学习模式"}:
            updated = self.product_store.upsert_mode_state(
                scope.user_id,
                scope.conversation_id,
                mode=mode_state.mode,
                learning_mode=True,
                custom_model=mode_state.custom_model,
                backup_model=mode_state.backup_model or self.settings.resolve_backup_model(),
                metadata={"source": "chat_command"},
            )
            await message.channel.send(self._render_study_status(updated))
            return True

        if normalized in {"/study off", "学习模式 关闭", "关闭学习模式"}:
            updated = self.product_store.upsert_mode_state(
                scope.user_id,
                scope.conversation_id,
                mode=mode_state.mode,
                learning_mode=False,
                custom_model=mode_state.custom_model,
                backup_model=mode_state.backup_model or self.settings.resolve_backup_model(),
                metadata={"source": "chat_command"},
            )
            await message.channel.send(self._render_study_status(updated))
            return True

        if normalized.startswith("/study ") or normalized.startswith("学习模式 "):
            await message.channel.send(
                f"学习模式只支持 `on` 或 `off`。\n{self._render_study_status(mode_state)}"
            )
            return True

        if normalized == "/proactive":
            await message.channel.send(self._render_proactive_status(scope))
            return True

        if normalized in {"/proactive on", "主动消息 开启", "开启主动消息"}:
            set_proactive_preferences(
                settings=self.settings,
                product_store=self.product_store,
                memory_store=self.memory_store,
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                enabled=True,
                source="chat_command",
            )
            await message.channel.send(self._render_proactive_status(scope))
            return True

        if normalized in {"/proactive off", "主动消息 关闭", "关闭主动消息"}:
            set_proactive_preferences(
                settings=self.settings,
                product_store=self.product_store,
                memory_store=self.memory_store,
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                enabled=False,
                source="chat_command",
            )
            await message.channel.send(self._render_proactive_status(scope))
            return True

        if normalized.startswith("/proactive ") or normalized.startswith("主动消息 "):
            selected = normalized.split(maxsplit=1)[1] if " " in normalized else ""
            cadence = normalize_proactive_cadence(selected)
            if cadence is not None:
                set_proactive_preferences(
                    settings=self.settings,
                    product_store=self.product_store,
                    memory_store=self.memory_store,
                    user_id=scope.user_id,
                    conversation_id=scope.conversation_id,
                    cadence=cadence,
                    source="chat_command",
                )
                await message.channel.send(self._render_proactive_status(scope))
                return True
            await message.channel.send(
                f"主动消息支持 `on`、`off`、`low`、`normal`、`high`。\n{self._render_proactive_status(scope)}"
            )
            return True
        return False

    def _normalize_mode(self, raw_mode: str) -> str | None:
        if raw_mode in {"自动", "auto"}:
            return "auto"
        if raw_mode in {"快速", "fast", "quick"}:
            return "fast"
        if raw_mode in {"深度", "deep", "thinking", "think"}:
            return "think"
        if raw_mode in {"自定义", "custom"}:
            return "custom"
        return None

    def _render_model_status(self, mode_state: ModeState) -> str:
        line = f"当前模型模式：{self._display_mode_label(mode_state)}"
        if (mode_state.mode or "").lower() == "custom" and mode_state.custom_model:
            return f"{line}\n自定义模型：{mode_state.custom_model}"
        return line

    def _render_study_status(self, mode_state: ModeState) -> str:
        return f"学习模式：{'开启' if mode_state.learning_mode else '关闭'}"

    def _render_proactive_status(self, scope: ConversationScope) -> str:
        if not self.settings.enable_proactive_messages:
            return "主动消息：系统总开关关闭。"
        prefs = get_proactive_preferences(
            settings=self.settings,
            product_store=self.product_store,
            memory_store=self.memory_store,
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
        )
        policy = proactive_cadence_policy(str(prefs.get("cadence") or "low"))
        enabled = bool(prefs.get("enabled"))
        next_eligible_at, next_reason = self._next_proactive_eligible_at(scope, policy)
        cadence_label = {"low": "低频", "normal": "中频", "high": "高频"}.get(str(prefs.get("cadence")), "低频")
        lines = [
            f"主动消息：{'开启' if enabled else '关闭'}",
            f"频率：{cadence_label}（空闲 {policy['min_idle_minutes']} 分钟后才考虑；间隔 {policy['min_interval_minutes']}-{policy['max_interval_minutes']} 分钟；每日最多 {policy['daily_max']} 条）",
        ]
        if next_eligible_at:
            lines.append(f"下一次最早可主动：{next_eligible_at}（{next_reason}）")
        lines.append("命令：`/proactive on/off`，或 `/proactive low|normal|high`。")
        return "\n".join(lines)

    def _next_proactive_eligible_at(self, scope: ConversationScope, policy: dict[str, int]) -> tuple[str, str]:
        candidates: list[tuple[datetime, str]] = []
        latest_user = self.memory_store.get_latest_user_message(scope.conversation_id)
        if latest_user is not None:
            user_at = parse_iso8601(latest_user.created_at)
            if user_at is not None:
                if user_at.tzinfo is None:
                    user_at = user_at.replace(tzinfo=timezone.utc)
                candidates.append((user_at + timedelta(minutes=int(policy["min_idle_minutes"])), "等待用户空闲"))
        backoff = self.product_store.get_app_setting(proactive_backoff_key(scope.conversation_id), {})
        if isinstance(backoff, dict):
            until = parse_iso8601(str(backoff.get("until") or ""))
            if until is not None:
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                candidates.append((until, "冷却中"))
        latest_proactive = next(
            (
                item
                for item in self.product_store.list_proactive_messages(limit=80)
                if item.user_id == scope.user_id and item.conversation_id == scope.conversation_id
            ),
            None,
        )
        if latest_proactive is not None:
            sent_at = parse_iso8601(latest_proactive.sent_at)
            if sent_at is not None:
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                if latest_proactive.status == "sent":
                    candidates.append((sent_at + timedelta(minutes=int(policy["unanswered_followup_minutes"])), "等回应后续"))
                else:
                    candidates.append((sent_at + timedelta(minutes=int(policy["min_interval_minutes"])), "主动消息间隔"))
        now = datetime.now(timezone.utc)
        future = [(when, reason) for when, reason in candidates if when > now]
        if not future:
            return "", "eligible"
        when, reason = max(future, key=lambda item: item[0])
        return when.astimezone().strftime("%Y-%m-%d %H:%M"), reason

    def _render_reality_status(self, scope: ConversationScope) -> str:
        payload = self.reality_context.build_dashboard_payload(scope)
        summary = payload.get("summary") or {}
        location = summary.get("location") or {}
        weather = summary.get("weather") or {}
        events = payload.get("items") or []
        lines = [
            f"现实锚点：{'开启' if summary.get('enabled') else '关闭'}",
            f"地点：{location.get('label') or '-'}",
        ]
        if weather.get("summary_text"):
            lines.append(f"外面：{weather['summary_text']}")
        else:
            lines.append("外面：暂时没有可用天气缓存")
        if events:
            lines.append("接下来：")
            for event in events[:4]:
                title = truncate_text(compact_text(str(event.get("title") or "")), 42)
                start_at = event.get("start_at") or "-"
                lines.append(f"- {start_at} {title}")
        else:
            lines.append("接下来：没有 48 小时内可见日程")
        return "\n".join(lines)

    def _display_mode_label(self, mode_state: ModeState) -> str:
        mode = (mode_state.mode or "auto").lower()
        if mode in {"fast", "quick", "快速"}:
            return "快速（fast）"
        if mode in {"think", "thinking", "deep", "深度"}:
            return "思考（think）"
        if mode in {"custom", "自定义"}:
            return "自定义（custom）"
        return "自动（auto）"

    def _render_status(self, scope: ConversationScope, mode_state: ModeState) -> str:
        recent_turns = self.product_store.list_recent_turns(conversation_id=scope.conversation_id, limit=20)
        requests_last_hour = 0
        now = datetime.now(timezone.utc)
        for turn in recent_turns:
            created_at = parse_iso8601(turn.created_at)
            if created_at is None:
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if (now - created_at).total_seconds() <= 3600:
                requests_last_hour += 1
        preview_plan = ReplyPlan(
            request_type="chat",
            scene="学习辅导" if mode_state.learning_mode else "分析解释",
            reply_goal="解释",
            mood="平稳",
            rhythm="平稳",
            should_search=False,
            should_draw=False,
            learning_mode=mode_state.learning_mode,
            mode_text=mode_state.mode,
            preferred_length="medium",
            system_note="",
            user_note="",
        )
        resolved_model = self.reply_service._resolve_primary_model(mode_state, preview_plan)
        return (
            f"当前模式：{self._display_mode_label(mode_state)}\n"
            f"学习模式：{'开启' if mode_state.learning_mode else '关闭'}\n"
            f"{self._render_proactive_status(scope)}\n"
            f"当前主模型：{resolved_model}\n"
            f"备用模型：{mode_state.backup_model or self.settings.resolve_backup_model() or '未配置'}\n"
            f"近 1 小时请求数：{requests_last_hour}\n"
            f"Dashboard：http://{self.settings.dashboard_host}:{self.settings.dashboard_port}"
        )

    async def _stream_text_reply(
        self,
        message: discord.Message,
        prepared: PreparedReply,
    ) -> tuple[ReplyGenerationResult, list[discord.Message]]:
        publisher = DiscordReplyPublisher(source_message=message, settings=self.settings)
        if self.settings.human_presence_enabled:
            generation = await self.reply_service.generate_reply(prepared)
            repaired_text, lint_info = self.presence_state.lint_reply(prepared.scope, generation.text)
            generation.text = repaired_text
            setattr(generation, "presence_lint", lint_info)
            await publisher.publish_human(generation.text)
            return generation, publisher.sent_messages

        release_state = ProgressiveReleaseState(
            flush_chars=self.settings.streaming_flush_chars,
            max_silence_ms=self.settings.streaming_max_silence_ms,
        )

        async def on_progress(text: str, is_final: bool) -> None:
            if not release_state.should_release(text, force=is_final):
                return
            await publisher.publish(text)
            release_state.mark_released(text)

        generation = await self.reply_service.stream_reply(prepared, on_progress=on_progress)
        if not publisher.sent_messages:
            await publisher.publish(generation.text)
        return generation, publisher.sent_messages

    async def _handle_draw_request(
        self,
        message: discord.Message,
        prepared: PreparedReply,
        attachment_insights: list[AttachmentInsight],
        *,
        request_id: str,
        turn_uid: str,
    ) -> dict[str, Any]:
        generation = await self.reply_service.generate_reply(prepared)
        if self.settings.human_presence_enabled:
            repaired_text, lint_info = self.presence_state.lint_reply(prepared.scope, generation.text)
            generation.text = repaired_text
            setattr(generation, "presence_lint", lint_info)
        publisher = DiscordReplyPublisher(source_message=message, settings=self.settings)
        if self.settings.human_presence_enabled:
            await publisher.publish_human(generation.text)
        else:
            await publisher.publish(generation.text)
        image_prompt = self._build_image_prompt(prepared.user_message.content, attachment_insights)
        image_path = None
        try:
            output_path = str(Path("data/generated_images") / f"{uuid.uuid4().hex}.png")
            image_path = await self.reply_service.llm_client.generate_image(prompt=image_prompt, output_path=output_path)
            await message.channel.send(file=discord.File(image_path))
        except Exception as exc:  # noqa: BLE001
            self.product_store.record_error(
                component="draw",
                message=f"Image generation failed: {type(exc).__name__}",
                details={
                    "error": str(exc),
                    "request_id": request_id,
                    "prompt_chars": len(image_prompt),
                    "attachment_context_count": len(attachment_insights),
                },
                related_turn_uid=turn_uid,
            )
            await message.channel.send("这张图我先没顺利出出来，但画面设定我已经接住了。你要是愿意，我可以立刻帮你再换一种更稳的画法。")
        return {
            "messages": publisher.sent_messages,
            "assistant_text": generation.text,
            "image_path": image_path,
            "reply_generation": generation,
        }

    def _build_image_prompt(self, user_content: str, attachment_insights: list[AttachmentInsight]) -> str:
        if not attachment_insights:
            return user_content
        details = "\n".join(f"- {item.context_line()}" for item in attachment_insights)
        return f"{user_content}\n\n参考这些附件线索：\n{details}"

    def _build_extra_context_blocks(
        self,
        scope: ConversationScope,
        attachment_insights: list[AttachmentInsight],
        search_digest: SearchDigest | None,
        *,
        user_text: str = "",
        memory_context: Any | None = None,
    ) -> list[str]:
        blocks: list[str] = [build_current_time_context(self.settings.bot_timezone)]
        reality_block = self.reality_context.build_context_block(scope)
        if reality_block:
            blocks.append(reality_block)
        presence_block = self.presence_state.build_context_block(scope)
        if presence_block:
            blocks.append(presence_block)
        day_block = self.day_engine.build_context_block(scope)
        if day_block:
            blocks.append(day_block)
        if memory_context is not None:
            reply_beats = self.presence_state.build_reply_beats(
                scope,
                user_text=user_text,
                memory_context=memory_context,
            )
            if reply_beats:
                blocks.append(reply_beats)
        attachment_block = self.attachment_service.build_context(attachment_insights)
        if attachment_block:
            blocks.append(attachment_block)
        if search_digest and search_digest.items:
            blocks.append(search_digest.to_context_block())
        return blocks

    def _build_retrieval_snapshot(self, memory_context, *, prompt_usage=None, request_id: str | None = None) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "recent_messages": [
                {
                    "id": item.id,
                    "sender_type": item.sender_type,
                    "preview": self._observability_preview(item.content, limit=96),
                }
                for item in memory_context.recent_messages[-6:]
            ],
            "session_memories": [
                {"memory_type": item.memory_type, "preview": self._observability_preview(item.content, limit=88)}
                for item in memory_context.session_memories
            ],
            "long_term_memories": [
                {
                    "memory_uid": item.memory_uid,
                    "memory_type": item.memory_type,
                    "category": item.category,
                    "preview": self._observability_preview(item.content, limit=88),
                }
                for item in memory_context.long_term_memories
            ],
            "structured_facts": [
                {"namespace": item.namespace, "key": item.key}
                for item in memory_context.structured_facts
            ],
            "relationship_states": [
                {"dimension": item.dimension, "preview": self._observability_preview(item.value, limit=64)}
                for item in memory_context.relationship_states
            ],
            "summary": self._observability_preview(memory_context.summary.content, limit=120) if memory_context.summary else None,
            "retrieved_counts": {
                "recent_messages": len(memory_context.recent_messages),
                "session_memories": len(memory_context.session_memories),
                "long_term_memories": len(memory_context.long_term_memories),
                "structured_facts": len(memory_context.structured_facts),
                "relationship_states": len(memory_context.relationship_states),
            },
            "used_prompt": None
            if prompt_usage is None
            else {
                "recent_message_ids": prompt_usage.recent_message_ids,
                "session_memory_ids": prompt_usage.session_memory_ids,
                "long_term_memory_uids": prompt_usage.long_term_memory_uids,
                "structured_fact_keys": prompt_usage.structured_fact_keys,
                "relationship_dimensions": prompt_usage.relationship_dimensions,
                "summary_included": prompt_usage.summary_included,
                "summary_version": prompt_usage.summary_version,
            },
        }

    def _build_memory_snapshot(self, memory_context, *, prompt_usage=None, request_id: str | None = None) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "recent_messages": [
                self._observability_preview(item.content, limit=96)
                for item in memory_context.recent_messages[-8:]
            ],
            "session_memories": [
                {"memory_type": item.memory_type, "preview": self._observability_preview(item.content, limit=88)}
                for item in memory_context.session_memories
            ],
            "long_term_memories": [
                {
                    "memory_uid": item.memory_uid,
                    "memory_type": item.memory_type,
                    "category": item.category,
                    "preview": self._observability_preview(item.content, limit=88),
                    "importance": item.importance,
                }
                for item in memory_context.long_term_memories
            ],
            "structured_facts": [
                {"namespace": item.namespace, "key": item.key}
                for item in memory_context.structured_facts
            ],
            "relationship_states": [
                {
                    "dimension": item.dimension,
                    "preview": self._observability_preview(item.value, limit=64),
                    "weight": item.weight,
                }
                for item in memory_context.relationship_states
            ],
            "summary": None if memory_context.summary is None else self._observability_preview(memory_context.summary.content, limit=120),
            "used_prompt": None
            if prompt_usage is None
            else {
                "session_memory_ids": prompt_usage.session_memory_ids,
                "long_term_memory_uids": prompt_usage.long_term_memory_uids,
                "summary_included": prompt_usage.summary_included,
            },
        }

    def _mark_proactive_response(self, scope: ConversationScope, response_message_id: int) -> None:
        latest = next(
            (
                item
                for item in self.product_store.list_proactive_messages(limit=80)
                if item.conversation_id == scope.conversation_id and item.user_id == scope.user_id and item.status == "sent"
            ),
            None,
        )
        if latest is None:
            return
        sent_at = parse_iso8601(latest.sent_at)
        if sent_at is None:
            return
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        latency_minutes = max((datetime.now(timezone.utc) - sent_at).total_seconds() / 60.0, 0.0)
        self.product_store.mark_proactive_response(
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            response_message_id=response_message_id,
            response_latency_minutes=latency_minutes,
        )
        self.presence_state.record_proactive_response(
            scope,
            proactive_uid=latest.proactive_uid,
            response_message_id=response_message_id,
            response_latency_minutes=latency_minutes,
        )

    def _recent_proactive_acceptance_rate(self) -> float:
        proactive = self.product_store.list_proactive_messages(limit=40)
        if not proactive:
            return 0.0
        accepted = sum(1 for item in proactive if item.accepted)
        return accepted / len(proactive)

    def _recent_proactive_cold_rate(self) -> float:
        proactive = self.product_store.list_proactive_messages(limit=40)
        if not proactive:
            return 0.0
        cold = sum(1 for item in proactive if item.cold_response)
        return cold / len(proactive)

    def _proactive_opt_in_enabled(self, user_id: str) -> bool:
        fact = self.memory_store.get_structured_fact(
            user_id,
            namespace="support",
            key="proactive_opt_in",
        )
        if fact is None:
            return False
        return fact.value.strip().lower() in {"on", "true", "yes", "enabled"}

    def _observability_preview(self, text: str, *, limit: int | None = None) -> str:
        char_limit = limit or self.settings.observability_content_preview_chars
        return truncate_text(compact_text(text), char_limit)

    def _sanitize_attachment_insight(self, item: AttachmentInsight) -> dict[str, Any]:
        return {
            "filename": item.filename,
            "artifact_type": item.artifact_type,
            "content_type": item.content_type,
            "summary_text": self._observability_preview(item.summary_text, limit=120),
            "truncated": item.truncated,
            "metadata": item.metadata,
        }

    def _sanitize_search_context(self, search_digest: SearchDigest) -> dict[str, Any]:
        return {
            "query": self._observability_preview(search_digest.query, limit=80),
            "mode": search_digest.mode,
            "note": None if search_digest.note is None else self._observability_preview(search_digest.note, limit=120),
            "item_count": len(search_digest.items),
            "sources": [
                {
                    "title": self._observability_preview(item.title, limit=72),
                    "url": self._observability_preview(item.url, limit=96),
                }
                for item in search_digest.items[:3]
            ],
        }

    def _estimate_tokens(self, text: str) -> int:
        normalized = compact_text(text)
        if not normalized:
            return 0
        return max((len(normalized) + 3) // 4, 1)

    def _estimate_model_cost_usd(
        self,
        model_name: str | None,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        if not model_name:
            return 0.0
        normalized = model_name.strip().lower()
        input_rate, output_rate = self.MODEL_COST_HINTS.get(normalized, (0.0004, 0.0016))
        return (input_tokens / 1000.0) * input_rate + (output_tokens / 1000.0) * output_rate
