"""学习目标追踪与间隔复习服务（Study Senpai 核心）。

包含：
- StudyService：目标 CRUD、复习卡片管理、学习会话、统计
- sm2_update：SuperMemo 2 间隔复习算法
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from src.db.database import Database
from src.utils.json_utils import json_dumps, json_loads
from src.utils.time_utils import iso_utc_now


# ---------------------------------------------------------------------------
# SM-2 算法
# ---------------------------------------------------------------------------

def sm2_update(ease_factor: float, interval: int, repetitions: int, quality: int) -> tuple[float, int, int]:
    """SuperMemo 2 间隔复习算法。

    quality 含义：
        0 = 完全忘记
        1 = 记错了
        2 = 挣扎记住
        3 = 记住了（勉强通过）
        4 = 轻松记住
        5 = 完美回忆

    Returns:
        (新 ease_factor, 新 interval_days, 新 repetitions)
    """
    if quality < 3:
        # 记忆失败：重置进度
        repetitions = 0
        interval = 1
    else:
        # 记忆成功：按重复次数决定间隔
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = round(interval * ease_factor)
        repetitions += 1

    # 更新难度系数，最小不低于 1.3
    ease_factor = max(1.3, ease_factor + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    return ease_factor, interval, repetitions


def _add_days_iso(base_iso: str, days: int) -> str:
    """给 ISO8601 时间戳加上若干天，返回 ISO8601 字符串。"""
    dt = datetime.fromisoformat(base_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + timedelta(days=days)).isoformat()


def _today_iso() -> str:
    """返回今天 UTC 日期的零点 ISO8601 字符串（用于到期判断）。"""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# StudyService
# ---------------------------------------------------------------------------

class StudyService:
    """学习目标追踪与间隔复习业务逻辑层。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    # -----------------------------------------------------------------------
    # 学习目标（study_goals）
    # -----------------------------------------------------------------------

    def create_goal(
        self,
        user_id: str,
        conv_id: str,
        title: str,
        subject: str | None = None,
        target_date: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """创建一个新的学习目标，返回完整目标 dict。"""
        now = iso_utc_now()
        goal_uid = f"goal_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO study_goals (
                goal_uid, user_id, conversation_id, title, description, subject,
                target_date, status, progress_pct, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?, ?)
            """,
            (
                goal_uid,
                user_id,
                conv_id,
                title,
                description,
                subject,
                target_date,
                json_dumps(metadata or {}),
                now,
                now,
            ),
        )
        result = self._get_goal_by_uid(goal_uid)
        if result is None:
            raise RuntimeError("study_goal insert failed")
        return result

    def list_goals(self, user_id: str, status: str = "active") -> list[dict[str, Any]]:
        """列出用户的学习目标，按更新时间倒序。"""
        rows = self.db.fetchall(
            """
            SELECT * FROM study_goals
            WHERE user_id = ? AND status = ?
            ORDER BY updated_at DESC
            """,
            (user_id, status),
        )
        return [self._goal_from_row(row) for row in rows]

    def get_goal(self, goal_uid: str) -> dict[str, Any] | None:
        """按 UID 获取单个目标。"""
        return self._get_goal_by_uid(goal_uid)

    def update_goal_progress(self, goal_uid: str, progress_pct: int) -> bool:
        """更新目标进度（0-100），自动 clamp。"""
        clamped = max(0, min(100, progress_pct))
        cursor = self.db.execute(
            """
            UPDATE study_goals
            SET progress_pct = ?, updated_at = ?
            WHERE goal_uid = ?
            """,
            (clamped, iso_utc_now(), goal_uid),
        )
        return (cursor.rowcount or 0) > 0

    def update_goal_status(self, goal_uid: str, status: str) -> bool:
        """更新目标状态（active/completed/paused/archived）。"""
        allowed = {"active", "completed", "paused", "archived"}
        if status not in allowed:
            raise ValueError(f"不合法的 status：{status!r}，允许值：{allowed}")
        cursor = self.db.execute(
            """
            UPDATE study_goals
            SET status = ?, updated_at = ?
            WHERE goal_uid = ?
            """,
            (status, iso_utc_now(), goal_uid),
        )
        return (cursor.rowcount or 0) > 0

    def update_goal(self, goal_uid: str, fields: dict[str, Any]) -> bool:
        """通用目标字段更新（允许字段白名单控制）。"""
        allowed = {"title", "description", "subject", "target_date", "status", "progress_pct", "metadata_json"}
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            if key == "metadata_json":
                params.append(json_dumps(value))
            elif key == "progress_pct":
                params.append(max(0, min(100, int(value))))
            else:
                params.append(value)
        if not assignments:
            return False
        assignments.append("updated_at = ?")
        params.append(iso_utc_now())
        params.append(goal_uid)
        cursor = self.db.execute(
            f"UPDATE study_goals SET {', '.join(assignments)} WHERE goal_uid = ?",
            params,
        )
        return (cursor.rowcount or 0) > 0

    # -----------------------------------------------------------------------
    # 复习卡片（review_items）
    # -----------------------------------------------------------------------

    def add_review_item(
        self,
        user_id: str,
        front: str,
        back: str,
        subject: str | None = None,
        goal_uid: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """添加一张复习卡片，初始化 SM-2 参数，设置明天到期。"""
        now = iso_utc_now()
        item_uid = f"item_{uuid.uuid4().hex}"
        next_review_at = _add_days_iso(now, 1)  # 默认明天第一次复习
        self.db.execute(
            """
            INSERT INTO review_items (
                item_uid, user_id, goal_uid, front, back, subject, tags_json,
                ease_factor, interval_days, repetitions, next_review_at,
                last_reviewed_at, status, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 2.5, 1, 0, ?, NULL, 'active', ?, ?, ?)
            """,
            (
                item_uid,
                user_id,
                goal_uid,
                front,
                back,
                subject,
                json_dumps(tags or []),
                next_review_at,
                json_dumps(metadata or {}),
                now,
                now,
            ),
        )
        result = self._get_item_by_uid(item_uid)
        if result is None:
            raise RuntimeError("review_item insert failed")
        return result

    def get_due_items(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """获取到期（next_review_at <= 现在）且 active 的复习卡片。"""
        now = iso_utc_now()
        rows = self.db.fetchall(
            """
            SELECT * FROM review_items
            WHERE user_id = ? AND status = 'active'
              AND (next_review_at IS NULL OR next_review_at <= ?)
            ORDER BY next_review_at ASC, created_at ASC
            LIMIT ?
            """,
            (user_id, now, limit),
        )
        return [self._item_from_row(row) for row in rows]

    def record_review_result(self, item_uid: str, quality: int) -> dict[str, Any] | None:
        """记录一次复习结果（quality 0-5），更新 SM-2 参数。

        Returns:
            更新后的 review_item dict，或 None（item 不存在）。
        """
        if quality < 0 or quality > 5:
            raise ValueError(f"quality 必须在 0-5 之间，收到：{quality}")

        row = self.db.fetchone(
            "SELECT * FROM review_items WHERE item_uid = ? LIMIT 1",
            (item_uid,),
        )
        if row is None:
            return None

        new_ef, new_interval, new_reps = sm2_update(
            ease_factor=float(row["ease_factor"]),
            interval=int(row["interval_days"]),
            repetitions=int(row["repetitions"]),
            quality=quality,
        )
        now = iso_utc_now()
        next_review_at = _add_days_iso(now, new_interval)
        self.db.execute(
            """
            UPDATE review_items
            SET ease_factor = ?, interval_days = ?, repetitions = ?,
                next_review_at = ?, last_reviewed_at = ?, updated_at = ?
            WHERE item_uid = ?
            """,
            (new_ef, new_interval, new_reps, next_review_at, now, now, item_uid),
        )
        return self._get_item_by_uid(item_uid)

    def list_review_items(
        self,
        user_id: str,
        status: str = "active",
        goal_uid: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """列出用户的复习卡片。"""
        clauses = ["user_id = ?", "status = ?"]
        params: list[Any] = [user_id, status]
        if goal_uid:
            clauses.append("goal_uid = ?")
            params.append(goal_uid)
        params.append(limit)
        rows = self.db.fetchall(
            f"""
            SELECT * FROM review_items
            WHERE {' AND '.join(clauses)}
            ORDER BY next_review_at ASC, created_at DESC
            LIMIT ?
            """,
            params,
        )
        return [self._item_from_row(row) for row in rows]

    # -----------------------------------------------------------------------
    # 学习会话（study_sessions）
    # -----------------------------------------------------------------------

    def start_session(self, user_id: str, goal_uid: str | None = None) -> str:
        """开始一次学习会话，返回 session_uid。"""
        now = iso_utc_now()
        session_uid = f"sess_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO study_sessions (
                session_uid, user_id, goal_uid, started_at, ended_at,
                focus_minutes, items_reviewed, notes, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, NULL, 0, 0, NULL, '{}', ?)
            """,
            (session_uid, user_id, goal_uid, now, now),
        )
        return session_uid

    def end_session(
        self,
        session_uid: str,
        focus_minutes: int,
        items_reviewed: int,
        notes: str | None = None,
    ) -> bool:
        """结束学习会话，记录专注时长和复习数量。"""
        now = iso_utc_now()
        cursor = self.db.execute(
            """
            UPDATE study_sessions
            SET ended_at = ?, focus_minutes = ?, items_reviewed = ?, notes = ?
            WHERE session_uid = ? AND ended_at IS NULL
            """,
            (now, max(0, focus_minutes), max(0, items_reviewed), notes, session_uid),
        )
        return (cursor.rowcount or 0) > 0

    def get_session(self, session_uid: str) -> dict[str, Any] | None:
        """按 UID 获取学习会话。"""
        row = self.db.fetchone(
            "SELECT * FROM study_sessions WHERE session_uid = ? LIMIT 1",
            (session_uid,),
        )
        return self._session_from_row(row) if row else None

    # -----------------------------------------------------------------------
    # 统计
    # -----------------------------------------------------------------------

    def generate_daily_summary(self, user_id: str) -> dict[str, Any]:
        """生成当日学习摘要（纯本地计算，不依赖 LLM）。

        Returns:
            dict 包含：
            - reviewed_today: 今日复习卡片数（来自 study_sessions.items_reviewed 之和）
            - goals_updated: 今日更新目标数（updated_at 在今天的目标）
            - streak_days: 连续学习天数
            - due_tomorrow: 明日到期卡片数
            - session_minutes: 今日学习时长（分钟）
            - achievements: 成就列表（如 "连续7天"、"完成10张复习" 等）
        """
        now = iso_utc_now()
        today_start = _today_iso()
        # 明天开始时间 = 今天零点 + 1天，明天结束 = 后天零点
        today_dt = datetime.fromisoformat(today_start)
        if today_dt.tzinfo is None:
            today_dt = today_dt.replace(tzinfo=timezone.utc)
        tomorrow_start = (today_dt + timedelta(days=1)).isoformat()
        day_after_start = (today_dt + timedelta(days=2)).isoformat()

        # 今日复习卡片数 & 学习时长（从 study_sessions 汇总）
        sessions_row = self.db.fetchone(
            """
            SELECT COALESCE(SUM(items_reviewed), 0) AS total_reviewed,
                   COALESCE(SUM(focus_minutes), 0) AS total_minutes
            FROM study_sessions
            WHERE user_id = ? AND started_at >= ? AND ended_at IS NOT NULL
            """,
            (user_id, today_start),
        )
        reviewed_today = int(sessions_row["total_reviewed"]) if sessions_row else 0
        session_minutes = int(sessions_row["total_minutes"]) if sessions_row else 0

        # 今日更新目标数（updated_at 在今天范围内，排除刚创建的）
        goals_updated_row = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM study_goals
            WHERE user_id = ? AND updated_at >= ? AND updated_at < ?
            """,
            (user_id, today_start, tomorrow_start),
        )
        goals_updated = int(goals_updated_row["cnt"]) if goals_updated_row else 0

        # 连续打卡天数
        streak_days = self._compute_streak(user_id)

        # 明日到期卡片数（next_review_at 在 [明天零点, 后天零点) 区间）
        due_tomorrow_row = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM review_items
            WHERE user_id = ? AND status = 'active'
              AND next_review_at >= ? AND next_review_at < ?
            """,
            (user_id, tomorrow_start, day_after_start),
        )
        due_tomorrow = int(due_tomorrow_row["cnt"]) if due_tomorrow_row else 0

        # 成就计算
        achievements: list[str] = []
        # 成就：连续学习天数里程碑（3/7/14/30/100 天）
        for milestone in (3, 7, 14, 30, 100):
            if streak_days == milestone:
                achievements.append(f"连续{milestone}天")
        # 成就：今日复习卡片里程碑（5/10/20/50 张）
        for milestone in (5, 10, 20, 50):
            if reviewed_today >= milestone:
                achievements.append(f"完成{milestone}张复习")
                break  # 只取最高档
        # 成就：专注学习时长里程碑（30/60/120 分钟）
        for milestone in (30, 60, 120):
            if session_minutes >= milestone:
                achievements.append(f"专注{milestone}分钟")
                break
        # 成就：今日更新目标
        if goals_updated > 0:
            achievements.append(f"更新{goals_updated}个目标")

        return {
            "user_id": user_id,
            "reviewed_today": reviewed_today,
            "goals_updated": goals_updated,
            "streak_days": streak_days,
            "due_tomorrow": due_tomorrow,
            "session_minutes": session_minutes,
            "achievements": achievements,
            "computed_at": now,
        }

    def get_review_summary_text(self, user_id: str) -> str:
        """生成人类可读的学习摘要文本（供 AI 发消息或 Dashboard 展示）。

        Returns:
            可直接展示的文字摘要字符串。
        """
        s = self.generate_daily_summary(user_id)
        lines: list[str] = []

        # 标题行
        lines.append("📚 今日学习摘要")

        # 核心数字
        if s["session_minutes"] > 0:
            lines.append(f"• 学习时长：{s['session_minutes']} 分钟")
        if s["reviewed_today"] > 0:
            lines.append(f"• 复习卡片：{s['reviewed_today']} 张")
        if s["goals_updated"] > 0:
            lines.append(f"• 更新目标：{s['goals_updated']} 个")

        # 连续天数
        if s["streak_days"] > 0:
            lines.append(f"• 连续打卡：{s['streak_days']} 天 🔥")
        else:
            lines.append("• 今天还没有完成任何学习会话")

        # 明日预告
        if s["due_tomorrow"] > 0:
            lines.append(f"• 明日待复习：{s['due_tomorrow']} 张")

        # 成就
        if s["achievements"]:
            lines.append("🏆 成就：" + "、".join(s["achievements"]))

        return "\n".join(lines)

    def get_study_stats(self, user_id: str) -> dict[str, Any]:
        """返回用户的学习统计概览：连续打卡天数、卡片总数、今日到期等。"""
        now = iso_utc_now()
        today_start = _today_iso()

        # 今日到期复习数
        due_today_row = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM review_items
            WHERE user_id = ? AND status = 'active'
              AND (next_review_at IS NULL OR next_review_at <= ?)
            """,
            (user_id, now),
        )
        due_today = int(due_today_row["cnt"]) if due_today_row else 0

        # 卡片总数（active）
        total_items_row = self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM review_items WHERE user_id = ? AND status = 'active'",
            (user_id,),
        )
        total_items = int(total_items_row["cnt"]) if total_items_row else 0

        # 活跃目标数
        active_goals_row = self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM study_goals WHERE user_id = ? AND status = 'active'",
            (user_id,),
        )
        active_goals = int(active_goals_row["cnt"]) if active_goals_row else 0

        # 今日已完成会话次数（有 ended_at）
        sessions_today_row = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt, COALESCE(SUM(focus_minutes), 0) AS total_focus,
                   COALESCE(SUM(items_reviewed), 0) AS total_reviewed
            FROM study_sessions
            WHERE user_id = ? AND started_at >= ? AND ended_at IS NOT NULL
            """,
            (user_id, today_start),
        )
        sessions_today = int(sessions_today_row["cnt"]) if sessions_today_row else 0
        focus_today = int(sessions_today_row["total_focus"]) if sessions_today_row else 0
        reviewed_today = int(sessions_today_row["total_reviewed"]) if sessions_today_row else 0

        # 连续打卡天数：连续有学习会话的天数
        streak = self._compute_streak(user_id)

        return {
            "user_id": user_id,
            "streak_days": streak,
            "total_review_items": total_items,
            "active_goals": active_goals,
            "due_today": due_today,
            "sessions_today": sessions_today,
            "focus_minutes_today": focus_today,
            "items_reviewed_today": reviewed_today,
            "computed_at": now,
        }

    def _compute_streak(self, user_id: str) -> int:
        """计算连续学习天数（有 ended_at 的会话）。"""
        rows = self.db.fetchall(
            """
            SELECT DISTINCT DATE(started_at) AS study_date
            FROM study_sessions
            WHERE user_id = ? AND ended_at IS NOT NULL
            ORDER BY study_date DESC
            LIMIT 365
            """,
            (user_id,),
        )
        if not rows:
            return 0

        today = datetime.now(timezone.utc).date()
        streak = 0
        expected = today

        for row in rows:
            date_str = row["study_date"]
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                break
            # 今天或昨天开始算连续
            if streak == 0 and d < expected - timedelta(days=1):
                break
            if d == expected or (streak == 0 and d == expected - timedelta(days=1)):
                streak += 1
                expected = d - timedelta(days=1)
            elif d == expected:
                streak += 1
                expected = d - timedelta(days=1)
            else:
                break

        return streak

    # -----------------------------------------------------------------------
    # 私有辅助方法
    # -----------------------------------------------------------------------

    def _get_goal_by_uid(self, goal_uid: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM study_goals WHERE goal_uid = ? LIMIT 1",
            (goal_uid,),
        )
        return self._goal_from_row(row) if row else None

    def _get_item_by_uid(self, item_uid: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM review_items WHERE item_uid = ? LIMIT 1",
            (item_uid,),
        )
        return self._item_from_row(row) if row else None

    def _goal_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "goal_uid": row["goal_uid"],
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "title": row["title"],
            "description": row["description"],
            "subject": row["subject"],
            "target_date": row["target_date"],
            "status": row["status"],
            "progress_pct": int(row["progress_pct"]),
            "metadata": json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _item_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "item_uid": row["item_uid"],
            "user_id": row["user_id"],
            "goal_uid": row["goal_uid"],
            "front": row["front"],
            "back": row["back"],
            "subject": row["subject"],
            "tags": json_loads(row["tags_json"], []),
            "ease_factor": float(row["ease_factor"]),
            "interval_days": int(row["interval_days"]),
            "repetitions": int(row["repetitions"]),
            "next_review_at": row["next_review_at"],
            "last_reviewed_at": row["last_reviewed_at"],
            "status": row["status"],
            "metadata": json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _session_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "session_uid": row["session_uid"],
            "user_id": row["user_id"],
            "goal_uid": row["goal_uid"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "focus_minutes": int(row["focus_minutes"]),
            "items_reviewed": int(row["items_reviewed"]),
            "notes": row["notes"],
            "metadata": json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
        }
