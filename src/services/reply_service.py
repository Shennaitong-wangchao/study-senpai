from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from src.core.settings import Settings
from src.core.types import ConversationScope, MessageContext
from src.llm.client import LLMClient
from src.llm.prompt_builder import PromptBuildResult, PromptBuilder
from src.memory.models import MessageRecord, RetrievedMemoryContext
from src.product.models import ModeState, ReplyPlan
from src.persona.style_calibration import ReplyStyleCalibration, ReplyStyleCalibrator
from src.persona.style_guard import ReplyStyleGuard
from src.services.memory_service import MemoryService


logger = logging.getLogger(__name__)


@dataclass
class PreparedReply:
    scope: ConversationScope
    current_user_input: str
    user_message: MessageRecord
    memory_context: RetrievedMemoryContext
    prompt: PromptBuildResult
    extra_context_blocks: list[str]
    style_calibration: ReplyStyleCalibration
    reply_plan: ReplyPlan
    mode_state: ModeState
    primary_model: str
    backup_model: str | None
    compact_prompt: PromptBuildResult | None = None


@dataclass
class ReplyGenerationResult:
    text: str
    model_name: str
    backup_model_name: str | None
    fallback_used: bool
    prompt_used: PromptBuildResult | None = None
    primary_stream_failed: bool = False


