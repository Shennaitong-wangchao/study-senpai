"""AI 学习计划生成器测试。

覆盖：
- generate_study_plan 的基本逻辑：urgency 计算、有/无目标日期时的行为
- daily_minutes 映射正确性
- cards_per_day 计算（due_today + 3，clamp 到 5~20）
- days_until_target 显式传入时覆盖 target_date
- /plan 命令处理（返回包含计划信息的文本）
- /start + /done 命令流程
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.db.database import Database
from src.db.migrations import _migration_20260611_study_system
from src.product.study import StudyService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def database(tmp_path) -> Iterator[Database]:
    db = Database(str(tmp_path / "plan_test.sqlite3"))
    db.initialize()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def study(database: Database) -> StudyService:
    return StudyService(db=database)


@pytest.fixture()
def user_id() -> str:
    return "user_plan_test_001"


@pytest.fixture()
def goal(study: StudyService, user_id: str):
    """创建一个活跃的学习目标（无截止日期）。"""
    return study.create_goal(
        user_id=user_id,
        conv_id="conv_test_001",
        title="高考数学备考",
        subject="数学",
    )


@pytest.fixture()
def goal_with_target(study: StudyService, user_id: str):
    """创建一个带有 60 天后截止日期的目标。"""
    future_date = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
    return study.create_goal(
        user_id=user_id,
        conv_id="conv_test_001",
        title="英语四级备考",
        subject="英语",
        target_date=future_date,
    )


# ---------------------------------------------------------------------------
# generate_study_plan：urgency 计算
# ---------------------------------------------------------------------------


class TestGenerateStudyPlanUrgency:
    """验证 urgency 根据 days_until_target 正确分级。"""

    def test_none_days_returns_low_urgency(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=None)
        assert plan["urgency"] == "low"

    def test_91_days_returns_low(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=91)
        assert plan["urgency"] == "low"

    def test_90_days_returns_medium(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=90)
        assert plan["urgency"] == "medium"

    def test_31_days_returns_medium(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=31)
        assert plan["urgency"] == "medium"

    def test_30_days_returns_high(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=30)
        assert plan["urgency"] == "high"

    def test_8_days_returns_high(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=8)
        assert plan["urgency"] == "high"

    def test_7_days_returns_critical(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=7)
        assert plan["urgency"] == "critical"

    def test_0_days_returns_critical(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=0)
        assert plan["urgency"] == "critical"

    def test_1_day_returns_critical(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=1)
        assert plan["urgency"] == "critical"


# ---------------------------------------------------------------------------
# generate_study_plan：daily_minutes
# ---------------------------------------------------------------------------


class TestGenerateStudyPlanDailyMinutes:
    """验证每日学习时长随紧迫度正确映射。"""

    def test_low_urgency_gives_30_minutes(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=None)
        assert plan["daily_minutes"] == 30

    def test_medium_urgency_gives_45_minutes(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=60)
        assert plan["urgency"] == "medium"
        assert plan["daily_minutes"] == 45

    def test_high_urgency_gives_60_minutes(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=15)
        assert plan["urgency"] == "high"
        assert plan["daily_minutes"] == 60

    def test_critical_urgency_gives_90_minutes(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=3)
        assert plan["urgency"] == "critical"
        assert plan["daily_minutes"] == 90

    def test_less_than_7_days_is_critical(self, study: StudyService, goal: dict, user_id: str):
        """days_until_target < 7 时，daily_minutes 应为 90（critical）。"""
        for days in (1, 3, 5, 6, 7):
            plan = study.generate_study_plan(user_id, goal["goal_uid"], days_until_target=days)
            assert plan["urgency"] == "critical"
            assert plan["daily_minutes"] == 90, f"days={days} 应为 critical，得到 {plan['urgency']}"


# ---------------------------------------------------------------------------
# generate_study_plan：cards_per_day
# ---------------------------------------------------------------------------


class TestGenerateStudyPlanCardsPerDay:
    """验证每日卡片数计算逻辑。"""

    def test_no_due_cards_gives_minimum_5(self, study: StudyService, goal: dict, user_id: str):
        """没有到期卡片时：min(20, max(5, 0+3)) = 5。"""
        plan = study.generate_study_plan(user_id, goal["goal_uid"])
        assert plan["cards_per_day"] == 5

    def test_due_cards_adds_3(self, study: StudyService, goal: dict, user_id: str, database: Database):
        """有 10 张到期卡片时：min(20, max(5, 10+3)) = 13。"""
        # 手动设置 10 张过期卡片（next_review_at 在过去）
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        for i in range(10):
            study.add_review_item(
                user_id=user_id,
                front=f"问题 {i}",
                back=f"答案 {i}",
                goal_uid=goal["goal_uid"],
            )
        # 将 next_review_at 设到过去
        database.execute(
            "UPDATE review_items SET next_review_at = ? WHERE user_id = ? AND goal_uid = ?",
            (past, user_id, goal["goal_uid"]),
        )
        plan = study.generate_study_plan(user_id, goal["goal_uid"])
        assert plan["cards_per_day"] == 13

    def test_cards_per_day_max_is_20(self, study: StudyService, goal: dict, user_id: str, database: Database):
        """到期卡片 >= 18 张时，cards_per_day 不超过 20。"""
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        for i in range(20):
            study.add_review_item(
                user_id=user_id,
                front=f"大量问题 {i}",
                back=f"大量答案 {i}",
                goal_uid=goal["goal_uid"],
            )
        database.execute(
            "UPDATE review_items SET next_review_at = ? WHERE user_id = ? AND goal_uid = ?",
            (past, user_id, goal["goal_uid"]),
        )
        plan = study.generate_study_plan(user_id, goal["goal_uid"])
        assert plan["cards_per_day"] <= 20


# ---------------------------------------------------------------------------
# generate_study_plan：auto-detect target_date
# ---------------------------------------------------------------------------


class TestGenerateStudyPlanTargetDateAutoDetect:
    """验证目标有 target_date 时自动计算紧迫度。"""

    def test_auto_detect_60_days_is_medium(
        self, study: StudyService, goal_with_target: dict, user_id: str
    ):
        """goal_with_target 设置了 60 天后的截止日期，不传 days 时应自动计算为 medium。"""
        plan = study.generate_study_plan(user_id, goal_with_target["goal_uid"])
        # 60 天 → medium
        assert plan["urgency"] == "medium"

    def test_explicit_days_overrides_target_date(
        self, study: StudyService, goal_with_target: dict, user_id: str
    ):
        """显式传入 days_until_target=3 应覆盖目标的 target_date，urgency 为 critical。"""
        plan = study.generate_study_plan(
            user_id, goal_with_target["goal_uid"], days_until_target=3
        )
        assert plan["urgency"] == "critical"

    def test_no_target_date_defaults_to_low(self, study: StudyService, goal: dict, user_id: str):
        """目标没有 target_date，且不传 days 时，urgency 应为 low。"""
        plan = study.generate_study_plan(user_id, goal["goal_uid"])
        assert plan["urgency"] == "low"
        assert plan["daily_minutes"] == 30


# ---------------------------------------------------------------------------
# generate_study_plan：返回结构完整性
# ---------------------------------------------------------------------------


class TestGenerateStudyPlanStructure:
    """验证返回的计划 dict 包含所有必要字段。"""

    def test_plan_has_required_keys(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"])
        required_keys = {
            "goal_uid",
            "user_id",
            "urgency",
            "daily_minutes",
            "cards_per_day",
            "focus_areas",
            "weekly_checkpoints",
            "computed_at",
        }
        assert required_keys.issubset(plan.keys())

    def test_focus_areas_is_list(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"])
        assert isinstance(plan["focus_areas"], list)
        assert len(plan["focus_areas"]) > 0

    def test_weekly_checkpoints_is_list(self, study: StudyService, goal: dict, user_id: str):
        plan = study.generate_study_plan(user_id, goal["goal_uid"])
        assert isinstance(plan["weekly_checkpoints"], list)
        assert len(plan["weekly_checkpoints"]) > 0

    def test_subject_appears_in_focus_areas(self, study: StudyService, goal: dict, user_id: str):
        """目标有 subject='数学' 时，focus_areas 应包含 '数学'。"""
        plan = study.generate_study_plan(user_id, goal["goal_uid"])
        assert "数学" in plan["focus_areas"]

    def test_no_subject_gives_default_focus_areas(
        self, study: StudyService, user_id: str, database: Database
    ):
        """目标没有 subject 时，focus_areas 给出通用建议。"""
        goal = study.create_goal(
            user_id=user_id,
            conv_id="conv_test_x",
            title="自由学习",
            subject=None,
        )
        plan = study.generate_study_plan(user_id, goal["goal_uid"])
        assert len(plan["focus_areas"]) > 0
        # 通用建议中包含"概念"或"练习"之类的词
        combined = " ".join(plan["focus_areas"])
        assert any(keyword in combined for keyword in ["概念", "练习", "复盘"])


# ---------------------------------------------------------------------------
# /plan 命令：文本输出验证
# ---------------------------------------------------------------------------


class TestPlanCommand:
    """/plan 命令处理器测试。"""

    def _make_router(self, database: Database):
        """构造 CommandRouter。"""
        from src.bot.commands import CommandRouter
        return CommandRouter(db=database)

    def test_plan_command_no_args_returns_usage(self, database: Database):
        router = self._make_router(database)
        result = router._handle_plan("user_x", "")
        assert "用法" in result or "plan" in result.lower()

    def test_plan_command_by_title_returns_plan_text(
        self, database: Database, study: StudyService, goal: dict, user_id: str
    ):
        """用目标标题调用 /plan，应返回含紧迫度和每日时长的文本。"""
        router = self._make_router(database)
        result = router._handle_plan(user_id, "高考数学备考")
        assert "学习计划" in result or "每日" in result
        # 应包含 daily_minutes 的某个数字
        assert any(str(m) in result for m in (30, 45, 60, 90))

    def test_plan_command_goal_not_found(self, database: Database, user_id: str):
        """查找不存在的目标时，返回友好的错误提示。"""
        router = self._make_router(database)
        result = router._handle_plan(user_id, "一个绝对不存在的目标xyz")
        assert "找不到" in result or "不存在" in result or "goals" in result.lower()

    def test_plan_command_by_uid(
        self, database: Database, study: StudyService, goal: dict, user_id: str
    ):
        """用 goal_uid 直接查找应正确返回计划。"""
        router = self._make_router(database)
        result = router._handle_plan(user_id, goal["goal_uid"])
        assert "学习计划" in result or "每日" in result

    def test_plan_includes_checkpoints(
        self, database: Database, study: StudyService, goal: dict, user_id: str
    ):
        """计划文本中应包含里程碑信息。"""
        router = self._make_router(database)
        result = router._handle_plan(user_id, "高考数学备考")
        assert "里程碑" in result or "第" in result or "周" in result


# ---------------------------------------------------------------------------
# /start + /done 命令：会话流程
# ---------------------------------------------------------------------------


class TestStartDoneCommands:
    """/start 和 /done 命令集成测试。"""

    def _make_router(self, database: Database):
        from src.bot.commands import CommandRouter, _active_sessions
        router = CommandRouter(db=database)
        # 清理残留 session
        _active_sessions.clear()
        return router

    def test_start_without_goal_creates_session(self, database: Database, user_id: str):
        from src.bot.commands import _active_sessions
        router = self._make_router(database)
        result = router._handle_start(user_id, "")
        assert "已开始" in result
        assert user_id in _active_sessions

    def test_start_with_goal_binds_session(
        self, database: Database, study: StudyService, goal: dict, user_id: str
    ):
        from src.bot.commands import _active_sessions
        router = self._make_router(database)
        result = router._handle_start(user_id, "高考数学备考")
        assert "已开始" in result
        assert goal["title"] in result
        assert user_id in _active_sessions

    def test_done_without_start_returns_error(self, database: Database, user_id: str):
        from src.bot.commands import _active_sessions
        router = self._make_router(database)
        _active_sessions.pop(user_id, None)  # 确保无活跃 session
        result = router._handle_done(user_id, "30")
        assert "没有找到" in result or "start" in result.lower()

    def test_done_without_args_returns_usage(self, database: Database, user_id: str):
        router = self._make_router(database)
        result = router._handle_done(user_id, "")
        assert "用法" in result or "分钟" in result

    def test_done_invalid_number_returns_error(self, database: Database, user_id: str):
        router = self._make_router(database)
        result = router._handle_done(user_id, "abc")
        assert "格式错误" in result or "分钟" in result

    def test_start_then_done_records_session(self, database: Database, user_id: str):
        """完整 /start → /done 流程：会话应成功创建并结束。"""
        from src.bot.commands import _active_sessions
        router = self._make_router(database)
        # 开始会话
        start_result = router._handle_start(user_id, "")
        assert user_id in _active_sessions
        # 结束会话
        done_result = router._handle_done(user_id, "45")
        assert "已记录" in done_result or "✅" in done_result
        assert "45" in done_result
        # 结束后清除活跃 session
        assert user_id not in _active_sessions

    def test_done_clears_active_session(self, database: Database, user_id: str):
        """成功结束后，_active_sessions 中不应再有该 user_id。"""
        from src.bot.commands import _active_sessions
        router = self._make_router(database)
        router._handle_start(user_id, "")
        router._handle_done(user_id, "20")
        assert user_id not in _active_sessions
