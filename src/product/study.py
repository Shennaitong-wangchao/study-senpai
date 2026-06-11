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
        subject: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """列出用户的复习卡片。支持按 goal_uid、subject 过滤。"""
        clauses = ["user_id = ?", "status = ?"]
        params: list[Any] = [user_id, status]
        if goal_uid:
            clauses.append("goal_uid = ?")
            params.append(goal_uid)
        if subject is not None:
            clauses.append("subject = ?")
            params.append(subject)
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

    def batch_add_review_items(
        self,
        user_id: str,
        items: list[dict],
        goal_uid: str | None = None,
    ) -> dict:
        """批量添加复习卡片，在单个事务中完成。

        items 格式：[{"front": str, "back": str, "subject"?: str, "tags"?: list}, ...]

        跳过规则：
        - front 或 back 为空（None 或空字符串）
        - front 或 back 超过 2000 字符

        Returns:
            {added: N, skipped: M, errors: [str]}
        """
        MAX_FIELD_LEN = 2000
        added = 0
        skipped = 0
        errors: list[str] = []
        rows_to_insert: list[tuple] = []
        now = iso_utc_now()
        next_review_at = _add_days_iso(now, 1)

        for idx, item in enumerate(items, start=1):
            front = (item.get("front") or "").strip()
            back = (item.get("back") or "").strip()

            if not front or not back:
                errors.append(f"第 {idx} 项：front 或 back 为空")
                skipped += 1
                continue
            if len(front) > MAX_FIELD_LEN:
                errors.append(f"第 {idx} 项：front 超过 {MAX_FIELD_LEN} 字符限制")
                skipped += 1
                continue
            if len(back) > MAX_FIELD_LEN:
                errors.append(f"第 {idx} 项：back 超过 {MAX_FIELD_LEN} 字符限制")
                skipped += 1
                continue

            item_uid = f"item_{uuid.uuid4().hex}"
            subject = item.get("subject") or None
            tags = item.get("tags") or []
            effective_goal_uid = goal_uid  # 批量操作统一使用传入的 goal_uid

            rows_to_insert.append((
                item_uid,
                user_id,
                effective_goal_uid,
                front,
                back,
                subject,
                json_dumps(tags),
                next_review_at,
                json_dumps({}),
                now,
                now,
            ))

        # 单事务批量插入（executemany 内部自带事务+commit，保证原子性）
        if rows_to_insert:
            self.db.executemany(
                """
                INSERT INTO review_items (
                    item_uid, user_id, goal_uid, front, back, subject, tags_json,
                    ease_factor, interval_days, repetitions, next_review_at,
                    last_reviewed_at, status, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 2.5, 1, 0, ?, NULL, 'active', ?, ?, ?)
                """,
                rows_to_insert,
            )
            added = len(rows_to_insert)

        return {"added": added, "skipped": skipped, "errors": errors}

    def archive_review_item(self, item_uid: str) -> bool:
        """归档（停止复习）单张卡片，将 status 设为 'archived'。

        Returns:
            True 表示归档成功，False 表示卡片不存在。
        """
        cursor = self.db.execute(
            """
            UPDATE review_items
            SET status = 'archived', updated_at = ?
            WHERE item_uid = ?
            """,
            (iso_utc_now(), item_uid),
        )
        return (cursor.rowcount or 0) > 0

    def restore_review_item(self, item_uid: str) -> bool:
        """恢复已归档的卡片：将 status 重置为 'active'，next_review_at 设为明天。

        Returns:
            True 表示恢复成功，False 表示卡片不存在。
        """
        now = iso_utc_now()
        next_review_at = _add_days_iso(now, 1)
        cursor = self.db.execute(
            """
            UPDATE review_items
            SET status = 'active', next_review_at = ?, updated_at = ?
            WHERE item_uid = ?
            """,
            (next_review_at, now, item_uid),
        )
        return (cursor.rowcount or 0) > 0

    def batch_archive_by_subject(self, user_id: str, subject: str) -> int:
        """批量归档指定学科的所有活跃卡片。

        Returns:
            归档的卡片数量。
        """
        cursor = self.db.execute(
            """
            UPDATE review_items
            SET status = 'archived', updated_at = ?
            WHERE user_id = ? AND subject = ? AND status = 'active'
            """,
            (iso_utc_now(), user_id, subject),
        )
        return cursor.rowcount or 0

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

    def get_active_session(self, user_id: str) -> dict[str, Any] | None:
        """获取用户当前进行中的学习会话（ended_at IS NULL）。

        若存在多个未结束的会话，返回最近开始的那一个。
        不存在则返回 None。
        """
        row = self.db.fetchone(
            """
            SELECT * FROM study_sessions
            WHERE user_id = ? AND ended_at IS NULL
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        return self._session_from_row(row) if row else None

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

    def generate_study_plan(
        self,
        user_id: str,
        goal_uid: str,
        days_until_target: int | None = None,
    ) -> dict[str, Any]:
        """基于目标和剩余时间，生成每日学习计划建议（纯本地计算，不依赖 LLM）。

        计算规则：
        - urgency：
            None 或 > 90 天 → "low"
            31-90 天       → "medium"
            8-30 天        → "high"
            ≤ 7 天         → "critical"
        - daily_minutes：low=30, medium=45, high=60, critical=90
        - cards_per_day：min(20, max(5, due_today + 3))
        - focus_areas：取目标 subject 字段，若为空则给通用建议
        - weekly_checkpoints：按 urgency 给出 1-4 个里程碑

        Returns:
            包含以下键的 dict：
            - daily_minutes: 建议每日学习时长
            - cards_per_day: 建议每日复习卡片数
            - focus_areas: 建议重点领域列表
            - weekly_checkpoints: 每周里程碑列表
            - urgency: 紧迫程度 (low/medium/high/critical)
        """
        # 如果未传 days_until_target，尝试从目标的 target_date 字段自动计算
        effective_days = days_until_target
        if effective_days is None:
            goal = self._get_goal_by_uid(goal_uid)
            if goal and goal.get("target_date"):
                try:
                    target_dt = datetime.fromisoformat(goal["target_date"])
                    if target_dt.tzinfo is None:
                        target_dt = target_dt.replace(tzinfo=timezone.utc)
                    now_dt = datetime.now(timezone.utc)
                    effective_days = max(0, (target_dt - now_dt).days)
                except (ValueError, TypeError):
                    effective_days = None

        # 判断紧迫度
        if effective_days is None or effective_days > 90:
            urgency = "low"
        elif effective_days > 30:
            urgency = "medium"
        elif effective_days > 7:
            urgency = "high"
        else:
            urgency = "critical"

        # 每日推荐学习时长
        daily_minutes_map = {"low": 30, "medium": 45, "high": 60, "critical": 90}
        daily_minutes = daily_minutes_map[urgency]

        # 今日到期卡片数 → 每日推荐卡片数
        now = iso_utc_now()
        due_row = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM review_items
            WHERE user_id = ? AND goal_uid = ? AND status = 'active'
              AND (next_review_at IS NULL OR next_review_at <= ?)
            """,
            (user_id, goal_uid, now),
        )
        due_today = int(due_row["cnt"]) if due_row else 0
        cards_per_day = min(20, max(5, due_today + 3))

        # 重点领域：从目标 subject 字段推断
        goal = self._get_goal_by_uid(goal_uid)
        focus_areas: list[str] = []
        if goal:
            subject = goal.get("subject") or ""
            if subject:
                focus_areas = [subject]
        if not focus_areas:
            focus_areas = ["概念理解", "练习巩固", "错题复盘"]

        # 每周里程碑
        checkpoint_templates: dict[str, list[str]] = {
            "low": [
                "第1周：建立学习节奏，完成基础模块",
                "第2周：完成初级卡片复习",
                "第3周：攻克重点难点",
                "第4周：全面复盘，查漏补缺",
            ],
            "medium": [
                "第1周：快速过一遍所有知识点",
                "第2周：重点突破，强化薄弱环节",
                "第3周：模拟测试 + 错题整理",
            ],
            "high": [
                "第1-2天：梳理核心知识框架",
                "第3-5天：高频卡片全面复习",
                "第6-7天：模拟演练 + 查漏",
            ],
            "critical": [
                "今天：优先复习到期卡片",
                "明天：攻克最薄弱的知识点",
                "冲刺：保持专注，稳定发挥",
            ],
        }
        weekly_checkpoints = checkpoint_templates[urgency]

        return {
            "goal_uid": goal_uid,
            "user_id": user_id,
            "urgency": urgency,
            "days_until_target": effective_days,
            "daily_minutes": daily_minutes,
            "cards_per_day": cards_per_day,
            "focus_areas": focus_areas,
            "weekly_checkpoints": weekly_checkpoints,
            "computed_at": iso_utc_now(),
        }

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
        # 成就：连续学习天数里程碑（3/7/14/30/100 天，精确匹配）
        for milestone in (3, 7, 14, 30, 100):
            if streak_days == milestone:
                achievements.append(f"连续{milestone}天")
        # 成就：今日复习卡片里程碑（从高到低取第一个达标档位）
        for milestone in (50, 20, 10, 5):
            if reviewed_today >= milestone:
                achievements.append(f"完成{milestone}张复习")
                break
        # 成就：专注学习时长里程碑（从高到低取第一个达标档位）
        for milestone in (120, 60, 30):
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

    def generate_weekly_report(self, user_id: str, period_days: int = 7) -> dict[str, Any]:
        """生成学习周报（过去 N 天，默认 7 天；30 天时可用于月报）。

        Returns:
            {
                "period": {"start": "2026-06-05", "end": "2026-06-11"},
                "summary": {
                    "total_sessions": 5,
                    "total_focus_minutes": 225,
                    "total_cards_reviewed": 47,
                    "goals_progressed": 2,
                    "new_cards_added": 15,
                },
                "streak": {"current": 7, "longest_this_week": 7},
                "by_subject": [
                    {"subject": "数学", "cards_reviewed": 20, "focus_minutes": 90},
                    ...
                ],
                "highlights": ["连续7天学习", "本周新增15张卡片"],
                "next_week_due": 35,
                "trend": "improving",  # improving / stable / declining
            }
        """
        today = datetime.now(timezone.utc).date()
        start_date = today - timedelta(days=period_days - 1)
        end_date = today

        start_iso = datetime(
            start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc
        ).isoformat()
        # 结束时间取明天零点（即 today+1 天的零点），方便 < 比较
        end_exclusive_iso = datetime(
            (end_date + timedelta(days=1)).year,
            (end_date + timedelta(days=1)).month,
            (end_date + timedelta(days=1)).day,
            tzinfo=timezone.utc,
        ).isoformat()
        # 下周结束（7 天后）
        next_period_end_iso = datetime(
            (end_date + timedelta(days=8)).year,
            (end_date + timedelta(days=8)).month,
            (end_date + timedelta(days=8)).day,
            tzinfo=timezone.utc,
        ).isoformat()

        # ----- 本期会话汇总 -----
        period_sessions_row = self.db.fetchone(
            """
            SELECT COUNT(*) AS total_sessions,
                   COALESCE(SUM(focus_minutes), 0) AS total_focus_minutes,
                   COALESCE(SUM(items_reviewed), 0) AS total_cards_reviewed
            FROM study_sessions
            WHERE user_id = ? AND started_at >= ? AND started_at < ?
              AND ended_at IS NOT NULL
            """,
            (user_id, start_iso, end_exclusive_iso),
        )
        total_sessions = int(period_sessions_row["total_sessions"]) if period_sessions_row else 0
        total_focus_minutes = int(period_sessions_row["total_focus_minutes"]) if period_sessions_row else 0
        total_cards_reviewed = int(period_sessions_row["total_cards_reviewed"]) if period_sessions_row else 0

        # ----- 本期更新过进度的目标数 -----
        goals_progressed_row = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM study_goals
            WHERE user_id = ? AND updated_at >= ? AND updated_at < ?
            """,
            (user_id, start_iso, end_exclusive_iso),
        )
        goals_progressed = int(goals_progressed_row["cnt"]) if goals_progressed_row else 0

        # ----- 本期新增卡片数 -----
        new_cards_row = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM review_items
            WHERE user_id = ? AND created_at >= ? AND created_at < ?
            """,
            (user_id, start_iso, end_exclusive_iso),
        )
        new_cards_added = int(new_cards_row["cnt"]) if new_cards_row else 0

        # ----- 连续打卡天数（当前 streak）-----
        current_streak = self._compute_streak(user_id)

        # ----- 本期内最长连续打卡天数 -----
        study_dates_rows = self.db.fetchall(
            """
            SELECT DISTINCT DATE(started_at) AS study_date
            FROM study_sessions
            WHERE user_id = ? AND started_at >= ? AND started_at < ?
              AND ended_at IS NOT NULL
            ORDER BY study_date ASC
            """,
            (user_id, start_iso, end_exclusive_iso),
        )
        study_dates = []
        for row in study_dates_rows:
            try:
                study_dates.append(datetime.strptime(row["study_date"], "%Y-%m-%d").date())
            except (ValueError, TypeError):
                pass

        longest_streak_period = 0
        if study_dates:
            cur_run = 1
            best_run = 1
            for i in range(1, len(study_dates)):
                if study_dates[i] == study_dates[i - 1] + timedelta(days=1):
                    cur_run += 1
                    best_run = max(best_run, cur_run)
                else:
                    cur_run = 1
            longest_streak_period = best_run

        # ----- 按科目汇总：cards_reviewed（study_sessions 中的 items_reviewed 无法按科目拆分）
        # 用 review_items 的 last_reviewed_at 在本期内的记录按 subject 聚合
        subject_rows = self.db.fetchall(
            """
            SELECT COALESCE(subject, '未分类') AS subject,
                   COUNT(*) AS cards_reviewed
            FROM review_items
            WHERE user_id = ? AND last_reviewed_at >= ? AND last_reviewed_at < ?
            GROUP BY subject
            ORDER BY cards_reviewed DESC
            """,
            (user_id, start_iso, end_exclusive_iso),
        )

        # 同时从 study_sessions join goal/subject 获取各科目的 focus_minutes（按 goal_uid 分组）
        # 先取本期 sessions 的 goal_uid → focus_minutes 映射
        session_goal_rows = self.db.fetchall(
            """
            SELECT goal_uid, COALESCE(SUM(focus_minutes), 0) AS focus_minutes
            FROM study_sessions
            WHERE user_id = ? AND started_at >= ? AND started_at < ?
              AND ended_at IS NOT NULL AND goal_uid IS NOT NULL
            GROUP BY goal_uid
            """,
            (user_id, start_iso, end_exclusive_iso),
        )
        # goal_uid → subject 映射
        goal_subject_map: dict[str, str] = {}
        for sg_row in session_goal_rows:
            g_uid = sg_row["goal_uid"]
            if g_uid and g_uid not in goal_subject_map:
                goal_row = self.db.fetchone(
                    "SELECT subject FROM study_goals WHERE goal_uid = ? LIMIT 1",
                    (g_uid,),
                )
                if goal_row:
                    goal_subject_map[g_uid] = goal_row["subject"] or "未分类"

        # subject → focus_minutes 汇总
        subject_focus: dict[str, int] = {}
        for sg_row in session_goal_rows:
            g_uid = sg_row["goal_uid"]
            subj = goal_subject_map.get(g_uid, "未分类") if g_uid else "未分类"
            subject_focus[subj] = subject_focus.get(subj, 0) + int(sg_row["focus_minutes"])

        # 合并 subject_rows 和 subject_focus
        by_subject: list[dict] = []
        subject_cards: dict[str, int] = {row["subject"]: int(row["cards_reviewed"]) for row in subject_rows}
        all_subjects = set(subject_cards) | set(subject_focus)
        for subj in sorted(all_subjects, key=lambda s: subject_cards.get(s, 0), reverse=True):
            by_subject.append({
                "subject": subj,
                "cards_reviewed": subject_cards.get(subj, 0),
                "focus_minutes": subject_focus.get(subj, 0),
            })

        # ----- 下周到期卡片数 -----
        next_week_due_row = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM review_items
            WHERE user_id = ? AND status = 'active'
              AND next_review_at >= ? AND next_review_at < ?
            """,
            (user_id, end_exclusive_iso, next_period_end_iso),
        )
        next_week_due = int(next_week_due_row["cnt"]) if next_week_due_row else 0

        # ----- trend：与上一个同等时段比较 -----
        prev_start_iso = datetime(
            (start_date - timedelta(days=period_days)).year,
            (start_date - timedelta(days=period_days)).month,
            (start_date - timedelta(days=period_days)).day,
            tzinfo=timezone.utc,
        ).isoformat()
        prev_sessions_row = self.db.fetchone(
            """
            SELECT COALESCE(SUM(focus_minutes), 0) AS total_focus,
                   COALESCE(SUM(items_reviewed), 0) AS total_reviewed
            FROM study_sessions
            WHERE user_id = ? AND started_at >= ? AND started_at < ?
              AND ended_at IS NOT NULL
            """,
            (user_id, prev_start_iso, start_iso),
        )
        prev_focus = int(prev_sessions_row["total_focus"]) if prev_sessions_row else 0
        prev_reviewed = int(prev_sessions_row["total_reviewed"]) if prev_sessions_row else 0

        # 综合评分（时长 + 复习数量），与上期比较
        cur_score = total_focus_minutes + total_cards_reviewed
        prev_score = prev_focus + prev_reviewed

        if prev_score == 0:
            trend = "improving" if cur_score > 0 else "stable"
        elif cur_score >= prev_score * 1.05:
            trend = "improving"
        elif cur_score <= prev_score * 0.95:
            trend = "declining"
        else:
            trend = "stable"

        # ----- highlights -----
        highlights: list[str] = []
        if current_streak >= period_days:
            label = "7" if period_days == 7 else str(period_days)
            highlights.append(f"连续{label}天学习")
        elif current_streak >= 3:
            highlights.append(f"连续{current_streak}天学习")
        if new_cards_added > 0:
            label = "本周" if period_days == 7 else "本月"
            highlights.append(f"{label}新增{new_cards_added}张卡片")
        if total_focus_minutes >= 60:
            highlights.append(f"累计专注{total_focus_minutes}分钟")
        if total_cards_reviewed >= 20:
            highlights.append(f"共复习{total_cards_reviewed}张卡片")

        return {
            "period": {
                "start": start_date.strftime("%Y-%m-%d"),
                "end": end_date.strftime("%Y-%m-%d"),
                "days": period_days,
            },
            "summary": {
                "total_sessions": total_sessions,
                "total_focus_minutes": total_focus_minutes,
                "total_cards_reviewed": total_cards_reviewed,
                "goals_progressed": goals_progressed,
                "new_cards_added": new_cards_added,
            },
            "streak": {
                "current": current_streak,
                "longest_this_week": longest_streak_period,
            },
            "by_subject": by_subject,
            "highlights": highlights,
            "next_week_due": next_week_due,
            "trend": trend,
        }

    # -----------------------------------------------------------------------
    # Anki TSV 导入 / 导出
    # -----------------------------------------------------------------------

    def export_to_anki_tsv(self, user_id: str, goal_uid: str | None = None) -> str:
        """导出复习卡片为 Anki TSV 格式（front\tback\ttags）。

        每行格式：front<TAB>back<TAB>tag1 tag2 ...
        仅导出 status='active' 的卡片。
        """
        items = self.list_review_items(user_id, status="active", goal_uid=goal_uid, limit=10000)
        lines: list[str] = []
        for item in items:
            front = str(item.get("front") or "").replace("\t", " ").replace("\n", " ").replace("\r", " ")
            back = str(item.get("back") or "").replace("\t", " ").replace("\n", " ").replace("\r", " ")
            tags_list: list[str] = item.get("tags") or []
            tags_str = " ".join(str(t).replace(" ", "_") for t in tags_list if t)
            lines.append(f"{front}\t{back}\t{tags_str}")
        return "\n".join(lines)

    def import_from_anki_tsv(
        self,
        user_id: str,
        tsv_content: str,
        goal_uid: str | None = None,
    ) -> dict:
        """从 Anki TSV 内容导入复习卡片。

        每行格式：front<TAB>back 或 front<TAB>back<TAB>tags（空格分隔）
        跳过空行、注释行（# 开头）、格式错误行。

        安全限制：
        - 内容不超过 10MB
        - 单条 front/back 不超过 2000 字符
        - 最多导入 1000 条

        Returns:
            {imported: N, skipped: M, errors: [str]}
        """
        MAX_BYTES = 10 * 1024 * 1024  # 10MB
        MAX_ITEMS = 1000
        MAX_FIELD_LEN = 2000

        # 大小检查
        if len(tsv_content.encode("utf-8")) > MAX_BYTES:
            return {"imported": 0, "skipped": 0, "errors": ["内容超过 10MB 限制"]}

        imported = 0
        skipped = 0
        errors: list[str] = []

        for lineno, line in enumerate(tsv_content.splitlines(), start=1):
            raw = line.rstrip("\r\n")
            # 跳过空行和注释行
            if not raw.strip() or raw.lstrip().startswith("#"):
                skipped += 1
                continue
            # 达到上限
            if imported >= MAX_ITEMS:
                skipped += 1
                continue

            parts = raw.split("\t")
            if len(parts) < 2:
                errors.append(f"第 {lineno} 行：缺少 back 列（应为 front\\tback 格式）")
                skipped += 1
                continue

            front = parts[0].strip()
            back = parts[1].strip()
            tags_raw = parts[2].strip() if len(parts) >= 3 else ""

            if not front or not back:
                errors.append(f"第 {lineno} 行：front 或 back 为空")
                skipped += 1
                continue
            if len(front) > MAX_FIELD_LEN:
                errors.append(f"第 {lineno} 行：front 超过 {MAX_FIELD_LEN} 字符限制")
                skipped += 1
                continue
            if len(back) > MAX_FIELD_LEN:
                errors.append(f"第 {lineno} 行：back 超过 {MAX_FIELD_LEN} 字符限制")
                skipped += 1
                continue

            tags: list[str] = [t.replace("_", " ") for t in tags_raw.split() if t] if tags_raw else []

            try:
                self.add_review_item(
                    user_id=user_id,
                    front=front,
                    back=back,
                    goal_uid=goal_uid,
                    tags=tags,
                )
                imported += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"第 {lineno} 行：写入失败 — {exc}")
                skipped += 1

        return {"imported": imported, "skipped": skipped, "errors": errors}

    # -----------------------------------------------------------------------
    # 学习统计可视化数据
    # -----------------------------------------------------------------------

    def get_heatmap_data(self, user_id: str, days: int = 90) -> list[dict]:
        """返回过去 N 天的学习热力图数据（类似 GitHub contribution graph）。

        每条记录：{date: "2026-06-01", count: int, minutes: int}
        - count  = 当天已结束的学习会话数量（ended_at IS NOT NULL）
        - minutes = 当天总 focus_minutes
        """
        # 计算起始日期（UTC）
        today = datetime.now(timezone.utc).date()
        start_date = today - timedelta(days=days - 1)
        start_iso = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc).isoformat()

        rows = self.db.fetchall(
            """
            SELECT DATE(started_at) AS study_date,
                   COUNT(*) AS session_count,
                   COALESCE(SUM(focus_minutes), 0) AS total_minutes
            FROM study_sessions
            WHERE user_id = ?
              AND ended_at IS NOT NULL
              AND started_at >= ?
            GROUP BY DATE(started_at)
            ORDER BY study_date ASC
            """,
            (user_id, start_iso),
        )
        # 构建日期 → 数据的 lookup
        data_by_date: dict[str, dict] = {}
        for row in rows:
            data_by_date[row["study_date"]] = {
                "count": int(row["session_count"]),
                "minutes": int(row["total_minutes"]),
            }

        # 生成完整日期序列（N 天，无数据的日期填 0）
        result: list[dict] = []
        for i in range(days):
            d = start_date + timedelta(days=i)
            date_str = d.strftime("%Y-%m-%d")
            entry = data_by_date.get(date_str, {"count": 0, "minutes": 0})
            result.append({
                "date": date_str,
                "count": entry["count"],
                "minutes": entry["minutes"],
            })
        return result

    def get_subject_distribution(self, user_id: str) -> list[dict]:
        """返回复习卡片的学科分布。

        格式：[{subject: "数学", count: 15, mastered: 8}, ...]
        - count    = 该科目下 active 卡片总数
        - mastered = repetitions >= 3 的卡片数（视为已掌握）
        """
        rows = self.db.fetchall(
            """
            SELECT
                COALESCE(subject, '未分类') AS subject,
                COUNT(*) AS total_count,
                SUM(CASE WHEN repetitions >= 3 THEN 1 ELSE 0 END) AS mastered_count
            FROM review_items
            WHERE user_id = ? AND status = 'active'
            GROUP BY subject
            ORDER BY total_count DESC
            """,
            (user_id,),
        )
        return [
            {
                "subject": row["subject"],
                "count": int(row["total_count"]),
                "mastered": int(row["mastered_count"]),
            }
            for row in rows
        ]

    def list_sessions(
        self,
        user_id: str,
        goal_uid: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """列出学习会话历史，按开始时间倒序。"""
        if goal_uid:
            rows = self.db.fetchall(
                "SELECT * FROM study_sessions WHERE user_id = ? AND goal_uid = ? ORDER BY started_at DESC LIMIT ?",
                (user_id, goal_uid, limit),
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM study_sessions WHERE user_id = ? ORDER BY started_at DESC LIMIT ?",
                (user_id, limit),
            )
        return [self._session_from_row(r) for r in rows]

    # -----------------------------------------------------------------------
    # 成就系统
    # -----------------------------------------------------------------------

    ACHIEVEMENTS: list[dict] = [
        # Streak 成就
        {"id": "streak_3",   "name": "初学者",   "desc": "连续学习 3 天",    "icon": "🌱", "type": "streak",   "threshold": 3},
        {"id": "streak_7",   "name": "一周坚持", "desc": "连续学习 7 天",    "icon": "🔥", "type": "streak",   "threshold": 7},
        {"id": "streak_14",  "name": "两周习惯", "desc": "连续学习 14 天",   "icon": "⚡", "type": "streak",   "threshold": 14},
        {"id": "streak_30",  "name": "月度冠军", "desc": "连续学习 30 天",   "icon": "🏆", "type": "streak",   "threshold": 30},
        {"id": "streak_100", "name": "百日传说", "desc": "连续学习 100 天",  "icon": "👑", "type": "streak",   "threshold": 100},
        # 卡片成就
        {"id": "cards_10",   "name": "入门",     "desc": "掌握 10 张卡片",   "icon": "📖", "type": "mastered", "threshold": 10},
        {"id": "cards_50",   "name": "进步中",   "desc": "掌握 50 张卡片",   "icon": "📚", "type": "mastered", "threshold": 50},
        {"id": "cards_100",  "name": "百卡达人", "desc": "掌握 100 张卡片",  "icon": "🎓", "type": "mastered", "threshold": 100},
        {"id": "cards_500",  "name": "知识宝库", "desc": "掌握 500 张卡片",  "icon": "🌟", "type": "mastered", "threshold": 500},
        # 目标成就
        {"id": "goals_1",    "name": "定目标",   "desc": "完成第一个学习目标", "icon": "🎯", "type": "completed_goals", "threshold": 1},
        {"id": "goals_5",    "name": "多线并进", "desc": "完成 5 个学习目标", "icon": "🏅", "type": "completed_goals", "threshold": 5},
        # 时长成就
        {"id": "hours_10",   "name": "十小时",   "desc": "累计学习 10 小时", "icon": "⏰", "type": "total_hours", "threshold": 10},
        {"id": "hours_100",  "name": "百小时",   "desc": "累计学习 100 小时","icon": "🌈", "type": "total_hours", "threshold": 100},
    ]

    def get_achievements(self, user_id: str) -> list[dict]:
        """返回用户的成就列表（含是否已解锁）。"""
        stats = self.get_study_stats(user_id)
        streak = stats.get("streak_days", 0)
        mastered = stats.get("mastered_items", 0)

        # 已完成目标数
        completed_goals_row = self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM study_goals WHERE user_id = ? AND status = 'completed'",
            (user_id,),
        )
        completed_goals = int(completed_goals_row["cnt"]) if completed_goals_row else 0

        # 累计学习时长（分钟）
        hours_row = self.db.fetchone(
            "SELECT COALESCE(SUM(focus_minutes), 0) AS total FROM study_sessions WHERE user_id = ? AND ended_at IS NOT NULL",
            (user_id,),
        )
        total_hours = (int(hours_row["total"]) if hours_row else 0) / 60

        values = {
            "streak": streak,
            "mastered": mastered,
            "completed_goals": completed_goals,
            "total_hours": total_hours,
        }
        result = []
        for ach in self.ACHIEVEMENTS:
            unlocked = values.get(ach["type"], 0) >= ach["threshold"]
            result.append({**ach, "unlocked": unlocked, "current": values.get(ach["type"], 0)})
        return result

    # -----------------------------------------------------------------------
    # 日历导出（ICS 格式）
    # -----------------------------------------------------------------------

    def export_study_plan_ics(self, user_id: str, days_ahead: int = 14) -> str:
        """导出学习计划为 ICS 格式（可导入 Apple Calendar / Google Calendar）。

        包含：
        - 今日到期复习卡片（作为全天提醒事项）
        - 未来 days_ahead 天内的预计到期卡片
        - 学习目标截止日期（如果有）

        返回 ICS 格式字符串。
        """
        try:
            import icalendar
            from datetime import date as _date
        except ImportError:
            raise RuntimeError("icalendar 库未安装，请运行：pip install icalendar>=5.0.12")

        now = datetime.now(timezone.utc)
        cal = icalendar.Calendar()
        cal.add("prodid", "-//Study Senpai//studysenpai//CN")
        cal.add("version", "2.0")
        cal.add("x-wr-calname", "Study Senpai 学习计划")
        cal.add("x-wr-timezone", "UTC")

        # 到期复习卡片（按日期分组）
        end_date = now + timedelta(days=days_ahead)
        rows = self.db.fetchall(
            """
            SELECT item_uid, front, subject, next_review_at
            FROM review_items
            WHERE user_id = ? AND status = 'active'
              AND next_review_at <= ?
            ORDER BY next_review_at
            """,
            (user_id, end_date.isoformat()),
        )
        # 按日期分组
        from collections import defaultdict
        daily_cards: dict = defaultdict(list)
        for row in rows:
            review_dt_str = row["next_review_at"]
            try:
                review_dt = datetime.fromisoformat(review_dt_str)
                day_str = review_dt.date().isoformat()
            except (ValueError, AttributeError):
                day_str = now.date().isoformat()
            daily_cards[day_str].append(row["front"])

        for day_str, fronts in sorted(daily_cards.items()):
            event = icalendar.Event()
            try:
                event_date = _date.fromisoformat(day_str)
            except ValueError:
                continue
            summary = f"📚 复习提醒：{len(fronts)} 张卡片"
            description = "\n".join(f"• {f[:80]}" for f in fronts[:10])
            if len(fronts) > 10:
                description += f"\n...共 {len(fronts)} 张"
            event.add("summary", summary)
            event.add("dtstart", event_date)
            event.add("dtend", event_date + timedelta(days=1))
            event.add("description", description)
            event.add("x-study-senpai-type", "review_reminder")
            cal.add_component(event)

        # 学习目标截止日期
        goals = self.list_goals(user_id)
        for goal in goals:
            if not goal.get("target_date"):
                continue
            try:
                target = _date.fromisoformat(goal["target_date"][:10])
            except (ValueError, TypeError):
                continue
            event = icalendar.Event()
            event.add("summary", f"🎯 目标截止：{goal['title']}")
            event.add("dtstart", target)
            event.add("dtend", target + timedelta(days=1))
            event.add("description", f"学习目标：{goal['title']}\n学科：{goal.get('subject', '未指定')}\n进度：{goal.get('progress_pct', 0)}%")
            event.add("x-study-senpai-type", "goal_deadline")
            cal.add_component(event)

        return cal.to_ical().decode("utf-8")

