from __future__ import annotations

import logging
import re

from src.core.settings import Settings
from src.core.types import ConversationScope
from src.llm.client import LLMClient
from src.llm.prompts.summary import SUMMARY_SYSTEM_PROMPT, build_summary_user_prompt
from src.memory.models import ConversationSummaryRecord, MessageRecord
from src.memory.store import MemoryStore
from src.utils.text_utils import truncate_text


logger = logging.getLogger(__name__)


class ConversationSummarizer:
    def __init__(self, store: MemoryStore, llm_client: LLMClient, settings: Settings) -> None:
        self.store = store
        self.llm_client = llm_client
        self.settings = settings

    async def maybe_refresh_summary(
        self,
        scope: ConversationScope,
        *,
        force: bool = False,
    ) -> ConversationSummaryRecord | None:
        latest = self.store.get_latest_summary(scope.conversation_id)
        after_message_id = latest.message_end_id if latest else 0
        new_messages = self.store.list_messages_after(scope.conversation_id, after_message_id)
        if not force and len(new_messages) < self.settings.summary_trigger_message_count:
            return latest

        transcript = self._render_transcript(new_messages)
        try:
            content = await self.llm_client.summarize(
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                user_prompt=build_summary_user_prompt(latest.content if latest else None, transcript),
                max_tokens=900,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Summary generation fell back to extractive mode for %s: %s", scope.conversation_id, exc)
            content = self._fallback_summary(latest.content if latest else None, new_messages)

        message_start_id = latest.message_start_id if latest else new_messages[0].id
        message_end_id = new_messages[-1].id
        message_count = (latest.message_count if latest else 0) + len(new_messages)
        version = (latest.version if latest else 0) + 1

        return self.store.insert_summary(
            scope,
            content=content,
            message_start_id=message_start_id,
            message_end_id=message_end_id,
            message_count=message_count,
            version=version,
            metadata={
                "new_message_count": len(new_messages),
                "estimated_turn_count": len([message for message in new_messages if message.sender_type == "user"]),
            },
        )

    def _render_transcript(self, messages: list[MessageRecord]) -> str:
        lines = [f"[{message.sender_type}] {truncate_text(message.content, 220)}" for message in messages]
        return "\n".join(lines)

    def _fallback_summary(
        self,
        previous_summary: str | None,
        messages: list[MessageRecord],
    ) -> str:
        sections = self._parse_summary_sections(previous_summary)

        user_messages = [message for message in messages if message.sender_type == "user"]
        assistant_messages = [message for message in messages if message.sender_type == "assistant"]

        stuck_points = self._collect_matching_lines(
            user_messages,
            ("焦虑", "委屈", "难受", "崩溃", "烦", "低落", "害怕", "慌", "累", "没状态", "压力"),
        )
        preference_lines = self._collect_matching_lines(
            user_messages,
            ("提醒", "安抚", "督促", "管", "不喜欢", "别太", "不要", "边界"),
        )
        commitment_lines = self._collect_matching_lines(
            assistant_messages,
            ("我会", "我记着", "我来", "我替你", "继续盯", "晚点再问", "提醒你"),
        )
        containment_lines = self._collect_matching_lines(
            assistant_messages,
            ("先别", "慢一点", "别急", "先把", "我在", "先缓", "收回来", "接住"),
        )
        unfinished_lines = self._collect_matching_lines(
            user_messages,
            ("还没", "还没做完", "之后", "明天", "今晚", "待会", "下一次", "继续"),
        )
        goal_lines = self._collect_matching_lines(
            user_messages,
            ("目标", "想考", "想上", "推进", "复习", "模考", "学习", "作息"),
        )

        self._extend_section(
            sections,
            "关系基调",
            ["继续保持克制、稳、带一点偏心地接住和收状态，不要滑向客服腔。"],
        )
        self._extend_section(sections, "最近真正卡住的点", stuck_points)
        self._extend_section(sections, "提醒/安抚偏好与禁区", preference_lines)
        self._extend_section(sections, "她接手要盯的事", commitment_lines)
        self._extend_section(sections, "最近一次怎么把人接回来", containment_lines)
        self._extend_section(sections, "未完事项", unfinished_lines)
        self._extend_section(sections, "长期目标推进", goal_lines)

        order = [
            "关系基调",
            "最近真正卡住的点",
            "提醒/安抚偏好与禁区",
            "她接手要盯的事",
            "最近一次怎么把人接回来",
            "未完事项",
            "长期目标推进",
        ]
        blocks = []
        for heading in order:
            lines = sections.get(heading, [])
            if not lines:
                continue
            blocks.append(f"{heading}：")
            blocks.extend(f"- {line}" for line in lines[:2])

        if not blocks:
            recent = []
            for message in messages[-6:]:
                prefix = "用户" if message.sender_type == "user" else "沈知微"
                recent.append(f"{prefix}: {truncate_text(message.content, 90)}")
            blocks.append("关系基调：")
            blocks.append("- 继续保持克制、稳、带一点偏心地接住和收状态。")
            blocks.append("未完事项：")
            blocks.extend(f"- {line}" for line in recent[:3])
        return "\n".join(blocks)

    def _collect_matching_lines(
        self,
        messages: list[MessageRecord],
        keywords: tuple[str, ...],
    ) -> list[str]:
        lines: list[str] = []
        for message in reversed(messages):
            content = truncate_text(message.content, 100)
            if any(keyword in content for keyword in keywords):
                normalized = re.sub(r"\s+", " ", content).strip()
                if normalized not in lines:
                    lines.append(normalized)
        return list(reversed(lines))

    def _parse_summary_sections(self, summary: str | None) -> dict[str, list[str]]:
        if not summary:
            return {}

        sections: dict[str, list[str]] = {}
        current_heading: str | None = None
        for raw_line in summary.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.endswith("：") and len(line) <= 20:
                current_heading = line[:-1]
                sections.setdefault(current_heading, [])
                continue
            if line.startswith("- "):
                line = line[2:].strip()
            if not line:
                continue
            if current_heading is None:
                current_heading = "关系基调"
                sections.setdefault(current_heading, [])
            if line not in sections[current_heading]:
                sections[current_heading].append(line)
        return sections

    def _extend_section(
        self,
        sections: dict[str, list[str]],
        heading: str,
        lines: list[str],
    ) -> None:
        if not lines:
            return
        bucket = sections.setdefault(heading, [])
        for line in lines:
            if line not in bucket:
                bucket.append(line)
