"""每日学习摘要功能测试。

覆盖：
- generate_daily_summary 返回正确字段和类型
- reviewed_today / session_minutes 来自今日已完成的学习会话
- goals_updated 来自今日更新的目标
- streak_days 连续学习天数计算
- due_tomorrow 明日到期卡片数
- achievements 触发条件（连续天数、复习数量、专注时长、目标更新）
- get_review_summary_text 生成人类可读文本
- 无学习数据时各字段均为零/空
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from src.db.database import Database
from src.product.study import StudyService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def database(tmp_path) -> Iterator[Database]:
    db = Database(str(tmp_path / "summary_test.sqlite3"))
    db.initialize()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def study(database: Database) -> StudyService:
    return StudyService(db=database)


def _iso_past(days: int = 0, hours: int = 0) -> str:
    """返回 N 天/小时前的 ISO8601 字符串（UTC）。"""
    dt = datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
    return dt.isoformat()


def _iso_tomorrow_midday() -> str:
    """返回明天中午的 ISO8601 字符串（UTC）。"""
    tomorrow = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1, hours=12)
    return tomorrow.isoformat()


# ---------------------------------------------------------------------------
# 基础字段测试
# ---------------------------------------------------------------------------

class TestGenerateDailySummaryFields:
    def test_returns_required_fields(self, study: StudyService):
        """generate_daily_summary 必须包含所有必填字段。"""
        summary = study.generate_daily_summary("user-1")
        required = {
            "user_id",
            "reviewed_today",
            "goals_updated",
            "streak_days",
            "due_tomorrow",
            "session_minutes",
            "achievements",
            "computed_at",
        }
        assert required.issubset(set(summary.keys())), f"缺少字段：{required - set(summary.keys())}"

    def test_empty_data_all_zeros(self, study: StudyService):
        """无任何学习数据时，所有计数字段应为 0，成就列表为空。"""
        s = study.generate_daily_summary("user-no-data")
        assert s["reviewed_today"] == 0
        assert s["goals_updated"] == 0
        assert s["streak_days"] == 0
        assert s["due_tomorrow"] == 0
        assert s["session_minutes"] == 0
        assert s["achievements"] == []

    def test_user_id_in_result(self, study: StudyService):
        """返回的 user_id 字段与传入一致。"""
        s = study.generate_daily_summary("user-xyz")
        assert s["user_id"] == "user-xyz"

    def test_field_types(self, study: StudyService):
        """所有数值字段应为 int，achievements 应为 list。"""
        s = study.generate_daily_summary("user-1")
        assert isinstance(s["reviewed_today"], int)
        assert isinstance(s["goals_updated"], int)
        assert isinstance(s["streak_days"], int)
        assert isinstance(s["due_tomorrow"], int)
        assert isinstance(s["session_minutes"], int)
        assert isinstance(s["achievements"], list)


# ---------------------------------------------------------------------------
# reviewed_today / session_minutes
# ---------------------------------------------------------------------------

class TestReviewedTodayAndMinutes:
    def test_counts_completed_sessions_today(self, study: StudyService):
        """只统计今日已完成（ended_at 不为 NULL）的会话。"""
        sess = study.start_session("user-1")
        study.end_session(sess, focus_minutes=45, items_reviewed=8)
        s = study.generate_daily_summary("user-1")
        assert s["reviewed_today"] == 8
        assert s["session_minutes"] == 45

    def test_multiple_sessions_aggregated(self, study: StudyService):
        """多个今日会话应累加。"""
        s1 = study.start_session("user-1")
        study.end_session(s1, focus_minutes=20, items_reviewed=5)
        s2 = study.start_session("user-1")
        study.end_session(s2, focus_minutes=30, items_reviewed=10)
        s = study.generate_daily_summary("user-1")
        assert s["reviewed_today"] == 15
        assert s["session_minutes"] == 50

    def test_incomplete_session_not_counted(self, study: StudyService):
        """未结束的会话（ended_at 为 NULL）不计入统计。"""
        # 未调用 end_session，session 的 ended_at 为 NULL
        study.start_session("user-1")
        s = study.generate_daily_summary("user-1")
        assert s["reviewed_today"] == 0
        assert s["session_minutes"] == 0

    def test_past_sessions_not_counted(self, study: StudyService):
        """昨天或更早的会话不应计入今日统计。"""
        sess = study.start_session("user-1")
        # 将 started_at 改为 2 天前
        past = _iso_past(days=2)
        study.db.execute(
            "UPDATE study_sessions SET started_at = ?, ended_at = ?, focus_minutes = 30, items_reviewed = 5 WHERE session_uid = ?",
            (past, past, sess),
        )
        s = study.generate_daily_summary("user-1")
        assert s["reviewed_today"] == 0
        assert s["session_minutes"] == 0


# ---------------------------------------------------------------------------
# goals_updated
# ---------------------------------------------------------------------------

class TestGoalsUpdated:
    def test_goals_updated_today(self, study: StudyService):
        """今日更新的目标应被统计。"""
        goal = study.create_goal("user-1", "conv-1", "学习目标")
        # create_goal 会把 updated_at 设为当前时间，因此 goals_updated >= 1
        s = study.generate_daily_summary("user-1")
        assert s["goals_updated"] >= 1

    def test_old_goals_not_counted(self, study: StudyService):
        """把 updated_at 改为昨天，就不应计入今日统计。"""
        goal = study.create_goal("user-1", "conv-1", "旧目标")
        yesterday = _iso_past(days=1)
        study.db.execute(
            "UPDATE study_goals SET updated_at = ? WHERE goal_uid = ?",
            (yesterday, goal["goal_uid"]),
        )
        s = study.generate_daily_summary("user-1")
        assert s["goals_updated"] == 0

    def test_user_isolation_goals(self, study: StudyService):
        """不同用户的目标更新互不影响。"""
        study.create_goal("user-1", "conv-1", "用户1目标")
        study.create_goal("user-2", "conv-1", "用户2目标")
        s1 = study.generate_daily_summary("user-1")
        s2 = study.generate_daily_summary("user-2")
        assert s1["goals_updated"] >= 1
        assert s2["goals_updated"] >= 1
        # 两者不会相互干扰
        assert s1["goals_updated"] == 1
        assert s2["goals_updated"] == 1


# ---------------------------------------------------------------------------
# streak_days（连续学习天数）
# ---------------------------------------------------------------------------

class TestStreakDays:
    def test_no_sessions_streak_zero(self, study: StudyService):
        """没有任何会话时，streak 为 0。"""
        s = study.generate_daily_summary("user-streak")
        assert s["streak_days"] == 0

    def test_today_session_streak_one(self, study: StudyService):
        """今天有完成的会话，streak 至少为 1。"""
        sess = study.start_session("user-1")
        study.end_session(sess, focus_minutes=10, items_reviewed=2)
        s = study.generate_daily_summary("user-1")
        assert s["streak_days"] >= 1

    def test_consecutive_days_streak(self, study: StudyService):
        """连续 3 天有会话，streak 应为 3。"""
        for days_ago in (2, 1, 0):
            sess = study.start_session("user-streak3")
            dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
            dt_iso = dt.isoformat()
            study.db.execute(
                "UPDATE study_sessions SET started_at = ?, ended_at = ?, focus_minutes = 10, items_reviewed = 1 WHERE session_uid = ?",
                (dt_iso, dt_iso, sess),
            )
        s = study.generate_daily_summary("user-streak3")
        assert s["streak_days"] == 3

    def test_broken_streak_resets(self, study: StudyService):
        """中断了一天再今天复习，streak 应为 1（不是从上上次算起）。"""
        # 3 天前和今天有学习，昨天没有
        for days_ago in (3, 0):
            sess = study.start_session("user-broken")
            dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
            dt_iso = dt.isoformat()
            study.db.execute(
                "UPDATE study_sessions SET started_at = ?, ended_at = ?, focus_minutes = 10, items_reviewed = 1 WHERE session_uid = ?",
                (dt_iso, dt_iso, sess),
            )
        s = study.generate_daily_summary("user-broken")
        # 昨天没有学习，连续天数应为 1（仅今天）
        assert s["streak_days"] == 1


# ---------------------------------------------------------------------------
# due_tomorrow（明日到期卡片数）
# ---------------------------------------------------------------------------

class TestDueTomorrow:
    def test_no_items_due_tomorrow(self, study: StudyService):
        """没有卡片时 due_tomorrow 为 0。"""
        s = study.generate_daily_summary("user-1")
        assert s["due_tomorrow"] == 0

    def test_item_due_tomorrow_counted(self, study: StudyService):
        """将 next_review_at 设为明天，应该计入 due_tomorrow。"""
        item = study.add_review_item(user_id="user-1", front="Q", back="A")
        tomorrow = _iso_tomorrow_midday()
        study.db.execute(
            "UPDATE review_items SET next_review_at = ? WHERE item_uid = ?",
            (tomorrow, item["item_uid"]),
        )
        s = study.generate_daily_summary("user-1")
        assert s["due_tomorrow"] == 1

    def test_item_due_today_not_counted_as_tomorrow(self, study: StudyService):
        """今天到期的卡片不算在 due_tomorrow。"""
        item = study.add_review_item(user_id="user-1", front="Q", back="A")
        now_past = _iso_past(hours=1)  # 1 小时前到期
        study.db.execute(
            "UPDATE review_items SET next_review_at = ? WHERE item_uid = ?",
            (now_past, item["item_uid"]),
        )
        s = study.generate_daily_summary("user-1")
        assert s["due_tomorrow"] == 0

    def test_item_due_day_after_tomorrow_not_counted(self, study: StudyService):
        """后天到期的卡片不算在 due_tomorrow。"""
        item = study.add_review_item(user_id="user-1", front="Q", back="A")
        day_after = (datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0) + timedelta(days=2)).isoformat()
        study.db.execute(
            "UPDATE review_items SET next_review_at = ? WHERE item_uid = ?",
            (day_after, item["item_uid"]),
        )
        s = study.generate_daily_summary("user-1")
        assert s["due_tomorrow"] == 0

    def test_multiple_items_due_tomorrow(self, study: StudyService):
        """多张明日到期的卡片应全部计入。"""
        tomorrow = _iso_tomorrow_midday()
        for i in range(3):
            item = study.add_review_item(user_id="user-1", front=f"Q{i}", back=f"A{i}")
            study.db.execute(
                "UPDATE review_items SET next_review_at = ? WHERE item_uid = ?",
                (tomorrow, item["item_uid"]),
            )
        s = study.generate_daily_summary("user-1")
        assert s["due_tomorrow"] == 3


# ---------------------------------------------------------------------------
# achievements（成就触发条件）
# ---------------------------------------------------------------------------

class TestAchievements:
    def _make_streak(self, study: StudyService, user_id: str, days: int) -> None:
        """创建连续 N 天的已完成学习会话。"""
        for days_ago in range(days - 1, -1, -1):
            sess = study.start_session(user_id)
            dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
            dt_iso = dt.isoformat()
            study.db.execute(
                "UPDATE study_sessions SET started_at = ?, ended_at = ?, focus_minutes = 1, items_reviewed = 1 WHERE session_uid = ?",
                (dt_iso, dt_iso, sess),
            )

    def test_no_achievements_when_empty(self, study: StudyService):
        """无数据时成就列表为空。"""
        s = study.generate_daily_summary("user-1")
        assert s["achievements"] == []

    def test_achievement_streak_7(self, study: StudyService):
        """连续 7 天触发 '连续7天' 成就。"""
        self._make_streak(study, "user-streak7", 7)
        s = study.generate_daily_summary("user-streak7")
        assert "连续7天" in s["achievements"]

    def test_achievement_streak_3(self, study: StudyService):
        """连续 3 天触发 '连续3天' 成就。"""
        self._make_streak(study, "user-streak3", 3)
        s = study.generate_daily_summary("user-streak3")
        assert "连续3天" in s["achievements"]

    def test_achievement_streak_milestone_not_triggered_on_wrong_day(self, study: StudyService):
        """连续 4 天不触发 '连续3天' 成就（milestone 须精确匹配）。"""
        self._make_streak(study, "user-streak4", 4)
        s = study.generate_daily_summary("user-streak4")
        assert "连续3天" not in s["achievements"]

    def test_achievement_reviewed_10(self, study: StudyService):
        """今日复习 10 张触发 '完成10张复习' 成就。"""
        sess = study.start_session("user-1")
        study.end_session(sess, focus_minutes=20, items_reviewed=10)
        s = study.generate_daily_summary("user-1")
        assert "完成10张复习" in s["achievements"]

    def test_achievement_reviewed_5_not_10(self, study: StudyService):
        """今日复习 5 张触发 '完成5张复习'，不触发 '完成10张复习'。"""
        sess = study.start_session("user-1")
        study.end_session(sess, focus_minutes=15, items_reviewed=5)
        s = study.generate_daily_summary("user-1")
        assert "完成5张复习" in s["achievements"]
        assert "完成10张复习" not in s["achievements"]

    def test_achievement_reviewed_20_highest_milestone(self, study: StudyService):
        """今日复习 20 张，只触发最高里程碑 '完成20张复习'。"""
        sess = study.start_session("user-1")
        study.end_session(sess, focus_minutes=40, items_reviewed=20)
        s = study.generate_daily_summary("user-1")
        assert "完成20张复习" in s["achievements"]
        # 低档不应重复出现
        assert "完成5张复习" not in s["achievements"]
        assert "完成10张复习" not in s["achievements"]

    def test_achievement_focus_30_minutes(self, study: StudyService):
        """今日专注 30 分钟触发 '专注30分钟' 成就。"""
        sess = study.start_session("user-1")
        study.end_session(sess, focus_minutes=30, items_reviewed=1)
        s = study.generate_daily_summary("user-1")
        assert "专注30分钟" in s["achievements"]

    def test_achievement_focus_60_minutes(self, study: StudyService):
        """今日专注 60 分钟触发 '专注60分钟' 成就（最高档，不重复低档）。"""
        sess = study.start_session("user-1")
        study.end_session(sess, focus_minutes=60, items_reviewed=1)
        s = study.generate_daily_summary("user-1")
        assert "专注60分钟" in s["achievements"]
        assert "专注30分钟" not in s["achievements"]

    def test_achievement_goals_updated(self, study: StudyService):
        """今日更新目标触发 '更新N个目标' 成就。"""
        study.create_goal("user-1", "conv-1", "目标A")
        s = study.generate_daily_summary("user-1")
        assert any("更新" in a and "目标" in a for a in s["achievements"])


# ---------------------------------------------------------------------------
# get_review_summary_text
# ---------------------------------------------------------------------------

class TestGetReviewSummaryText:
    def test_returns_string(self, study: StudyService):
        """返回值应为 str。"""
        text = study.get_review_summary_text("user-1")
        assert isinstance(text, str)

    def test_contains_title(self, study: StudyService):
        """文本应包含摘要标题。"""
        text = study.get_review_summary_text("user-1")
        assert "学习摘要" in text

    def test_contains_streak_info(self, study: StudyService):
        """有连续学习天数时，文本中应有相关信息。"""
        sess = study.start_session("user-1")
        study.end_session(sess, focus_minutes=10, items_reviewed=2)
        text = study.get_review_summary_text("user-1")
        assert "连续打卡" in text

    def test_contains_reviewed_info(self, study: StudyService):
        """今日有复习时，文本应包含复习卡片数。"""
        sess = study.start_session("user-1")
        study.end_session(sess, focus_minutes=20, items_reviewed=7)
        text = study.get_review_summary_text("user-1")
        assert "7" in text

    def test_contains_due_tomorrow(self, study: StudyService):
        """有明日到期卡片时，文本应提及。"""
        item = study.add_review_item(user_id="user-1", front="Q", back="A")
        tomorrow = _iso_tomorrow_midday()
        study.db.execute(
            "UPDATE review_items SET next_review_at = ? WHERE item_uid = ?",
            (tomorrow, item["item_uid"]),
        )
        text = study.get_review_summary_text("user-1")
        assert "明日" in text or "1" in text

    def test_no_data_fallback_message(self, study: StudyService):
        """无学习数据时，文本应有合理的提示（不崩溃）。"""
        text = study.get_review_summary_text("user-new")
        assert len(text) > 0

    def test_achievements_in_text(self, study: StudyService):
        """有成就时，文本应包含成就信息。"""
        sess = study.start_session("user-1")
        study.end_session(sess, focus_minutes=30, items_reviewed=10)
        text = study.get_review_summary_text("user-1")
        assert "成就" in text or "专注" in text or "完成" in text
