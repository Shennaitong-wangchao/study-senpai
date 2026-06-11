"""学习目标追踪与间隔复习系统测试。

覆盖：
- study_goals CRUD（创建、列出、更新进度/状态）
- review_items 增加、到期查询、记录结果
- SM-2 算法正确性（多种 quality 值）
- study_sessions 开始/结束
- get_study_stats 统计
- 迁移幂等性（表已存在不报错）
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from src.db.database import Database
from src.db.migrations import _migration_20260611_study_system
from src.product.study import StudyService, sm2_update


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def database(tmp_path) -> Iterator[Database]:
    db = Database(str(tmp_path / "study_test.sqlite3"))
    db.initialize()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def study(database: Database) -> StudyService:
    return StudyService(db=database)


# ---------------------------------------------------------------------------
# SM-2 算法单元测试
# ---------------------------------------------------------------------------

class TestSm2Update:
    def test_quality_5_perfect_recall_first_rep(self):
        """第一次完美回忆：interval=1, reps=1, ef 上升。"""
        ef, interval, reps = sm2_update(2.5, 1, 0, 5)
        assert interval == 1
        assert reps == 1
        assert ef > 2.5  # 完美回忆应提升 ef

    def test_quality_4_second_rep(self):
        """第二次轻松回忆：interval 应变为 6。"""
        ef, interval, reps = sm2_update(2.5, 1, 1, 4)
        assert interval == 6
        assert reps == 2

    def test_quality_3_third_rep_uses_ef(self):
        """第三次及以后：interval = round(prev_interval * ef)。"""
        ef, interval, reps = sm2_update(2.5, 6, 2, 3)
        assert interval == round(6 * 2.5)
        assert reps == 3

    def test_quality_2_failure_resets(self):
        """quality < 3：重置 reps=0, interval=1。"""
        ef, interval, reps = sm2_update(2.5, 15, 5, 2)
        assert reps == 0
        assert interval == 1

    def test_quality_0_complete_forget(self):
        """quality=0：重置，且 ef 下降（但不低于 1.3）。"""
        ef_before = 2.5
        ef, interval, reps = sm2_update(ef_before, 30, 10, 0)
        assert reps == 0
        assert interval == 1
        assert ef < ef_before

    def test_ease_factor_minimum_clamp(self):
        """ef 最小值为 1.3，不会被压到 1.3 以下。"""
        # 连续多次 quality=0 测试极限值
        ef = 1.3
        new_ef, _, _ = sm2_update(ef, 1, 0, 0)
        assert new_ef >= 1.3

    def test_quality_5_increases_ef(self):
        """quality=5 应提升 ease_factor。"""
        ef, _, _ = sm2_update(2.5, 1, 0, 5)
        assert round(ef, 4) > 2.5

    def test_quality_3_keeps_ef_roughly_same(self):
        """quality=3 是刚好通过的阈值，ef 几乎不变（小幅下降）。"""
        ef_before = 2.5
        ef, _, _ = sm2_update(ef_before, 1, 0, 3)
        # quality=3: ef = max(1.3, 2.5 + 0.1 - 2*(0.08 + 2*0.02)) = 2.5 + 0.1 - 2*0.12 = 2.5 - 0.14 = 2.36
        assert ef < ef_before

    def test_return_types(self):
        """返回类型应为 (float, int, int)。"""
        ef, interval, reps = sm2_update(2.5, 1, 0, 4)
        assert isinstance(ef, float)
        assert isinstance(interval, int)
        assert isinstance(reps, int)


# ---------------------------------------------------------------------------
# 学习目标 CRUD 测试
# ---------------------------------------------------------------------------

class TestStudyGoals:
    def test_create_and_list_goals(self, study: StudyService):
        """创建目标后可以列出。"""
        goal = study.create_goal(
            user_id="user-1",
            conv_id="conv-1",
            title="学完高数第三章",
            subject="数学",
            target_date="2026-07-01",
        )
        assert goal["goal_uid"].startswith("goal_")
        assert goal["title"] == "学完高数第三章"
        assert goal["status"] == "active"
        assert goal["progress_pct"] == 0

        goals = study.list_goals("user-1")
        assert len(goals) == 1
        assert goals[0]["goal_uid"] == goal["goal_uid"]

    def test_list_goals_by_status(self, study: StudyService):
        """按 status 过滤目标。"""
        g1 = study.create_goal("user-1", "conv-1", "目标A")
        g2 = study.create_goal("user-1", "conv-1", "目标B")
        study.update_goal_status(g2["goal_uid"], "completed")

        active = study.list_goals("user-1", status="active")
        completed = study.list_goals("user-1", status="completed")

        assert len(active) == 1
        assert active[0]["goal_uid"] == g1["goal_uid"]
        assert len(completed) == 1
        assert completed[0]["goal_uid"] == g2["goal_uid"]

    def test_update_goal_progress(self, study: StudyService):
        """更新进度后能正确读取，且 clamp 到 0-100。"""
        goal = study.create_goal("user-1", "conv-1", "背单词")
        ok = study.update_goal_progress(goal["goal_uid"], 75)
        assert ok is True

        updated = study.get_goal(goal["goal_uid"])
        assert updated is not None
        assert updated["progress_pct"] == 75

    def test_progress_clamp(self, study: StudyService):
        """进度超过 100 应被 clamp 到 100；小于 0 应 clamp 到 0。"""
        goal = study.create_goal("user-1", "conv-1", "测试 clamp")
        study.update_goal_progress(goal["goal_uid"], 200)
        assert study.get_goal(goal["goal_uid"])["progress_pct"] == 100

        study.update_goal_progress(goal["goal_uid"], -10)
        assert study.get_goal(goal["goal_uid"])["progress_pct"] == 0

    def test_update_goal_status(self, study: StudyService):
        """更改目标状态。"""
        goal = study.create_goal("user-1", "conv-1", "状态测试")
        assert study.update_goal_status(goal["goal_uid"], "paused") is True
        assert study.get_goal(goal["goal_uid"])["status"] == "paused"

    def test_update_goal_status_invalid_raises(self, study: StudyService):
        """非法 status 应抛出 ValueError。"""
        goal = study.create_goal("user-1", "conv-1", "非法状态")
        with pytest.raises(ValueError, match="不合法的 status"):
            study.update_goal_status(goal["goal_uid"], "deleted")

    def test_get_goal_not_found(self, study: StudyService):
        """不存在的 goal_uid 返回 None。"""
        assert study.get_goal("goal_nonexistent") is None

    def test_user_isolation(self, study: StudyService):
        """不同用户的目标互相隔离。"""
        study.create_goal("user-1", "conv-1", "用户1的目标")
        study.create_goal("user-2", "conv-1", "用户2的目标")

        u1_goals = study.list_goals("user-1")
        u2_goals = study.list_goals("user-2")

        assert len(u1_goals) == 1
        assert len(u2_goals) == 1
        assert u1_goals[0]["title"] == "用户1的目标"
        assert u2_goals[0]["title"] == "用户2的目标"


# ---------------------------------------------------------------------------
# 复习卡片测试
# ---------------------------------------------------------------------------

class TestReviewItems:
    def test_add_review_item(self, study: StudyService):
        """添加卡片后有正确的 SM-2 初始值。"""
        item = study.add_review_item(
            user_id="user-1",
            front="光合作用的公式？",
            back="6CO2 + 6H2O → C6H12O6 + 6O2",
            subject="生物",
            tags=["生物", "初中"],
        )
        assert item["item_uid"].startswith("item_")
        assert item["ease_factor"] == 2.5
        assert item["interval_days"] == 1
        assert item["repetitions"] == 0
        assert item["tags"] == ["生物", "初中"]
        assert item["next_review_at"] is not None

    def test_add_review_item_with_goal(self, study: StudyService):
        """卡片可以关联到目标。"""
        goal = study.create_goal("user-1", "conv-1", "生物学习")
        item = study.add_review_item(
            user_id="user-1",
            front="光合作用发生在哪里？",
            back="叶绿体",
            goal_uid=goal["goal_uid"],
        )
        assert item["goal_uid"] == goal["goal_uid"]

    def test_get_due_items_new_card(self, study: StudyService):
        """新建卡片设置了 next_review_at=明天，今天不应到期。"""
        study.add_review_item(user_id="user-1", front="Q", back="A")
        due = study.get_due_items("user-1")
        # 明天才到期，今天不应出现
        assert len(due) == 0

    def test_get_due_items_past_due(self, study: StudyService):
        """手动将 next_review_at 设置到过去，应该出现在到期列表。"""
        item = study.add_review_item(user_id="user-1", front="Q过期", back="A过期")
        past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        study.db.execute(
            "UPDATE review_items SET next_review_at = ? WHERE item_uid = ?",
            (past, item["item_uid"]),
        )
        due = study.get_due_items("user-1")
        assert len(due) == 1
        assert due[0]["item_uid"] == item["item_uid"]

    def test_record_review_result_updates_sm2(self, study: StudyService):
        """记录 quality=4 后，SM-2 参数应正确更新。"""
        item = study.add_review_item(user_id="user-1", front="Q", back="A")
        # 把到期时间设为过去
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        study.db.execute(
            "UPDATE review_items SET next_review_at = ? WHERE item_uid = ?",
            (past, item["item_uid"]),
        )

        updated = study.record_review_result(item["item_uid"], quality=4)
        assert updated is not None
        assert updated["repetitions"] == 1
        assert updated["interval_days"] == 1  # 第一次 quality>=3，interval=1
        assert updated["last_reviewed_at"] is not None
        # next_review_at 应该在今天之后
        next_dt = datetime.fromisoformat(updated["next_review_at"])
        assert next_dt > datetime.now(timezone.utc)

    def test_record_review_result_failure_resets(self, study: StudyService):
        """quality < 3 应重置 repetitions 和 interval。"""
        item = study.add_review_item(user_id="user-1", front="Q", back="A")
        # 模拟已经有过几次复习
        study.db.execute(
            "UPDATE review_items SET repetitions = 5, interval_days = 30, ease_factor = 2.8 WHERE item_uid = ?",
            (item["item_uid"],),
        )
        updated = study.record_review_result(item["item_uid"], quality=1)
        assert updated is not None
        assert updated["repetitions"] == 0
        assert updated["interval_days"] == 1

    def test_record_review_result_not_found(self, study: StudyService):
        """不存在的 item 返回 None。"""
        assert study.record_review_result("item_nonexistent", quality=4) is None

    def test_record_review_result_invalid_quality(self, study: StudyService):
        """quality 超出范围应抛出 ValueError。"""
        item = study.add_review_item(user_id="user-1", front="Q", back="A")
        with pytest.raises(ValueError):
            study.record_review_result(item["item_uid"], quality=6)

    def test_list_review_items(self, study: StudyService):
        """列出卡片测试。"""
        study.add_review_item(user_id="user-1", front="Q1", back="A1")
        study.add_review_item(user_id="user-1", front="Q2", back="A2")
        items = study.list_review_items("user-1")
        assert len(items) == 2

    def test_due_items_respects_limit(self, study: StudyService):
        """get_due_items 应遵守 limit 参数。"""
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        for i in range(5):
            item = study.add_review_item(user_id="user-1", front=f"Q{i}", back=f"A{i}")
            study.db.execute(
                "UPDATE review_items SET next_review_at = ? WHERE item_uid = ?",
                (past, item["item_uid"]),
            )
        due = study.get_due_items("user-1", limit=3)
        assert len(due) == 3


# ---------------------------------------------------------------------------
# 学习会话测试
# ---------------------------------------------------------------------------

class TestStudySessions:
    def test_start_and_end_session(self, study: StudyService):
        """开始会话后可以结束并记录时长。"""
        session_uid = study.start_session("user-1")
        assert session_uid.startswith("sess_")

        ok = study.end_session(session_uid, focus_minutes=45, items_reviewed=10, notes="今天学了微积分")
        assert ok is True

        session = study.get_session(session_uid)
        assert session is not None
        assert session["focus_minutes"] == 45
        assert session["items_reviewed"] == 10
        assert session["notes"] == "今天学了微积分"
        assert session["ended_at"] is not None

    def test_start_session_with_goal(self, study: StudyService):
        """会话可以关联目标。"""
        goal = study.create_goal("user-1", "conv-1", "物理复习")
        session_uid = study.start_session("user-1", goal_uid=goal["goal_uid"])
        session = study.get_session(session_uid)
        assert session["goal_uid"] == goal["goal_uid"]

    def test_end_session_not_found(self, study: StudyService):
        """结束不存在的会话应返回 False。"""
        ok = study.end_session("sess_nonexistent", focus_minutes=30, items_reviewed=5)
        assert ok is False

    def test_end_session_twice_fails(self, study: StudyService):
        """已结束的会话不能再次结束。"""
        session_uid = study.start_session("user-1")
        study.end_session(session_uid, focus_minutes=30, items_reviewed=5)
        # 第二次 end_session 应返回 False（WHERE ended_at IS NULL 不满足）
        ok = study.end_session(session_uid, focus_minutes=60, items_reviewed=10)
        assert ok is False


# ---------------------------------------------------------------------------
# 统计测试
# ---------------------------------------------------------------------------

class TestStudyStats:
    def test_get_study_stats_empty(self, study: StudyService):
        """空数据情况下统计应返回合理的零值。"""
        stats = study.get_study_stats("user-1")
        assert stats["streak_days"] == 0
        assert stats["total_review_items"] == 0
        assert stats["active_goals"] == 0
        assert stats["due_today"] == 0

    def test_get_study_stats_with_data(self, study: StudyService):
        """有数据时统计应正确返回。"""
        study.create_goal("user-1", "conv-1", "目标1")
        study.create_goal("user-1", "conv-1", "目标2")
        study.add_review_item(user_id="user-1", front="Q1", back="A1")
        study.add_review_item(user_id="user-1", front="Q2", back="A2")

        # 添加一张过期卡片
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        item = study.add_review_item(user_id="user-1", front="Q_due", back="A_due")
        study.db.execute(
            "UPDATE review_items SET next_review_at = ? WHERE item_uid = ?",
            (past, item["item_uid"]),
        )

        # 完成一个会话
        session_uid = study.start_session("user-1")
        study.end_session(session_uid, focus_minutes=30, items_reviewed=5)

        stats = study.get_study_stats("user-1")
        assert stats["active_goals"] == 2
        assert stats["total_review_items"] == 3
        assert stats["due_today"] == 1
        assert stats["sessions_today"] == 1
        assert stats["focus_minutes_today"] == 30
        assert stats["items_reviewed_today"] == 5

    def test_streak_single_day(self, study: StudyService):
        """今天有会话，连续天数应为 1。"""
        session_uid = study.start_session("user-1")
        study.end_session(session_uid, focus_minutes=20, items_reviewed=3)
        stats = study.get_study_stats("user-1")
        assert stats["streak_days"] >= 1


# ---------------------------------------------------------------------------
# 迁移幂等性测试
# ---------------------------------------------------------------------------

class TestMigrationIdempotency:
    def test_study_migration_is_idempotent(self):
        """重复运行迁移不应报错（CREATE TABLE IF NOT EXISTS）。"""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            # 第一次运行
            _migration_20260611_study_system(conn)
            # 第二次运行（幂等性验证）
            _migration_20260611_study_system(conn)

            # 验证表都已创建
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?)",
                    ("study_goals", "review_items", "study_sessions"),
                ).fetchall()
            }
            assert tables == {"study_goals", "review_items", "study_sessions"}
        finally:
            conn.close()

    def test_study_tables_exist_after_db_initialize(self, database: Database):
        """database.initialize() 后三张学习表均存在。"""
        tables = {
            row["name"]
            for row in database.fetchall(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table'
                  AND name IN ('study_goals', 'review_items', 'study_sessions')
                """
            )
        }
        assert tables == {"study_goals", "review_items", "study_sessions"}
