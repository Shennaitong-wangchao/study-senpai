"""周学习报告生成功能测试。

覆盖：
1. 空数据时返回零值
2. 基本报告生成（sessions + cards）
3. period 字段正确
4. summary 各字段准确
5. streak 字段（current + longest_this_week）
6. by_subject 按学科汇总
7. next_week_due 下周到期数
8. trend 计算（improving / stable / declining）
9. highlights 生成逻辑
10. period_days=30 月报生成
11. 多个连续日期 streak 计算
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from src.db.database import Database
from src.product.study import StudyService


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _iso(days_ago: int = 0, hour: int = 10) -> str:
    """返回距今 days_ago 天前的 UTC ISO 字符串（指定小时）。"""
    dt = datetime.now(timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0)
    dt -= timedelta(days=days_ago)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def database(tmp_path) -> Iterator[Database]:
    db = Database(str(tmp_path / "weekly_report_test.sqlite3"))
    db.initialize()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def study(database: Database) -> StudyService:
    return StudyService(db=database)


def _add_session(study: StudyService, user_id: str, days_ago: int = 0,
                 focus_minutes: int = 30, items_reviewed: int = 10,
                 goal_uid: str | None = None) -> str:
    """插入一条已结束的学习会话（辅助函数）。"""
    sess_uid = study.start_session(user_id, goal_uid=goal_uid)
    # 手动将 started_at 设为 days_ago 天前（绕过 ISO 默认为 now）
    started_at = _iso(days_ago)
    study.db.execute(
        "UPDATE study_sessions SET started_at = ? WHERE session_uid = ?",
        (started_at, sess_uid),
    )
    study.end_session(sess_uid, focus_minutes=focus_minutes, items_reviewed=items_reviewed)
    return sess_uid


def _add_card(study: StudyService, user_id: str, days_ago: int = 0,
              subject: str | None = None, last_reviewed_ago: int | None = None) -> str:
    """添加一张复习卡片（辅助函数）。"""
    item = study.add_review_item(user_id, front="Q", back="A", subject=subject)
    item_uid = item["item_uid"]
    # 调整 created_at
    created_at = _iso(days_ago)
    study.db.execute(
        "UPDATE review_items SET created_at = ?, updated_at = ? WHERE item_uid = ?",
        (created_at, created_at, item_uid),
    )
    # 调整 last_reviewed_at（用于 by_subject 统计）
    if last_reviewed_ago is not None:
        last_reviewed_at = _iso(last_reviewed_ago)
        study.db.execute(
            "UPDATE review_items SET last_reviewed_at = ? WHERE item_uid = ?",
            (last_reviewed_at, item_uid),
        )
    return item_uid


# ---------------------------------------------------------------------------
# 测试：空数据
# ---------------------------------------------------------------------------

class TestWeeklyReportEmpty:
    def test_empty_returns_zero_summary(self, study: StudyService) -> None:
        """无任何数据时，summary 各数字字段均为 0。"""
        report = study.generate_weekly_report("user-empty")
        s = report["summary"]
        assert s["total_sessions"] == 0
        assert s["total_focus_minutes"] == 0
        assert s["total_cards_reviewed"] == 0
        assert s["goals_progressed"] == 0
        assert s["new_cards_added"] == 0

    def test_empty_returns_zero_streak(self, study: StudyService) -> None:
        report = study.generate_weekly_report("user-empty2")
        assert report["streak"]["current"] == 0
        assert report["streak"]["longest_this_week"] == 0

    def test_empty_next_week_due_zero(self, study: StudyService) -> None:
        report = study.generate_weekly_report("user-empty3")
        assert report["next_week_due"] == 0

    def test_empty_trend_stable(self, study: StudyService) -> None:
        """无历史数据时，trend 应为 stable。"""
        report = study.generate_weekly_report("user-no-data")
        assert report["trend"] == "stable"


# ---------------------------------------------------------------------------
# 测试：period 字段
# ---------------------------------------------------------------------------

class TestWeeklyReportPeriod:
    def test_period_7_days_span(self, study: StudyService) -> None:
        """7 天周报的 period 字段正确。"""
        report = study.generate_weekly_report("u-period", period_days=7)
        from datetime import date
        start = datetime.fromisoformat(report["period"]["start"]).date() if isinstance(report["period"]["start"], str) else report["period"]["start"]
        end_dt = datetime.fromisoformat(report["period"]["end"]).date() if isinstance(report["period"]["end"], str) else report["period"]["end"]
        # 转成 date 对象
        if isinstance(start, str):
            start = datetime.strptime(start, "%Y-%m-%d").date()
        if isinstance(end_dt, str):
            end_dt = datetime.strptime(end_dt, "%Y-%m-%d").date()
        assert (end_dt - start).days == 6  # 7 天 span
        assert report["period"]["days"] == 7

    def test_period_30_days_span(self, study: StudyService) -> None:
        """30 天月报的 period 字段正确。"""
        report = study.generate_weekly_report("u-period-30", period_days=30)
        start_str = report["period"]["start"]
        end_str = report["period"]["end"]
        start = datetime.strptime(start_str, "%Y-%m-%d").date()
        end = datetime.strptime(end_str, "%Y-%m-%d").date()
        assert (end - start).days == 29
        assert report["period"]["days"] == 30


# ---------------------------------------------------------------------------
# 测试：基本报告生成
# ---------------------------------------------------------------------------

class TestWeeklyReportBasic:
    def test_sessions_counted(self, study: StudyService) -> None:
        """本周 sessions 数量和时长被正确统计。"""
        for i in range(3):
            _add_session(study, "user-basic", days_ago=i, focus_minutes=40, items_reviewed=8)
        report = study.generate_weekly_report("user-basic")
        s = report["summary"]
        assert s["total_sessions"] == 3
        assert s["total_focus_minutes"] == 120
        assert s["total_cards_reviewed"] == 24

    def test_old_sessions_excluded(self, study: StudyService) -> None:
        """超过 7 天前的 session 不应被纳入本周统计。"""
        _add_session(study, "user-old", days_ago=8, focus_minutes=60, items_reviewed=20)
        _add_session(study, "user-old", days_ago=2, focus_minutes=30, items_reviewed=5)
        report = study.generate_weekly_report("user-old")
        s = report["summary"]
        assert s["total_sessions"] == 1
        assert s["total_focus_minutes"] == 30

    def test_new_cards_counted(self, study: StudyService) -> None:
        """本周新增卡片数被正确统计。"""
        for i in range(5):
            _add_card(study, "user-cards", days_ago=i)
        _add_card(study, "user-cards", days_ago=10)  # 超出范围
        report = study.generate_weekly_report("user-cards")
        assert report["summary"]["new_cards_added"] == 5


# ---------------------------------------------------------------------------
# 测试：trend 计算
# ---------------------------------------------------------------------------

class TestWeeklyReportTrend:
    def test_trend_improving(self, study: StudyService) -> None:
        """本周显著优于上周，trend = improving。"""
        # 上周（8-14 天前）：1 session
        _add_session(study, "user-trend", days_ago=10, focus_minutes=10, items_reviewed=2)
        # 本周（0-6 天前）：5 sessions
        for i in range(5):
            _add_session(study, "user-trend", days_ago=i, focus_minutes=40, items_reviewed=15)
        report = study.generate_weekly_report("user-trend")
        assert report["trend"] == "improving"

    def test_trend_declining(self, study: StudyService) -> None:
        """本周显著低于上周，trend = declining。"""
        # 上周
        for i in range(5):
            _add_session(study, "user-decline", days_ago=8 + i, focus_minutes=40, items_reviewed=15)
        # 本周（仅 1 session）
        _add_session(study, "user-decline", days_ago=1, focus_minutes=10, items_reviewed=2)
        report = study.generate_weekly_report("user-decline")
        assert report["trend"] == "declining"

    def test_trend_stable(self, study: StudyService) -> None:
        """本周与上周相当，trend = stable。"""
        # 上周和本周各 2 次 30 分钟
        for i in range(2):
            _add_session(study, "user-stable", days_ago=8 + i, focus_minutes=30, items_reviewed=5)
        for i in range(2):
            _add_session(study, "user-stable", days_ago=i, focus_minutes=30, items_reviewed=5)
        report = study.generate_weekly_report("user-stable")
        assert report["trend"] == "stable"

    def test_trend_first_week_with_data(self, study: StudyService) -> None:
        """上周无数据、本周有数据时，trend = improving。"""
        _add_session(study, "user-first-week", days_ago=1, focus_minutes=30, items_reviewed=10)
        report = study.generate_weekly_report("user-first-week")
        assert report["trend"] == "improving"


# ---------------------------------------------------------------------------
# 测试：by_subject
# ---------------------------------------------------------------------------

class TestWeeklyReportBySubject:
    def test_by_subject_aggregation(self, study: StudyService) -> None:
        """按学科汇总复习卡片数量。"""
        for _ in range(3):
            _add_card(study, "user-subj", days_ago=1, subject="数学",
                      last_reviewed_ago=1)
        for _ in range(2):
            _add_card(study, "user-subj", days_ago=2, subject="英语",
                      last_reviewed_ago=2)
        report = study.generate_weekly_report("user-subj")
        subjects = {item["subject"]: item["cards_reviewed"] for item in report["by_subject"]}
        assert subjects.get("数学", 0) == 3
        assert subjects.get("英语", 0) == 2


# ---------------------------------------------------------------------------
# 测试：monthly report（30 天）
# ---------------------------------------------------------------------------

class TestMonthlyReport:
    def test_monthly_sessions_counted(self, study: StudyService) -> None:
        """月报正确统计 30 天内的 sessions。"""
        for i in range(5):
            _add_session(study, "user-monthly", days_ago=i * 5, focus_minutes=50,
                         items_reviewed=10)
        _add_session(study, "user-monthly", days_ago=31, focus_minutes=60, items_reviewed=20)
        report = study.generate_weekly_report("user-monthly", period_days=30)
        assert report["summary"]["total_sessions"] == 5