class ReplyService:
    def __init__(
        self,
        *,
        settings: Settings,
        memory_service: MemoryService,
        llm_client: LLMClient,
        prompt_builder: PromptBuilder,
    ) -> None:
        self.settings = settings
        self.memory_service = memory_service
        self.llm_client = llm_client
        self.prompt_builder = prompt_builder
        self.style_calibrator = ReplyStyleCalibrator()
        self.style_guard = ReplyStyleGuard()

    async def prepare_reply(
        self,
        *,
        scope: ConversationScope,
        user_content: str,
        user_context: MessageContext,
        mode_state: ModeState,
        reply_plan: ReplyPlan,
        user_metadata: dict[str, Any] | None = None,
        extra_context_blocks: list[str] | None = None,
    ) -> PreparedReply:
        user_message = self.memory_service.ingest_message(
            scope,
            sender_type="user",
            content=user_content,
            context=user_context,
            metadata=user_metadata or {},
        )
        memory_context = self.memory_service.retrieve_for_reply(
            scope,
            current_user_input=user_content,
            before_message_id=user_message.id,
        )
        return self.build_prepared_reply(
            scope=scope,
            user_content=user_content,
            user_message=user_message,
            memory_context=memory_context,
            mode_state=mode_state,
            reply_plan=reply_plan,
            extra_context_blocks=extra_context_blocks,
        )

    def build_prepared_reply(
        self,
        *,
        scope: ConversationScope,
        user_content: str,
        user_message: MessageRecord,
        memory_context: RetrievedMemoryContext,
        mode_state: ModeState,
        reply_plan: ReplyPlan,
        extra_context_blocks: list[str] | None = None,
    ) -> PreparedReply:
        style_calibration = self.style_calibrator.calibrate(
            current_user_input=user_content,
            memory_context=memory_context,
        )
        style_calibration = self._apply_plan_to_style(style_calibration, reply_plan)
        prompt = self.prompt_builder.build_messages(
            scope=scope,
            memory_context=memory_context,
            current_user_input=user_content,
            style_calibration=style_calibration,
            strategy_note=reply_plan.system_note,
            user_note=reply_plan.user_note,
            extra_context_blocks=extra_context_blocks,
        )

        if self.settings.debug_prompts:
            logger.info("Reply style calibration for %s: %s", scope.conversation_id, style_calibration)
            logger.info(
                "Prompt context for %s: [redacted] messages=%s chars=%s extra_blocks=%s",
                scope.conversation_id,
                len(prompt.messages),
                self._prompt_char_count(prompt),
                len(extra_context_blocks or []),
            )

        return PreparedReply(
            scope=scope,
            current_user_input=user_content,
            user_message=user_message,
            memory_context=memory_context,
            prompt=prompt,
            extra_context_blocks=list(extra_context_blocks or []),
            style_calibration=style_calibration,
            reply_plan=reply_plan,
            mode_state=mode_state,
            primary_model=self._resolve_primary_model(mode_state, reply_plan),
            backup_model=mode_state.backup_model or self.settings.resolve_backup_model(),
        )

    async def finalize_reply(
        self,
        prepared: PreparedReply,
        *,
        assistant_content: str,
        assistant_context: MessageContext,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> MessageRecord:
        assistant_message = self.memory_service.ingest_message(
            prepared.scope,
            sender_type="assistant",
            content=assistant_content,
            context=assistant_context,
            metadata=assistant_metadata or {},
        )
        return assistant_message

    async def generate_reply(
        self,
        prepared: PreparedReply,
    ) -> ReplyGenerationResult:
        compact_prompt: PromptBuildResult | None = None
        try:
            return await self._generate_for_model(
                prepared,
                prompt=prepared.prompt,
                model_name=prepared.primary_model,
                backup_model_name=prepared.backup_model,
                fallback_used=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Primary reply generation failed for %s: %s", prepared.scope.conversation_id, exc)
            if self._looks_like_context_overflow(exc):
                compact_prompt = self._build_compact_prompt(prepared)
                logger.warning(
                    "Prompt looks too long for %s, retrying compact prompt (%s -> %s chars)",
                    prepared.scope.conversation_id,
                    self._prompt_char_count(prepared.prompt),
                    self._prompt_char_count(compact_prompt),
                )
                try:
                    return await self._generate_for_model(
                        prepared,
                        prompt=compact_prompt,
                        model_name=prepared.primary_model,
                        backup_model_name=prepared.backup_model,
                        fallback_used=False,
                    )
                except Exception as compact_exc:  # noqa: BLE001
                    logger.warning(
                        "Compact prompt retry failed for %s: %s",
                        prepared.scope.conversation_id,
                        compact_exc,
                    )
            if prepared.backup_model and prepared.backup_model != prepared.primary_model:
                prompt_for_backup = compact_prompt or prepared.prompt
                try:
                    return await self._generate_for_model(
                        prepared,
                        prompt=prompt_for_backup,
                        model_name=prepared.backup_model,
                        backup_model_name=prepared.backup_model,
                        fallback_used=True,
                    )
                except Exception as backup_exc:  # noqa: BLE001
                    logger.warning(
                        "Backup reply generation failed for %s: %s",
                        prepared.scope.conversation_id,
                        backup_exc,
                    )
            text = self._heuristic_fallback(prepared.reply_plan)
            return ReplyGenerationResult(
                text=text,
                model_name="heuristic-fallback",
                backup_model_name=prepared.backup_model,
                fallback_used=True,
                prompt_used=None,
            )

    async def stream_reply(
        self,
        prepared: PreparedReply,
        *,
        on_progress,
    ) -> ReplyGenerationResult:
        streamed_text = ""
        primary_stream_failed = False
        try:
            async for delta in self.llm_client.stream_chat_completion(
                prepared.prompt.messages,
                model=prepared.primary_model,
                temperature=prepared.style_calibration.temperature,
                max_tokens=prepared.style_calibration.max_tokens,
                reasoning_effort=self._resolve_reasoning_effort(prepared),
                use_native_search=prepared.reply_plan.should_search,
            ):
                streamed_text += delta
                await on_progress(streamed_text, False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Primary streaming failed for %s: %s", prepared.scope.conversation_id, exc)
            primary_stream_failed = True

        if streamed_text:
            text = self._finalize_reply_text(streamed_text, prepared.style_calibration)
            await on_progress(text, True)
            return ReplyGenerationResult(
                text=text,
                model_name=prepared.primary_model,
                backup_model_name=prepared.backup_model,
                fallback_used=False,
                prompt_used=prepared.prompt,
                primary_stream_failed=primary_stream_failed,
            )

        generated = await self.generate_reply(prepared)
        await on_progress(generated.text, True)
        generated.primary_stream_failed = primary_stream_failed
        return generated

    def _postprocess_reply_text(self, reply_text: str) -> str:
        text = reply_text.strip()
        text = re.sub(r"^(?:沈知微|学姐)[:：]\s*", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"(?m)^(?:当然|好的|好哦)[，,]?\s*", "", text)

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if self._looks_like_list(lines):
            flattened = [re.sub(r"^(?:[-*•]\s+|\d+\.\s+)", "", line).strip() for line in lines]
            text = "\n".join(flattened)

        return text.strip()

    def _finalize_reply_text(
        self,
        raw_reply: str,
        style_calibration: ReplyStyleCalibration,
    ) -> str:
        reply_text = self._postprocess_reply_text(raw_reply)
        guard_result = self.style_guard.review(reply_text, style_calibration)
        reply_text = guard_result.text
        return reply_text

    def _resolve_primary_model(self, mode_state: ModeState, reply_plan: ReplyPlan) -> str:
        mode = (mode_state.mode or "auto").lower()
        if mode in {"custom", "自定义"} and mode_state.custom_model:
            return mode_state.custom_model
        if reply_plan.should_search and self.settings.llm_search_model:
            return self.settings.llm_search_model
        if mode in {"think", "deep", "thinking", "深度"}:
            return self.settings.llm_reply_model_thinking or self.settings.resolve_reply_model()
        if mode in {"fast", "quick", "快速"}:
            return self.settings.llm_reply_model_fast or self.settings.llm_model
        if reply_plan.learning_mode or reply_plan.scene in {"学习辅导", "分析解释"}:
            return self.settings.llm_reply_model_thinking or self.settings.resolve_reply_model()
        return self.settings.llm_reply_model_fast or self.settings.llm_model

    def _resolve_reasoning_effort(self, prepared: PreparedReply) -> str | None:
        primary = prepared.primary_model
        thinking_model = self.settings.llm_reply_model_thinking or ""
        if thinking_model and primary == thinking_model:
            return self.settings.llm_reply_reasoning_effort or None
        return None

    # P0-2: max_tokens 受控区间上限，由风格校准器控制的基准最大值
    _MAX_TOKENS_SCENE_CAP: int = 2048

    def _apply_plan_to_style(
        self,
        style: ReplyStyleCalibration,
        plan: ReplyPlan,
    ) -> ReplyStyleCalibration:
        # P0-2: 各场景只做小幅上调，不超过 _MAX_TOKENS_SCENE_CAP
        # 原代码把 max_tokens 抬到 8k-12k 会导致超长回复、尾延迟飙升与成本失控
        if plan.scene == "学习辅导":
            style.guidance_priority = min(style.guidance_priority + 0.22, 1.0)
            style.sentence_style = "解释时分步骤一点，但别冷。"
            style.pacing_hint = "先讲当前最关键的一步，再带着继续想。"
            style.response_arc = "先说结论或切入口，再把推理铺开。"
            style.max_tokens = min(max(style.max_tokens, style.max_tokens), self._MAX_TOKENS_SCENE_CAP)
        elif plan.scene == "情绪安慰":
            style.soothing_priority = min(style.soothing_priority + 0.2, 1.0)
            style.sentence_style = "中短句，先接住，再往下多陪半步，别写成空安慰。"
            style.pacing_hint = "先稳住当下感受，再替他把最卡的那一点收出来。"
            style.response_arc = "先接住情绪，再给判断和收束，最后自然续半步。"
            style.max_tokens = min(style.max_tokens, self._MAX_TOKENS_SCENE_CAP)
        elif plan.scene == "夸奖鼓励":
            style.bias_hint += " 夸奖要贴着刚发生的进步，再顺手往下接半步。"
            style.response_arc = "先点明哪里做得好，再把这份进展接稳，不要空夸。"
            style.max_tokens = min(style.max_tokens, self._MAX_TOKENS_SCENE_CAP)
        elif plan.scene == "边界收束":
            style.judgment_hint = "边界要明确，但不要像客服警告。"
            style.max_tokens = min(style.max_tokens, self._MAX_TOKENS_SCENE_CAP)

        if plan.reply_goal in {"督促", "轻压"}:
            style.guidance_priority = min(style.guidance_priority + 0.12, 1.0)
            style.response_arc += " 收尾要带一点向前推的力。"
        return style

    async def _generate_for_model(
        self,
        prepared: PreparedReply,
        *,
        prompt: PromptBuildResult,
        model_name: str,
        backup_model_name: str | None,
        fallback_used: bool,
    ) -> ReplyGenerationResult:
        raw_reply = await self.llm_client.chat_completion(
            prompt.messages,
            model=model_name,
            temperature=prepared.style_calibration.temperature,
            max_tokens=prepared.style_calibration.max_tokens,
            reasoning_effort=self._resolve_reasoning_effort_for_model(model_name),
            use_native_search=prepared.reply_plan.should_search,
        )
        text = self._finalize_reply_text(raw_reply, prepared.style_calibration)
        return ReplyGenerationResult(
            text=text,
            model_name=model_name,
            backup_model_name=backup_model_name,
            fallback_used=fallback_used,
            prompt_used=prompt,
        )

    def _resolve_reasoning_effort_for_model(self, model_name: str) -> str | None:
        thinking_model = self.settings.llm_reply_model_thinking or ""
        if thinking_model and model_name == thinking_model:
            return self.settings.llm_reply_reasoning_effort or None
        return None

    def _build_compact_prompt(self, prepared: PreparedReply) -> PromptBuildResult:
        if prepared.compact_prompt is None:
            prepared.compact_prompt = self.prompt_builder.build_messages(
                scope=prepared.scope,
                memory_context=prepared.memory_context,
                current_user_input=prepared.current_user_input,
                style_calibration=prepared.style_calibration,
                strategy_note=prepared.reply_plan.system_note,
                user_note=prepared.reply_plan.user_note,
                extra_context_blocks=prepared.extra_context_blocks,
                compact=True,
            )
        return prepared.compact_prompt

    def _looks_like_context_overflow(self, exc: Exception) -> bool:
        text = str(exc).lower()
        markers = (
            "maximum context length",
            "context length",
            "context window",
            "too many tokens",
            "prompt is too long",
            "input is too long",
            "context_window_exceeded",
        )
        return any(marker in text for marker in markers)

    def _prompt_char_count(self, prompt: PromptBuildResult) -> int:
        return sum(len(message["content"]) for message in prompt.messages)

    def _heuristic_fallback(self, plan: ReplyPlan) -> str:
        if plan.request_type == "search":
            return (
                "我这轮没法稳定联网核实最新信息，所以不想装作已经查过。"
                "你可以稍后再让我查一次，或者给我一个想核对的来源/时间点，我按那个范围帮你整理。"
            )
        if plan.scene == "情绪安慰":
            return "我先在。别急着把自己逼到更乱，先把这一口气缓下来，再跟我说最卡的那一点。"
        if plan.scene == "学习辅导":
            return "我们先别一口气摊太多。你把最卡的那一步扔给我，我带你一点点拆。"
        if plan.reply_goal == "夸奖":
            return "这次不是空口说好，是你真的把那一步走出来了。这个进展我记一笔。"
        return "我还在。你继续说，我先把这轮接稳。"

    def _looks_like_list(self, lines: list[str]) -> bool:
        if len(lines) < 3:
            return False
        return all(re.match(r"^(?:[-*•]\s+|\d+\.\s+)", line) for line in lines)
