from __future__ import annotations

from src.memory.gating import MemoryGate
from src.memory.models import MessageRecord
from src.persona.immersion_lint import normalize_stage_parentheticals, repair_immersive_voice


def make_message(message_id: int, sender_type: str, content: str) -> MessageRecord:
    return MessageRecord(
        id=message_id,
        platform="test",
        conversation_id="conv-1",
        session_id="session-1",
        platform_message_id=f"msg-{message_id}",
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


def test_memory_gate_detects_stable_fact_and_summary_refresh() -> None:
    gate = MemoryGate(summary_trigger_message_count=3)
    decision = gate.decide(
        turn_messages=[make_message(1, "user", "你以后叫我阿深，我喜欢晚上复盘。")],
        recent_messages=[],
        messages_since_summary=3,
    )

    assert decision.should_extract is True
    assert decision.should_refresh_summary is True
    assert "stable_fact_signal" in decision.reasons
    assert "structured_personal_signal" in decision.reasons


def test_memory_gate_detects_repeated_routine_pattern() -> None:
    gate = MemoryGate()
    decision = gate.decide(
        turn_messages=[make_message(2, "user", "我最近又熬夜了，作息一直乱。")],
        recent_messages=[
            make_message(3, "user", "这周熬夜很多。"),
            make_message(4, "assistant", "我会陪你把节奏收回来。"),
        ],
        messages_since_summary=1,
    )

    assert decision.should_extract is True
    assert "repeated_pattern" in decision.reasons


def test_memory_gate_ignores_short_small_talk_without_signals() -> None:
    decision = MemoryGate().decide(
        turn_messages=[make_message(5, "user", "刚吃完饭。")],
        recent_messages=[],
        messages_since_summary=1,
    )

    assert decision.should_extract is False
    assert decision.should_refresh_summary is False
    assert decision.reasons == []


def test_repair_immersive_voice_removes_third_person_and_tool_leakage() -> None:
    text = "（她这边想到系统提示词）她这边把灯压低一点，然后脑子里就很自然地绕到你那里去了。"

    repaired = repair_immersive_voice(text)

    assert "她这边" not in repaired
    assert "系统" not in repaired
    assert "提示词" not in repaired
    assert "我这边" in repaired or "我把" in repaired
    assert "我就又想到你了" in repaired


def test_normalize_stage_parentheticals_keeps_safe_action_beats() -> None:
    assert normalize_stage_parentheticals("(她把杯子放下) 我回来了。") == "（我把杯子放下） 我回来了。"
