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

        if cmd in ("plan", "计划", "studyplan"):
            return self._handle_plan(user_id, args)

        if cmd in ("start", "开始", "startlearn"):
            return self._handle_start(user_id, args)

        if cmd in ("done", "完成", "end", "finishlearn"):
            return self._handle_done(user_id, args)

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

    def _handle_plan(self, user_id: str, args: str) -> str:
        """显示指定目标的学习计划建议。

        用法：/plan <目标标题或UID>
        """
        if not args:
            return "用法：`/plan <目标标题或UID>`\n例：`/plan 高考数学备考`"
        try:
            # 先尝试按 UID 查找，再按标题模糊匹配
            goal = self._study.get_goal(args.strip())
            if goal is None:
                # 按标题模糊匹配（不区分大小写，取第一个匹配的）
                goals = self._study.list_goals(user_id)
                keyword = args.strip().lower()
                goal = next(
                    (g for g in goals if keyword in g["title"].lower()),
                    None,
                )
            if goal is None:
                return f"找不到目标「{args.strip()}」。\n\n用 `/goals` 查看所有目标。"

            plan = self._study.generate_study_plan(
                user_id=user_id,
                goal_uid=goal["goal_uid"],
            )
            urgency_label = {
                "low": "🟢 低",
                "medium": "🟡 中",
                "high": "🟠 高",
                "critical": "🔴 紧急",
            }.get(plan["urgency"], plan["urgency"])

            lines = [
                f"📋 **学习计划：{goal['title']}**\n",
                f"⏰ 紧迫程度：**{urgency_label}**",
                f"📅 每日学习：**{plan['daily_minutes']} 分钟**",
                f"🃏 每日卡片：**{plan['cards_per_day']} 张**",
            ]
            if plan.get("focus_areas"):
                lines.append("🎯 重点领域：" + "、".join(plan["focus_areas"]))
            if plan.get("weekly_checkpoints"):
                lines.append("\n📌 **里程碑计划**")
                for checkpoint in plan["weekly_checkpoints"]:
                    lines.append(f"• {checkpoint}")
            return "\n".join(lines)
        except Exception:
            logger.exception("Failed to generate plan for %s, args=%s", user_id, args)
            return "生成学习计划失败，请稍后再试。"

    def _handle_start(self, user_id: str, args: str) -> str:
        """开始计时学习会话（可选绑定到某个目标）。

        用法：/start [目标标题或UID]
        """
        try:
            goal_uid: str | None = None
            goal_title = ""
            if args.strip():
                # 尝试解析目标
                goal = self._study.get_goal(args.strip())
                if goal is None:
                    goals = self._study.list_goals(user_id)
                    keyword = args.strip().lower()
                    goal = next(
                        (g for g in goals if keyword in g["title"].lower()),
                        None,
                    )
                if goal:
                    goal_uid = goal["goal_uid"]
                    goal_title = goal["title"]

            session_uid = self._study.start_session(user_id=user_id, goal_uid=goal_uid)
            _active_sessions[user_id] = session_uid

            if goal_title:
                return (
                    f"⏱️ 学习会话已开始！\n\n"
                    f"🎯 绑定目标：**{goal_title}**\n"
                    f"📌 会话 ID：`{session_uid[:16]}...`\n\n"
                    f"完成后用 `/done <分钟数>` 记录学习时长。"
                )
            return (
                f"⏱️ 学习会话已开始！\n\n"
                f"📌 会话 ID：`{session_uid[:16]}...`\n\n"
                f"完成后用 `/done <分钟数>` 记录学习时长。\n"
                f"提示：用 `/start <目标名>` 可以把会话绑定到学习目标。"
            )
        except Exception:
            logger.exception("Failed to start session for %s", user_id)
            return "开始学习会话失败，请稍后再试。"

    def _handle_done(self, user_id: str, args: str) -> str:
        """结束学习会话并记录时长。

        用法：/done <分钟数>
        """
        if not args.strip():
            return "用法：`/done <分钟数>`\n例：`/done 45` 表示学习了 45 分钟"
        try:
            minutes_str = args.strip().split()[0]
            focus_minutes = int(minutes_str)
            if focus_minutes < 0:
                return "学习时长不能为负数。"
        except (ValueError, IndexError):
            return f"时长格式错误：`{args.strip()}`\n用法：`/done <分钟数>`，例如 `/done 45`"

        session_uid = _active_sessions.get(user_id)
        if not session_uid:
            return (
                "没有找到进行中的学习会话。\n\n"
                "用 `/start` 开始一个新的学习会话，再用 `/done <分钟数>` 结束。"
            )
        try:
            success = self._study.end_session(
                session_uid=session_uid,
                focus_minutes=focus_minutes,
                items_reviewed=0,
            )
            if not success:
                # 会话可能已结束
                _active_sessions.pop(user_id, None)
                return "会话已结束或不存在，用 `/start` 开始新会话。"

            _active_sessions.pop(user_id, None)
            return (
                f"✅ 学习会话已记录！\n\n"
                f"⏱️ 专注时长：**{focus_minutes} 分钟**\n\n"
                f"用 `/stats` 查看今日累计统计，`/review` 查看待复习卡片。"
            )
        except Exception:
            logger.exception("Failed to end session %s for %s", session_uid, user_id)
            return "结束学习会话失败，请稍后再试。"
