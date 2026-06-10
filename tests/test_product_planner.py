from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.memory.models import MessageRecord, RetrievedMemoryContext
from src.product.models import ModeState
from src.product.planner import ReplyPlanner


def message_at(created_at: datetime) -> MessageRecord:
    return MessageRecord(
        id=1,
        platform="test",
        conversation_id="conv-1",
        session_id="session-1",
        platform_message_id="msg-1",
        sender_type="user",
        author_id="user-1",
        user_id="user-1",
        channel_id="channel-1",
        guild_id=None,
        reply_to_platform_message_id=None,
        thread_id=None,
        content="hello",
        metadata={},
        created_at=created_at.isoformat(),
    )


def context_with_messages(*messages: MessageRecord) -> RetrievedMemoryContext:
    return RetrievedMemoryContext(
        recent_messages=list(messages),
        session_memories=[],
        long_term_memories=[],
        structured_facts=[],
        relationship_states=[],
        summary=None,
    )


def plan_for(
    user_input: str,
    *,
    mode_state: ModeState | None = None,
    attachment_count: int = 0,
    memory_context: RetrievedMemoryContext | None = None,
):
    return ReplyPlanner().plan(
        user_input=user_input,
        memory_context=memory_context or context_with_messages(),
        mode_state=mode_state or ModeState(),
        attachment_count=attachment_count,
    )


def test_planner_detects_search_intent_and_multimodal_context() -> None:
    plan = plan_for("帮我查一下最新政策资料", attachment_count=2)

    assert plan.request_type == "search"
    assert plan.should_search is True
    assert plan.should_draw is False
    assert plan.preferred_length == "medium_structured"
    assert "搜索型回复" in plan.system_note
    assert "本轮带了 2 个附件" in plan.system_note
    assert "multimodal" in plan.strategy_tags


def test_planner_detects_draw_intent_before_search_or_chat() -> None:
    plan = plan_for("帮我画一张复习计划图")

    assert plan.request_type == "draw"
    assert plan.should_draw is True
    assert plan.should_search is False
    assert plan.preferred_length == "short"
    assert "绘图型回复" in plan.system_note


def test_learning_mode_forces_study_scene_and_goal() -> None:
    plan = plan_for("我没开始复习，督促我", mode_state=ModeState(mode="fast", learning_mode=True))

    assert plan.scene == "学习辅导"
    assert plan.reply_goal == "督促"
    assert plan.mood == "专注"
    assert plan.learning_mode is True
    assert plan.mode_text == "fast+study"
    assert "study_mode" in plan.strategy_tags
    assert "学习模式已开启" in plan.system_note


def test_boundary_scene_takes_priority_over_emotional_tokens() -> None:
    plan = plan_for("别再追问我了，我现在有点烦")

    assert plan.scene == "边界收束"
    assert plan.reply_goal == "边界收束"
    assert plan.user_note.endswith("边界要清楚，但语气仍然是同一个人。")


def test_planner_marks_dense_and_sparse_conversation_rhythm() -> None:
    base = datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc)
    dense = context_with_messages(message_at(base), message_at(base + timedelta(minutes=3)))
    sparse = context_with_messages(message_at(base), message_at(base + timedelta(hours=13)))

    assert plan_for("讲讲这个公式", memory_context=dense).rhythm == "密集"
    assert plan_for("今天复习一下", memory_context=sparse).rhythm == "稀疏"
