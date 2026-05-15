from __future__ import annotations

from dataclasses import dataclass
import re

from src.memory.models import MessageRecord


@dataclass
class MemoryGateDecision:
    should_extract: bool
    should_refresh_summary: bool
    reasons: list[str]


class MemoryGate:
    STABLE_FACT_TOKENS = (
        "叫我",
        "你可以叫我",
        "称呼我",
        "我喜欢",
        "我不喜欢",
        "别",
        "不要",
        "边界",
        "目标是",
        "想考",
        "想上",
        "准备考",
        "以后你",
        "你以后",
        "你可以多",
    )
    REPEATED_PATTERN_TOKENS = (
        "总是",
        "经常",
        "老是",
        "一直",
        "反复",
        "又",
        "还是",
        "每次",
    )
    ROUTINE_TOKENS = ("熬夜", "晚睡", "失眠", "作息", "睡不着", "黑白颠倒")
    STUDY_TOKENS = ("学习", "复习", "考试", "刷题", "作业", "模考", "成绩", "高考")
    EMOTIONAL_TOKENS = ("焦虑", "委屈", "难受", "崩溃", "烦", "低落", "害怕", "慌", "累", "撑不住")
    ASSISTANT_COMMITMENT_TOKENS = ("我会", "我来", "我记着", "我盯着", "我继续盯", "晚点再问", "提醒你")
    GUIDANCE_SIGNAL_TOKENS = ("提醒我", "督促我", "监督我", "管我", "别太", "安抚我", "陪我")
    MEMORY_REQUEST_TOKENS = ("记住", "别忘了", "之后记得", "以后记得", "下次记得")
    SHORT_TERM_FOLLOWUP_TOKENS = (
        "提醒",
        "记得",
        "问我",
        "盯",
        "到货",
        "到了",
        "要做",
        "要去",
        "要交",
        "要考",
        "复盘",
        "处理",
        "睡",
        "吃药",
    )
    TEMPORAL_PATTERN_RE = re.compile(
        r"(今天|今晚|明天|明晚|后天|这周|本周|下周|这两天|过几天|几天后|待会|等会|回头|"
        r"到时候|凌晨|早上|上午|中午|下午|晚上|每天|每周|每晚|周[一二三四五六日天末]|"
        r"最近|一直|平时|通常|以后|下次|长期)"
    )
    PERSONAL_FACT_PATTERN_RE = re.compile(
        r"我(?:最近|现在|一直|平时|通常|以后|这周|这个月|想|打算|准备|计划|负责|在做|正在|会|要|不想|不能|更喜欢|讨厌|习惯)"
    )
    PREFERENCE_PATTERN_RE = re.compile(r"我(?:比较|更)?(?:喜欢|偏爱|不喜欢|讨厌|害怕|受不了|接受不了)")
    BOUNDARY_PATTERN_RE = re.compile(r"(别|不要|先别|别再|不要再).{0,16}(对我|跟我|这么|这样)")
    SELF_DISCLOSURE_PATTERN_RE = re.compile(r"我(?:是|在|有|会|总会|老是|经常|容易).{2,40}")

    def __init__(self, *, summary_trigger_message_count: int = 16) -> None:
        self.summary_trigger_message_count = summary_trigger_message_count

    def decide(
        self,
        *,
        turn_messages: list[MessageRecord],
        recent_messages: list[MessageRecord],
        messages_since_summary: int,
    ) -> MemoryGateDecision:
        reasons: list[str] = []
        user_text = "\n".join(message.content for message in turn_messages if message.sender_type == "user")
        assistant_text = "\n".join(message.content for message in turn_messages if message.sender_type == "assistant")
        recent_user_texts = [message.content for message in recent_messages if message.sender_type == "user"]

        if self._contains_any(user_text, self.STABLE_FACT_TOKENS):
            reasons.append("stable_fact_signal")
        if self._contains_any(user_text, self.MEMORY_REQUEST_TOKENS):
            reasons.append("memory_request_signal")
        if self._contains_any(user_text, self.GUIDANCE_SIGNAL_TOKENS):
            reasons.append("relationship_signal")
        if self._contains_any(assistant_text, self.ASSISTANT_COMMITMENT_TOKENS):
            reasons.append("assistant_commitment")
        if self._has_structured_personal_signal(user_text):
            reasons.append("structured_personal_signal")
        if self._has_short_term_followup(user_text):
            reasons.append("short_term_followup")
        if self._has_repeated_pattern(user_text, recent_user_texts):
            reasons.append("repeated_pattern")

        should_refresh_summary = messages_since_summary >= self.summary_trigger_message_count
        should_extract = bool(reasons)
        return MemoryGateDecision(
            should_extract=should_extract,
            should_refresh_summary=should_refresh_summary,
            reasons=reasons,
        )

    def _has_repeated_pattern(self, user_text: str, recent_user_texts: list[str]) -> bool:
        if not recent_user_texts:
            return False
        current_has_pattern = self._contains_any(user_text, self.REPEATED_PATTERN_TOKENS)
        semantic_hits = 0
        token_groups = (self.ROUTINE_TOKENS, self.STUDY_TOKENS, self.EMOTIONAL_TOKENS)
        for tokens in token_groups:
            if self._contains_any(user_text, tokens) and any(self._contains_any(text, tokens) for text in recent_user_texts[-8:]):
                semantic_hits += 1
        return current_has_pattern and semantic_hits > 0

    def _contains_any(self, text: str, tokens: tuple[str, ...]) -> bool:
        return any(token in text for token in tokens)

    def _has_short_term_followup(self, user_text: str) -> bool:
        text = user_text.strip()
        if len(text) < 4:
            return False
        if not self.TEMPORAL_PATTERN_RE.search(text):
            return False
        if self._contains_any(text, self.SHORT_TERM_FOLLOWUP_TOKENS):
            return True
        return bool(re.search(r"(我|你|她|他|它).{0,24}(要|会|得|需要|准备|打算|记得|别忘)", text))

    def _has_structured_personal_signal(self, user_text: str) -> bool:
        text = user_text.strip()
        if len(text) < 6 or "我" not in text:
            return False
        if self.PREFERENCE_PATTERN_RE.search(text):
            return True
        if self.BOUNDARY_PATTERN_RE.search(text):
            return True
        if self.PERSONAL_FACT_PATTERN_RE.search(text) and self.TEMPORAL_PATTERN_RE.search(text):
            return True
        if self.SELF_DISCLOSURE_PATTERN_RE.search(text) and any(marker in text for marker in ("因为", "所以", "但是", "不过", "一直")):
            return True
        return False
