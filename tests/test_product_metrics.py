from __future__ import annotations

from src.memory.models import LongTermMemoryRecord, MessageRecord, RetrievedMemoryContext, StructuredFactRecord
from src.product.metrics import ExperienceMetricsService
from src.product.models import AttachmentInsight, ReplyPlan, SearchDigest, SearchDigestItem


def message(content: str, sender_type: str = "assistant") -> MessageRecord:
    return MessageRecord(
        id=1,
        platform="test",
        conversation_id="conv-1",
        session_id="session-1",
        platform_message_id="msg-1",
        sender_type=sender_type,
        author_id=sender_type,
        user_id="user-1",
        channel_id="channel-1",
        guild_id=None,
        reply_to_platform_message_id=None,
        thread_id=None,
        content=content,
        metadata={},
        created_at="2026-04-28T10:00:00+00:00",
    )


def long_term(content: str) -> LongTermMemoryRecord:
    return LongTermMemoryRecord(
        id=1,
        memory_uid="mem-1",
        user_id="user-1",
        conversation_id="conv-1",
        channel_id="channel-1",
        guild_id=None,
        memory_type="study_context",
        category="routine",
        content=content,
        tags=["study"],
        source_message_ids=[1],
        confidence=0.9,
        importance=0.8,
        status="active",
        last_used_at=None,
        supersedes_memory_uid=None,
        metadata={},
        created_at="2026-04-28T10:00:00+00:00",
        updated_at="2026-04-28T10:00:00+00:00",
    )


def fact(value: str) -> StructuredFactRecord:
    return StructuredFactRecord(
        id=1,
        user_id="user-1",
        namespace="study",
        key="goal",
        value=value,
        confidence=0.9,
        source_message_ids=[1],
        status="active",
        metadata={},
        created_at="2026-04-28T10:00:00+00:00",
        updated_at="2026-04-28T10:00:00+00:00",
    )


def plan(scene: str = "学习辅导") -> ReplyPlan:
    return ReplyPlan(
        request_type="chat",
        scene=scene,
        reply_goal="陪用户推进学习",
        mood="steady",
        rhythm="calm",
        should_search=False,
        should_draw=False,
        learning_mode=True,
        mode_text="auto",
        preferred_length="medium",
        system_note="",
        user_note="",
    )


def test_attachment_and_search_digest_context_lines() -> None:
    assert AttachmentInsight(
        filename="notes.txt",
        artifact_type="document",
        content_type="text/plain",
        extracted_text="",
        summary_text="周三复盘重点",
    ).context_line() == "notes.txt（document）：周三复盘重点"

    digest = SearchDigest(
        query="学习计划",
        items=[SearchDigestItem(title="计划法", snippet="先拆目标", url="https://example.com/plan")],
    )
    assert digest.to_context_block() == "搜索主题：学习计划\n- 计划法：先拆目标 (https://example.com/plan)"


def test_experience_metrics_rewards_memory_use_and_detects_structure() -> None:
    context = RetrievedMemoryContext(
        recent_messages=[message("别怕，你已经很棒了")],
        session_memories=[],
        long_term_memories=[long_term("用户每晚练习雅思口语")],
        structured_facts=[fact("目标是雅思口语 7 分")],
        relationship_states=[],
        summary=None,
    )

    metrics = ExperienceMetricsService().evaluate(
        reply_text="我记着：用户每晚练习雅思口语。今晚先做 20 分钟。\n- 先读题\n- 再复盘",
        memory_context=context,
        plan=plan(),
        search_used=False,
        proactive_acceptance=0.5,
    )

    assert metrics["structure_type"] == "list"
    assert metrics["memory_hit_quality"] > 0.35
    assert metrics["memory_usage_rate"] > 0
    assert metrics["persona_consistency"] > 0.8
    assert metrics["proactive_acceptance"] == 0.5


def test_experience_metrics_penalizes_tool_trace_and_ai_voice() -> None:
    context = RetrievedMemoryContext(
        recent_messages=[],
        session_memories=[],
        long_term_memories=[],
        structured_facts=[],
        relationship_states=[],
        summary=None,
    )

    metrics = ExperienceMetricsService().evaluate(
        reply_text="作为AI，我调用工具后根据搜索给你一个答案。",
        memory_context=context,
        plan=plan(scene="情绪安慰"),
        search_used=True,
    )

    assert metrics["tool_trace_leakage_rate"] > 0
    assert metrics["persona_consistency"] < 0.6
    assert metrics["memory_hit_quality"] == 0
