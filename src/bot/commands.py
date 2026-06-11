"""Discord 文本命令处理器。

支持在 DM 中输入 /goals, /review, /stats, /help 等命令。
"""
from __future__ import annotations

import logging
from typing import Any

import discord

from src.db.database import Database
from src.product.study import StudyService
from src.utils.time_utils import iso_utc_now


logger = logging.getLogger(__name__)

# 内存中存储活跃学习会话：user_id → session_uid
# 注意：Bot 重启后会丢失，生产环境可持久化到 Redis/DB
_active_sessions: dict[str, str] = {}


HELP_TEXT = """📚 **Study Senpai 可用命令**

`/help` — 查看所有命令
`/stats` — 查看学习统计（连续天数、今日复习数等）
`/goals` — 查看当前学习目标列表
`/review` — 查看今日到期的复习卡片
`/addgoal <标题> | <学科>` — 添加学习目标，如 `/addgoal 高考数学 | 数学`
`/addcard <问题> | <答案>` — 添加复习卡片，如 `/addcard 牛顿第一定律 | 惯性定律`
`/plan <目标标题或UID>` — 查看指定目标的每日学习计划建议
`/start [目标标题或UID]` — 开始计时学习会话（记录到数据库）
`/done <分钟数>` — 结束学习会话并记录时长，如 `/done 45`

其他任何消息都会直接发给学姐~"""


def _user_id_from_message(message: discord.Message) -> str:
    return str(message.author.id)


def _conv_id_from_message(message: discord.Message) -> str:
    return str(message.channel.id)


class CommandRouter:
    """识别并处理文本命令（/开头的消息）。"""

    def __init__(self, db: Database) -> None:
        self._study = StudyService(db=db)

    def is_command(self, content: str) -> bool:
        stripped = content.strip().lower()
        return stripped.startswith("/") and not stripped.startswith("// ")

    async def handle_command(self, message: discord.Message) -> str | None:
        """处理命令，返回回复文本；如果不是命令则返回 None。"""
        content = message.content.strip()
        if not content.startswith("/"):
            return None

        parts = content[1:].split(None, 1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""
        user_id = _user_id_from_message(message)
        conv_id = _conv_id_from_message(message)

        if cmd in ("help", "h", "帮助"):
            return HELP_TEXT

        if cmd in ("stats", "统计", "stat"):
            return self._handle_stats(user_id)

        if cmd in ("goals", "目标", "goal"):
            return self._handle_goals(user_id)

        if cmd in ("review", "复习", "rev"):
            return self._handle_review(user_id)

        if cmd in ("addgoal", "添加目标", "newgoal"):
            return self._handle_add_goal(user_id, conv_id, args)

        if cmd in ("addcard", "添加卡片", "newcard"):
            return self._handle_add_card(user_id, args)

        return None

    def _handle_stats(self, user_id: str) -> str:
        try:
            stats = self._study.get_study_stats(user_id)
            streak = stats.get("streak_days", 0)
            due = stats.get("due_today", 0)
            mastered = stats.get("mastered_items", 0)
            total = stats.get("total_items", 0)
            goals = stats.get("active_goals", 0)
            return (
                f"📊 **你的学习数据**\n\n"
                f"🔥 连续学习 **{streak}** 天\n"
                f"🃏 今日到期 **{due}** 张卡片\n"
                f"✅ 已掌握 **{mastered}/{total}** 张卡片\n"
                f"🎯 活跃目标 **{goals}** 个\n"
            )
        except Exception:
            logger.exception("Failed to get study stats for %s", user_id)
            return "获取统计失败，请稍后再试。"

    def _handle_goals(self, user_id: str) -> str:
        try:
            goals = self._study.list_goals(user_id)
            if not goals:
                return "你还没有学习目标。\n\n用 `/addgoal 高考数学 | 数学` 添加第一个目标吧！"
            lines = ["🎯 **你的学习目标**\n"]
            for g in goals[:8]:
                pct = g.get("progress_pct", 0)
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                date_info = f" (截止 {g['target_date'][:10]})" if g.get("target_date") else ""
                lines.append(f"**{g['title']}** {date_info}\n`{bar}` {pct}%\n")
            return "\n".join(lines)
        except Exception:
            logger.exception("Failed to list goals for %s", user_id)
            return "获取目标列表失败，请稍后再试。"

    def _handle_review(self, user_id: str) -> str:
        try:
            items = self._study.get_due_items(user_id, limit=5)
            if not items:
                return "🎉 今日复习已完成！没有到期卡片了。\n\n用 `/addcard 问题 | 答案` 添加新卡片。"
            lines = [f"🃏 **今日到期复习 ({len(items)} 张)**\n"]
            for i, item in enumerate(items, 1):
                lines.append(f"**{i}.** {item['front']}\n||{item['back']}||")
            lines.append("\n在 Dashboard 学习面板中记录复习结果。")
            return "\n".join(lines)
        except Exception:
            logger.exception("Failed to get due items for %s", user_id)
            return "获取复习列表失败，请稍后再试。"

    def _handle_add_goal(self, user_id: str, conv_id: str, args: str) -> str:
        if not args:
            return "用法：`/addgoal <目标标题> | <学科>`\n例：`/addgoal 高考数学备考 | 数学`"
        parts = args.split("|", 1)
        title = parts[0].strip()
        subject = parts[1].strip() if len(parts) > 1 else ""
        if not title:
            return "目标标题不能为空。"
        try:
            goal = self._study.create_goal(
                user_id=user_id,
                conv_id=conv_id,
                title=title,
                subject=subject or None,
                target_date=None,
            )
            return f"✅ 学习目标已创建：**{goal['title']}**\n\n用 `/goals` 查看所有目标。"
        except Exception:
            logger.exception("Failed to create goal for %s", user_id)
            return "创建目标失败，请稍后再试。"

    def _handle_add_card(self, user_id: str, args: str) -> str:
        if not args or "|" not in args:
            return "用法：`/addcard <问题> | <答案>`\n例：`/addcard 牛顿第一定律是什么？ | 惯性定律：物体保持原有运动状态`"
        parts = args.split("|", 1)
        front = parts[0].strip()
        back = parts[1].strip()
        if not front or not back:
            return "问题和答案都不能为空。"
        try:
            item = self._study.add_review_item(
                user_id=user_id,
                front=front,
                back=back,
                subject=None,
            )
            return f"✅ 复习卡片已添加！\n\n**Q:** {item['front']}\n**A:** {item['back']}\n\n下次复习时间：明天"
        except Exception:
            logger.exception("Failed to add review item for %s", user_id)
            return "添加卡片失败，请稍后再试。"
