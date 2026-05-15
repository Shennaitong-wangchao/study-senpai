from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.persona.immersion_lint import repair_immersive_voice
from src.persona.style_calibration import ReplyStyleCalibration


@dataclass
class StyleGuardResult:
    text: str
    applied_repairs: list[str] = field(default_factory=list)


class ReplyStyleGuard:
    SELF_EXPLANATION_RE = re.compile(r"(我会记得|我会记住|我会照顾|我会一直|我会陪着|我会看着|我不会忘)")
    INLINE_ENUMERATOR_RE = re.compile(r"(^|[\s。！？!?])(?:首先|其次|最后)[，,：:]?\s*")
    AI_LEAK_SENTENCE_RE = re.compile(
        r"[^。！？!?]*(?:作为(?:一个)?AI|我是(?:一个)?AI|我只是(?:一个)?AI|作为(?:语言)?模型|我是(?:语言)?模型|我没有真实(?:身体|生活)|系统提示|提示词|工具调用)[^。！？!?]*[。！？!?]?"
    )
    SERVICE_TONE_REPLACEMENTS = {
        "如果你愿意的话，": "",
        "如果你愿意的话": "",
        "根据你的情况，": "",
        "根据你的情况": "",
        "建议你可以": "",
        "你可以尝试": "先",
        "以下几点": "",
    }
    GENERIC_REPLACEMENTS = {
        "你已经很棒了": "先别急着把自己往下压。",
        "你已经很努力了": "先别急着把自己往下压。",
        "你已经做得很好了": "先别急着把自己往下压。",
        "先休息一下吧": "先缓一下。",
        "没关系，一切都会好起来的": "先别急，眼下先把这一阵稳住。",
    }

    def review(self, text: str, calibration: ReplyStyleCalibration) -> StyleGuardResult:
        repaired = text.strip()
        repairs: list[str] = []

        updated = self._soften_service_tone(repaired)
        if updated != repaired:
            repaired = updated
            repairs.append("softened_service_tone")

        updated = self._trim_self_explanations(repaired)
        if updated != repaired:
            repaired = updated
            repairs.append("trimmed_self_explanations")

        updated = self._remove_ai_leakage(repaired)
        if updated != repaired:
            repaired = updated
            repairs.append("removed_ai_leakage")

        updated = self._soften_generic_reassurance(repaired, calibration)
        if updated != repaired:
            repaired = updated
            repairs.append("softened_generic_reassurance")

        updated = repair_immersive_voice(repaired)
        if updated != repaired:
            repaired = updated
            repairs.append("repaired_immersive_voice")

        updated = self._flatten_listy_lines(repaired)
        if updated != repaired:
            repaired = updated
            repairs.append("flattened_listy_lines")

        repaired = re.sub(r"(?:^|\s)(首先|其次|最后)[，,：:]?\s*", " ", repaired)
        repaired = repaired.replace("先先", "先")
        repaired = re.sub(r"[。]{2,}", "。", repaired)
        repaired = re.sub(r"\n{3,}", "\n\n", repaired).strip()
        return StyleGuardResult(text=repaired, applied_repairs=repairs)

    def _soften_service_tone(self, text: str) -> str:
        updated = text
        for old, new in self.SERVICE_TONE_REPLACEMENTS.items():
            updated = updated.replace(old, new)
        updated = re.sub(r"(?m)^(首先|其次|最后)[，,：:]?\s*", "", updated)
        updated = self.INLINE_ENUMERATOR_RE.sub(r"\1", updated)
        return updated

    def _trim_self_explanations(self, text: str) -> str:
        matches = list(self.SELF_EXPLANATION_RE.finditer(text))
        if len(matches) <= 1:
            return text

        sentences = re.split(r"(?<=[。！？!?])", text)
        kept = []
        self_explanation_kept = False
        for sentence in sentences:
            stripped = sentence.strip()
            if not stripped:
                continue
            stripped = re.sub(
                r"(我会(?:记得|记住|照顾|一直|陪着|看着|不会忘)[^，。！？!?]*)(?:[，,、]\s*我会(?:记得|记住|照顾|一直|陪着|看着|不会忘)[^，。！？!?]*)+",
                r"\1",
                stripped,
            )
            if self.SELF_EXPLANATION_RE.search(stripped):
                if self_explanation_kept:
                    continue
                self_explanation_kept = True
            kept.append(stripped)
        return "".join(kept).strip()

    def _soften_generic_reassurance(self, text: str, calibration: ReplyStyleCalibration) -> str:
        updated = text
        if calibration.soothing_priority >= 0.45:
            for old, new in self.GENERIC_REPLACEMENTS.items():
                updated = updated.replace(old, new)
        return updated

    def _remove_ai_leakage(self, text: str) -> str:
        updated = self.AI_LEAK_SENTENCE_RE.sub("", text)
        updated = updated.replace("AI助手", "我").replace("智能助手", "我")
        return updated.strip() or text

    def _flatten_listy_lines(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            return text
        if not any(re.match(r"^(?:[-*•]\s+|\d+\.\s+)", line) for line in lines):
            return text
        flattened = [re.sub(r"^(?:[-*•]\s+|\d+\.\s+)", "", line).strip() for line in lines]
        return " ".join(flattened)
