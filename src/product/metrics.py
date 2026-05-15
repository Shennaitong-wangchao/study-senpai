from __future__ import annotations

from collections import Counter

from src.memory.models import RetrievedMemoryContext
from src.product.models import ReplyPlan
from src.utils.text_utils import overlap_score


class ExperienceMetricsService:
    TOOL_TRACE_TOKENS = ("我调用", "我搜索", "我查了工具", "根据搜索", "根据检索", "识别结果显示")
    COMFORT_TOKENS = ("别怕", "没事的", "你已经很棒了", "都会好的", "抱抱你")
    PERSONA_RISK_TOKENS = ("作为AI", "作为助手", "很高兴为你服务", "请问还有什么可以帮您")

    def evaluate(
        self,
        *,
        reply_text: str,
        memory_context: RetrievedMemoryContext,
        plan: ReplyPlan,
        search_used: bool,
        proactive_acceptance: float = 0.0,
        proactive_cold_response_rate: float = 0.0,
    ) -> dict[str, float | str]:
        previous_replies = [message.content for message in memory_context.recent_messages if message.sender_type == "assistant"]
        repeated_comfort = self._repeated_comfort_rate(reply_text, previous_replies)
        tool_trace = self._tool_trace_rate(reply_text)
        persona_consistency = self._persona_consistency(reply_text, plan, tool_trace)
        structure_type = self._structure_type(reply_text)
        memory_usage_rate = self._memory_usage_rate(reply_text, memory_context)
        memory_hit_quality = self._memory_hit_quality(reply_text, memory_context, search_used)
        over_explaining = self._over_explaining_rate(reply_text, plan)
        return {
            "persona_consistency": round(persona_consistency, 3),
            "memory_hit_quality": round(memory_hit_quality, 3),
            "memory_usage_rate": round(memory_usage_rate, 3),
            "proactive_acceptance": round(proactive_acceptance, 3),
            "repeated_comfort_rate": round(repeated_comfort, 3),
            "over_explaining_rate": round(over_explaining, 3),
            "tool_trace_leakage_rate": round(tool_trace, 3),
            "proactive_cold_response_rate": round(proactive_cold_response_rate, 3),
            "structure_type": structure_type,
        }

    def _persona_consistency(self, reply_text: str, plan: ReplyPlan, tool_trace_rate: float) -> float:
        score = 0.86
        if plan.scene == "学习辅导" and ("\n1." in reply_text or "\n- " in reply_text):
            score += 0.04
        if plan.scene == "情绪安慰" and len(reply_text) < 220:
            score += 0.04
        if any(token in reply_text for token in self.PERSONA_RISK_TOKENS):
            score -= 0.4
        score -= tool_trace_rate * 0.45
        return max(0.0, min(score, 1.0))

    def _memory_usage_rate(self, reply_text: str, memory_context: RetrievedMemoryContext) -> float:
        candidate_texts = [memory.content for memory in memory_context.long_term_memories[:4]]
        candidate_texts.extend(memory.value for memory in memory_context.structured_facts[:4])
        if not candidate_texts:
            return 0.0
        overlaps = [overlap_score(reply_text, text) for text in candidate_texts]
        return min(sum(overlaps) / max(len(overlaps), 1) * 1.8, 1.0)

    def _memory_hit_quality(
        self,
        reply_text: str,
        memory_context: RetrievedMemoryContext,
        search_used: bool,
    ) -> float:
        if not memory_context.long_term_memories and not memory_context.structured_facts:
            return 0.0
        direct_overlap = max(
            [overlap_score(reply_text, memory.content) for memory in memory_context.long_term_memories[:3]]
            + [overlap_score(reply_text, fact.value) for fact in memory_context.structured_facts[:3]]
            + [0.0]
        )
        if search_used:
            direct_overlap *= 0.92
        return min(0.35 + direct_overlap * 1.4, 1.0)

    def _repeated_comfort_rate(self, reply_text: str, previous_replies: list[str]) -> float:
        if not previous_replies:
            return 0.0
        comfort_hits = sum(1 for token in self.COMFORT_TOKENS if token in reply_text)
        if comfort_hits == 0:
            return 0.0
        repeated = 0
        for previous in previous_replies[-4:]:
            if any(token in previous and token in reply_text for token in self.COMFORT_TOKENS):
                repeated += 1
        return min((repeated / max(len(previous_replies[-4:]), 1)) * 0.8, 1.0)

    def _over_explaining_rate(self, reply_text: str, plan: ReplyPlan) -> float:
        length = len(reply_text)
        sentence_count = sum(reply_text.count(mark) for mark in ("。", "！", "？", ".", "!", "?"))
        if plan.scene == "学习辅导":
            return 0.0 if length < 900 else min((length - 900) / 700, 1.0)
        if plan.scene == "情绪安慰":
            return min(max(length - 280, 0) / 520 + max(sentence_count - 7, 0) * 0.05, 1.0)
        return min(max(length - 520, 0) / 900, 1.0)

    def _tool_trace_rate(self, reply_text: str) -> float:
        count = sum(1 for token in self.TOOL_TRACE_TOKENS if token in reply_text)
        if count == 0:
            return 0.0
        return min(count * 0.35, 1.0)

    def _structure_type(self, reply_text: str) -> str:
        if "```" in reply_text:
            return "code"
        if "\n- " in reply_text or "\n1." in reply_text:
            return "list"
        if "\n>" in reply_text:
            return "quote"
        if "\n\n" in reply_text:
            return "paragraph"
        return "plain"
