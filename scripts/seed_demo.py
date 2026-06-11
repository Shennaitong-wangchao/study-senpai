#!/usr/bin/env python3
"""Study Senpai Demo 数据生成脚本。

在空白数据库中生成逼真的演示数据，供 Dashboard 展示和截图使用。
所有数据均为虚构，不含真实个人信息。

用法：
    python3 scripts/seed_demo.py
    python3 scripts/seed_demo.py --database data/demo.sqlite3
    python3 scripts/seed_demo.py --reset  # 清空后重新生成
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.types import ConversationScope, MessageContext
from src.db.database import Database
from src.memory.store import MemoryStore
from src.product.store import ProductStore
from src.product.study import StudyService
from src.utils.time_utils import iso_utc_now


def _days_ago(n: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=n)
    return dt.isoformat()


def _seed_memories(store: MemoryStore, scope: ConversationScope) -> None:
    """生成虚构的长期记忆示例。"""
    memories = [
        ("personal_fact", "hobby", "用户喜欢在深夜听轻音乐复习，尤其是钢琴曲", ["music", "study"], 0.9, 0.8),
        ("personal_fact", "schedule", "每天 22:00-23:30 是用户的固定自习时间", ["schedule", "study"], 0.95, 0.9),
        ("study_context", "subject", "用户正在备考高中数学，重点是导数和微积分", ["math", "exam"], 0.9, 0.85),
        ("study_context", "weakness", "用户在立体几何题目上经常出错，需要加强空间想象力训练", ["math", "geometry"], 0.85, 0.8),
        ("emotional_context", "stress", "用户在模拟考试成绩不理想时容易焦虑，需要先安慰再建议", ["emotion", "exam"], 0.8, 0.75),
        ("preference", "feedback", "用户喜欢具体的、可操作的学习建议，不喜欢空洞的鼓励", ["preference"], 0.9, 0.85),
        ("routine_pattern", "sleep", "用户通常 0:30 左右睡觉，但最近因为备考经常熬夜到 1:30", ["sleep", "health"], 0.85, 0.7),
        ("commitment_record", "plan", "用户承诺每天做 3 道导数题，已坚持了 12 天", ["math", "commitment"], 0.9, 0.9),
        ("care_history", "support", "用户上周模考数学只考了 88 分，比目标低 12 分，当时情绪很低落", ["exam", "support"], 0.8, 0.75),
        ("relationship_signal", "trust", "用户愿意分享考试成绩和学习挫折，说明信任程度较高", ["relationship"], 0.85, 0.7),
    ]
    for mem_type, category, content, tags, confidence, importance in memories:
        store.insert_or_merge_long_term_memory(
            scope,
            memory_type=mem_type,
            category=category,
            content=content,
            tags=tags,
            confidence=confidence,
            importance=importance,
            source_message_ids=[],
        )
    print(f"  ✓ 已生成 {len(memories)} 条长期记忆")


def _seed_messages(store: MemoryStore, scope: ConversationScope) -> None:
    """生成虚构的对话消息示例。"""
    conversations = [
        ("user", "学姐，今天数学模考考了 88 分，比目标差了 12 分，好难受"),
        ("assistant", "88 分，我知道这跟你的目标有差距，但先别急着评判这个分数。\n\n能告诉我是哪些题目扣分了吗？是粗心还是真的没掌握？"),
        ("user", "立体几何扣了 10 分，感觉空间想象能力太差了"),
        ("assistant", "立体几何扣 10 分，这个方向很清晰了——不是整体的问题，是这一块需要专项突破。\n\n空间想象能力是可以练出来的。我建议你找 10 道经典的三视图题先做一遍，感受一下思路，而不是大量刷题。质比量重要。"),
        ("user", "好，我先试试。学姐你今天在干什么？"),
        ("assistant", "（轻声）我在陪着你啊。\n\n你先把今天的导数练习题做完，做完了告诉我感觉怎么样。"),
    ]
    for sender, content in conversations:
        store.insert_message(
            scope,
            sender_type=sender,
            content=content,
            context=MessageContext(
                platform_message_id=f"demo_{uuid.uuid4().hex[:8]}",
                author_id="demo_user",
            ),
        )
    print(f"  ✓ 已生成 {len(conversations)} 条对话消息")


def _seed_study_data(study_service: StudyService, user_id: str, conv_id: str) -> None:
    """生成虚构的学习目标和复习卡片。"""
    # 学习目标
    goals = [
        ("高考数学备考", "数学", "2026-06-07"),
        ("英语词汇 6000 词", "英语", "2026-05-01"),
        ("Python 编程入门", "编程", None),
    ]
    goal_uids = []
    for title, subject, target_date in goals:
        goal = study_service.create_goal(
            user_id=user_id,
            conv_id=conv_id,
            title=title,
            subject=subject,
            target_date=target_date,
        )
        goal_uids.append(goal["goal_uid"])
        # 设置不同进度
        progress = 45 if "数学" in subject else (30 if "英语" in subject else 20)
        study_service.update_goal_progress(goal["goal_uid"], progress)

    print(f"  ✓ 已生成 {len(goals)} 个学习目标")

    # 复习卡片（数学）
    cards = [
        ("导数的几何意义是什么？", "函数在某点的切线斜率"),
        ("什么是函数的极值？", "函数从增到减的转折点（极大值）或从减到增的转折点（极小值）"),
        ("牛顿-莱布尼兹公式", "∫[a,b] f(x)dx = F(b) - F(a)，其中 F'(x) = f(x)"),
        ("等差数列的前 n 项和", "Sn = n(a1 + an) / 2 = na1 + n(n-1)d/2"),
        ("正弦定理", "a/sinA = b/sinB = c/sinC = 2R"),
        ("What does 'meticulous' mean?", "极度谨慎的、一丝不苟的"),
        ("'Conundrum' 的含义", "难题、困惑（尤指复杂的、令人困扰的问题）"),
    ]
    for i, (front, back) in enumerate(cards):
        subject = "数学" if i < 5 else "英语"
        goal_uid = goal_uids[0] if i < 5 else goal_uids[1]
        item = study_service.add_review_item(
            user_id=user_id,
            front=front,
            back=back,
            subject=subject,
            goal_uid=goal_uid,
        )
        # 部分卡片已经复习过
        if i < 3:
            quality = 4 if i == 0 else 3
            study_service.record_review_result(item["item_uid"], quality)

    print(f"  ✓ 已生成 {len(cards)} 张复习卡片")

    # 学习会话历史
    for days_ago in range(5, 0, -1):
        session_uid = study_service.start_session(user_id=user_id, goal_uid=goal_uids[0])
        study_service.end_session(
            session_uid=session_uid,
            focus_minutes=45 + days_ago * 5,
            items_reviewed=3 + days_ago,
            notes=f"第 {6 - days_ago} 天复习记录（演示数据）",
        )
    print("  ✓ 已生成 5 天学习会话历史")


def _seed_product_data(product_store: ProductStore, scope: ConversationScope) -> None:
    """生成任务队列和可观测性示例数据。"""
    from src.memory.models import LongTermMemoryCandidate

    # 候选记忆（待审核）
    candidates = [
        ("preference", "study", "用户在压力大时更喜欢做选择题而不是解答题", 0.85, 0.8),
        ("personal_fact", "habit", "用户会在睡前把第二天的学习计划写在便利贴上", 0.9, 0.75),
    ]
    for mem_type, category, content, confidence, importance in candidates:
        candidate = LongTermMemoryCandidate(
            memory_type=mem_type,
            category=category,
            content=content,
            tags=[category],
            importance=importance,
            confidence=confidence,
            reason="从对话中提取（演示数据）",
            source_message_ids=[],
        )
        product_store.create_candidate_memory(scope, candidate)
    print(f"  ✓ 已生成 {len(candidates)} 条候选记忆（待审核）")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Study Senpai 演示数据")
    parser.add_argument("--database", default="data/demo.sqlite3", help="数据库路径")
    parser.add_argument("--reset", action="store_true", help="清空后重新生成")
    args = parser.parse_args()

    db_path = Path(args.database)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if args.reset and db_path.exists():
        db_path.unlink()
        for wal in [db_path.with_suffix(".sqlite3-wal"), db_path.with_suffix(".sqlite3-shm")]:
            if wal.exists():
                wal.unlink()
        print(f"已删除旧数据库：{db_path}")

    print(f"\n🌱 生成 Study Senpai 演示数据 → {db_path}\n")

    database = Database(str(db_path))
    database.initialize()
    store = MemoryStore(database)
    product_store = ProductStore(database)
    study_service = StudyService(db=database)

    # 虚构用户
    user_id = "demo_user_001"
    conv_id = "demo_conversation_001"

    scope = ConversationScope(
        platform="dashboard",
        conversation_id=conv_id,
        user_id=user_id,
        channel_id="demo_channel",
        guild_id=None,
        session_id="demo_session",
    )

    # 设置活跃 scope
    product_store.set_dashboard_active_scope(
        user_id=user_id,
        conversation_id=conv_id,
        channel_id="demo_channel",
        guild_id=None,
    )

    print("📝 记忆和消息：")
    _seed_memories(store, scope)
    _seed_messages(store, scope)

    print("\n📚 学习数据：")
    _seed_study_data(study_service, user_id, conv_id)

    print("\n🔍 产品数据：")
    _seed_product_data(product_store, scope)

    database.close()

    print(f"""
✅ 演示数据生成完成！

启动 Dashboard 查看效果：
  DATABASE_PATH={db_path} RUN_DISCORD_BOT=false python3 -m src.main

或者用 Docker：
  DATABASE_PATH={db_path} docker compose up -d

打开 http://127.0.0.1:8099 即可看到演示数据。

⚠️  所有数据均为虚构，请勿在生产数据库上运行 --reset 参数。
""")


if __name__ == "__main__":
    main()
