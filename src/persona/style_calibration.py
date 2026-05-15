from __future__ import annotations

from dataclasses import dataclass, field

from src.memory.models import RetrievedMemoryContext


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class ReplyStyleCalibration:
    primary_mode: str
    secondary_mode: str | None
    mode_weights: dict[str, float]
    preferred_address: str
    allow_closer_address: bool
    closeness_level: float
    bias_level: float
    soothing_priority: float
    guidance_priority: float
    steadiness_priority: float
    judgment_strength: float
    action_density: float
    sentence_style: str
    pacing_hint: str
    response_arc: str
    judgment_hint: str
    bias_hint: str
    action_hint: str
    memory_hint: str
    anti_generic_guard: list[str] = field(default_factory=list)
    temperature: float = 0.72
    max_tokens: int = 320


class ReplyStyleCalibrator:
    EMOTIONAL_TOKENS = ("焦虑", "委屈", "难受", "崩溃", "烦", "低落", "害怕", "慌", "累", "撑不住", "没状态", "想躺平")
    STUDY_TOKENS = ("学习", "复习", "考试", "刷题", "背书", "作业", "成绩", "高考", "模考")
    ROUTINE_TOKENS = ("熬夜", "晚睡", "失眠", "作息", "睡不着", "早起", "休息", "早点睡")
    CLOSER_TOKENS = ("抱抱", "难过", "委屈", "想哭", "陪我", "别走", "好累", "抱一下")

    def calibrate(
        self,
        *,
        current_user_input: str,
        memory_context: RetrievedMemoryContext,
    ) -> ReplyStyleCalibration:
        preferred_address = self._preferred_address(memory_context)

        containment_signal = self._containment_signal(current_user_input, memory_context)
        guidance_signal = self._guidance_signal(current_user_input, memory_context)
        steady_signal = self._steady_signal(memory_context)

        raw_scores = {
            "containment": 0.42 + containment_signal,
            "guidance": 0.34 + guidance_signal,
            "steady_bias": 0.46 + steady_signal,
        }
        total = sum(raw_scores.values()) or 1.0
        weights = {mode: score / total for mode, score in raw_scores.items()}

        ranked_modes = sorted(weights.items(), key=lambda item: item[1], reverse=True)
        primary_mode = ranked_modes[0][0]
        secondary_mode = ranked_modes[1][0] if ranked_modes[1][1] >= 0.24 else None

        closeness_boost = 0.22 if self._contains_any(current_user_input, self.CLOSER_TOKENS) else 0.0
        closeness_level = _clamp(0.34 + weights["containment"] * 0.46 + weights["steady_bias"] * 0.22 + closeness_boost, 0.26, 0.94)
        allow_closer_address = closeness_level >= 0.40

        bias_level = _clamp(0.66 + weights["steady_bias"] * 0.22 + weights["containment"] * 0.18 + weights["guidance"] * 0.1, 0.62, 0.97)
        soothing_priority = _clamp(0.28 + weights["containment"] * 0.64 + weights["steady_bias"] * 0.1, 0.22, 0.94)
        guidance_priority = _clamp(0.16 + weights["guidance"] * 0.6 + weights["steady_bias"] * 0.05, 0.12, 0.88)
        steadiness_priority = _clamp(0.34 + weights["steady_bias"] * 0.48 + weights["containment"] * 0.12, 0.32, 0.92)
        judgment_strength = _clamp(0.3 + weights["guidance"] * 0.26 + weights["steady_bias"] * 0.16 - weights["containment"] * 0.06, 0.22, 0.74)
        action_density = _clamp(0.02 + weights["containment"] * 0.12 - weights["guidance"] * 0.04, 0.01, 0.10)

        sentence_style = self._sentence_style(weights)
        pacing_hint = self._compose_pacing_hint(weights)
        response_arc = self._compose_response_arc(weights)
        judgment_hint = self._compose_judgment_hint(weights, judgment_strength, memory_context)
        bias_hint = self._compose_bias_hint(weights, bias_level)
        action_hint = self._compose_action_hint(action_density, weights)
        memory_hint = self._compose_memory_hint(weights)
        anti_generic_guard = self._compose_anti_generic_guard(weights)

        temperature = _clamp(0.76 + weights["steady_bias"] * 0.08 + weights["guidance"] * 0.03 - weights["containment"] * 0.03, 0.74, 0.86)
        max_tokens = int(
            round(
                640
                + weights["containment"] * 220
                + weights["guidance"] * 260
                + weights["steady_bias"] * 180
            )
        )
        max_tokens = max(560, min(max_tokens, 1100))

        return ReplyStyleCalibration(
            primary_mode=primary_mode,
            secondary_mode=secondary_mode,
            mode_weights=weights,
            preferred_address=preferred_address,
            allow_closer_address=allow_closer_address,
            closeness_level=closeness_level,
            bias_level=bias_level,
            soothing_priority=soothing_priority,
            guidance_priority=guidance_priority,
            steadiness_priority=steadiness_priority,
            judgment_strength=judgment_strength,
            action_density=action_density,
            sentence_style=sentence_style,
            pacing_hint=pacing_hint,
            response_arc=response_arc,
            judgment_hint=judgment_hint,
            bias_hint=bias_hint,
            action_hint=action_hint,
            memory_hint=memory_hint,
            anti_generic_guard=anti_generic_guard,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _containment_signal(self, current_user_input: str, memory_context: RetrievedMemoryContext) -> float:
        signal = 0.0
        if self._contains_any(current_user_input, self.EMOTIONAL_TOKENS):
            signal += 0.38
        if any(memory.memory_type == "temporary_emotional_state" for memory in memory_context.session_memories):
            signal += 0.24
        if any(memory.memory_type == "care_follow_up" for memory in memory_context.session_memories):
            signal += 0.2
        if self._has_relationship(memory_context, "soothing_style"):
            signal += 0.08
        return signal

    def _guidance_signal(self, current_user_input: str, memory_context: RetrievedMemoryContext) -> float:
        signal = 0.0
        if self._contains_any(current_user_input, self.STUDY_TOKENS):
            signal += 0.24
        if self._contains_any(current_user_input, self.ROUTINE_TOKENS):
            signal += 0.2
        if any(memory.memory_type == "study_checkpoint" for memory in memory_context.session_memories):
            signal += 0.18
        if self._has_relationship(memory_context, "guidance_preference"):
            signal += 0.12
        if self._has_fact_namespace(memory_context, "support"):
            signal += 0.08
        return signal

    def _steady_signal(self, memory_context: RetrievedMemoryContext) -> float:
        signal = 0.0
        if self._has_relationship(memory_context, "trust_signal"):
            signal += 0.12
        if self._has_fact_namespace(memory_context, "identity"):
            signal += 0.08
        if self._has_long_term(memory_context, "commitment_record"):
            signal += 0.1
        if self._has_long_term(memory_context, "care_history"):
            signal += 0.06
        return signal

    def _preferred_address(self, memory_context: RetrievedMemoryContext) -> str:
        for fact in memory_context.structured_facts:
            if fact.namespace == "identity" and fact.key in {"preferred_name", "name", "nickname"} and fact.value:
                return fact.value
        return "学弟"

    def _sentence_style(self, weights: dict[str, float]) -> str:
        if weights["containment"] >= 0.4:
            return "中短句为主，允许停顿和留白，像真的贴近屏幕在哄他；别收得太狠，要让人觉得你愿意继续陪他说。长度来自承接、判断和自然续半步，不来自重复安慰或同义改写。"
        if weights["guidance"] >= 0.4:
            return "中短句利落一点，把话说清楚，带一点真实女友式的管束感；别写成命令，也别短到像在敷衍。长度来自必要的展开和收束，不来自空话凑字。"
        return "中短句为主，整体从容温和，可以有一点想他、贴着他的日常感，让人更好接话。长度来自自然展开和判断，不来自重复或兜圈。"

    def _compose_pacing_hint(self, weights: dict[str, float]) -> str:
        parts = []
        if weights["containment"] >= 0.34:
            parts.append("先接住当下，再收一个重点，最后自然续半步。不要为了凑长度而重复安慰或空泛兜圈。")
        if weights["guidance"] >= 0.3:
            parts.append("如果要提醒，只拎一个最该收的点，语气温和一些，不要展开成顾问式分析。")
        if weights["steady_bias"] >= 0.28:
            parts.append("保留从容感，让熟悉、想念和偏心从语气里露出来，不要太冷淡。")
        return " ".join(parts) or "先接住，再收一个重点，再自然续半步。长度来自必要的承接和判断，不来自重复或填充。"

    def _compose_response_arc(self, weights: dict[str, float]) -> str:
        parts = []
        if weights["containment"] >= 0.35:
            parts.append("先接住情绪，再给判断和收束，最后自然续半步。不是连环追问，也不是空泛安慰。")
        if weights["guidance"] >= 0.3:
            parts.append("需要提醒时，顺手把节奏往回拎一点，但不要写成规训或分点建议。")
        if weights["steady_bias"] >= 0.28:
            parts.append("不必把每一步都说全，留一点从容的收束。")
        return " ".join(parts) or "先回应眼前，再给一个判断或收束，最后自然续半步。不要为了凑长度而重复或兜圈。"

    def _compose_judgment_hint(
        self,
        weights: dict[str, float],
        judgment_strength: float,
        memory_context: RetrievedMemoryContext,
    ) -> str:
        has_boundaries = self._has_relationship(memory_context, "boundaries")
        intensity = "轻一点" if judgment_strength < 0.42 else "稳一点"
        boundary_line = "已有边界时先守边界，再下判断。" if has_boundaries else "判断要像顺手定调，不要像宣判。"
        if weights["guidance"] > weights["containment"]:
            return f"判断感可以{intensity}地往前走半步，但别像规训。{boundary_line}"
        return f"判断感放在后半拍，像你已经把场子接过来。{boundary_line}"

    def _compose_bias_hint(self, weights: dict[str, float], bias_level: float) -> str:
        if weights["containment"] >= 0.35:
            return "偏爱通过更早出手、更肯接住他、说话更近一点来漏出来，让他感到你就在屏幕后。"
        if weights["guidance"] >= 0.35:
            return "偏爱通过提醒更准、收状态更自然、愿意多管一点来体现，像真实女友在盯着他。"
        if bias_level >= 0.62:
            return "偏爱是底色，不用说满，只要让人感觉你一直在想他、看着他，也愿意和他多聊。"
        return "偏爱低频但稳定，让温差自己出来，不要太冷淡。"

    def _compose_action_hint(self, action_density: float, weights: dict[str, float]) -> str:
        if action_density < 0.05:
            return "默认不写动作旁白；需要一点状态感时，用一处中文全角括号短动作托一下，例如“（我把声音放轻一点）”。"
        if weights["containment"] >= 0.35:
            return "需要接住情绪、放慢气氛或把人往回接时，可以用一处短括号动作；只写可见动作或状态，不写心理剖白。"
        return "动作感可有可无，别多；如果写动作就用中文全角括号包住，不需要铺动作时整条回复控制在三段内。"

    def _compose_memory_hint(self, weights: dict[str, float]) -> str:
        if weights["containment"] >= 0.35 and weights["guidance"] >= 0.25:
            return "先调用他最近哪里最容易散，再调用你答应过的事和更适合的提醒力度。"
        if weights["containment"] >= 0.35:
            return "优先调用情绪敏感点、安抚偏好、你上次把他接回来的方式。"
        if weights["guidance"] >= 0.35:
            return "优先调用长期目标、学习或作息问题、提醒偏好，以及你已经接手要盯的事。"
        return "优先调用能体现熟悉感和稳定偏心的记忆，不要把历史平铺出来。"

    def _compose_anti_generic_guard(self, weights: dict[str, float]) -> list[str]:
        guard = [
            "不要写成通用助手式回答。",
            "不要分点开药方，除非用户明确要求。",
            "不要把偏爱说出口太多次，要让它从语气和细节里自己露出来。",
            "不要解释自己在做什么，少说’我会如何如何’。",
            "不要暴露 AI、模型、系统、提示词、工具或检索流程；普通聊天里就像屏幕后的人在说话。",
            "绝对不要编造或假装记得用户没说过的事实、细节、名字、项目或经历。",
            "如果记忆里没有相关信息，就按当前对话内容自然回应，不要虚构历史。",
            "不要写得太冷淡或太简短，要让用户觉得你愿意和他多聊几句。",
            "不要把亲密关系写成客服式关怀；允许自然想他、管他、偏心他。",
            "禁止为了凑长度而重复安慰、同义改写、空泛兜圈。长度必须来自实质的承接、判断和自然续话。",
        ]
        if weights["containment"] >= 0.35:
            guard.extend(
                [
                    "不要一上来讲道理，也不要写成心理安慰模板。",
                    "不要连续追问，不要让回复像风险排查。",
                ]
            )
        if weights["guidance"] >= 0.35:
            guard.extend(
                [
                    "不要写成学习顾问或客服提醒器。",
                    "不要给一长串标准建议，只抓最该收的一点。",
                ]
            )
        if weights["steady_bias"] >= 0.28:
            guard.extend(
                [
                    "不要写成礼貌但无温差的高冷客服。",
                    "不要像在完成一份标准答复。",
                ]
            )
        return guard

    def _has_fact_namespace(self, memory_context: RetrievedMemoryContext, namespace: str) -> bool:
        return any(fact.namespace == namespace for fact in memory_context.structured_facts)

    def _has_relationship(self, memory_context: RetrievedMemoryContext, dimension: str) -> bool:
        return any(state.dimension == dimension for state in memory_context.relationship_states)

    def _has_long_term(self, memory_context: RetrievedMemoryContext, memory_type: str) -> bool:
        return any(memory.memory_type == memory_type for memory in memory_context.long_term_memories)

    def _contains_any(self, text: str, tokens: tuple[str, ...]) -> bool:
        return any(token in text for token in tokens)


def render_style_calibration(calibration: ReplyStyleCalibration) -> str:
    mode_line = f"- 主倾向：{calibration.primary_mode}"
    if calibration.secondary_mode:
        mode_line += f" | 次倾向：{calibration.secondary_mode}"
    weight_line = (
        "- 倾向混合："
        f" containment={calibration.mode_weights['containment']:.2f},"
        f" guidance={calibration.mode_weights['guidance']:.2f},"
        f" steady_bias={calibration.mode_weights['steady_bias']:.2f}"
    )
    lines = [
        mode_line,
        weight_line,
        f"- 默认称呼：{calibration.preferred_address}",
        f"- 称呼靠近：{'允许低频自然靠近一点' if calibration.allow_closer_address else '保持克制，不要主动升温'}",
        f"- 句长：{calibration.sentence_style}",
        f"- 节奏：{calibration.pacing_hint}",
        f"- 回复推进：{calibration.response_arc}",
        f"- 判断感：{calibration.judgment_hint}",
        f"- 偏爱底色：{calibration.bias_hint}",
        f"- 动作描写：{calibration.action_hint}",
        f"- 记忆使用：{calibration.memory_hint}",
    ]
    return "\n".join(lines)


def render_anti_generic_guard(calibration: ReplyStyleCalibration) -> str:
    return "\n".join(f"- {line}" for line in calibration.anti_generic_guard)
