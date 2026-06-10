from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import src.product.human_delivery as human_delivery
from src.product.human_delivery import send_human_message_parts, split_human_message_parts
from src.product.streaming import ProgressiveReleaseState, split_markdown_chunks


class FakeTyping:
    def __init__(self, channel: "FakeChannel") -> None:
        self.channel = channel

    async def __aenter__(self) -> None:
        self.channel.typing_entries += 1

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.channel.typing_exits += 1


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.typing_entries = 0
        self.typing_exits = 0

    def typing(self) -> FakeTyping:
        return FakeTyping(self)

    async def send(self, content: str, **kwargs: Any) -> dict[str, Any]:
        message = {"content": content, **kwargs}
        self.sent.append(message)
        return message


def test_progressive_release_waits_for_threshold_or_paragraph_break() -> None:
    state = ProgressiveReleaseState(flush_chars=10, max_silence_ms=10_000)

    assert state.should_release("short") is False
    assert state.should_release("1234567890") is True

    state.mark_released("1234567890")

    assert state.should_release("1234567890") is False
    assert state.should_release("1234567890\n\nnext") is True
    assert state.should_release("1234567890 and more", force=True) is True


def test_progressive_release_flushes_after_silence() -> None:
    state = ProgressiveReleaseState(flush_chars=100, max_silence_ms=1)
    state.last_release_at -= 1

    assert state.should_release("new text") is True


def test_split_markdown_chunks_splits_long_plain_text_without_loss() -> None:
    text = "A" * 95 + "。继续说明。" + "B" * 95

    chunks = split_markdown_chunks(text, limit=90)

    assert len(chunks) >= 3
    assert all(len(chunk) <= 90 for chunk in chunks)
    assert "".join(chunks) == text


def test_split_markdown_chunks_keeps_code_fences_balanced() -> None:
    text = "说明\n```python\n" + "value = 'hello'\n" * 20 + "```\n结束"

    chunks = split_markdown_chunks(text, limit=90)

    assert len(chunks) > 1
    for chunk in chunks:
        fence_count = sum(1 for line in chunk.splitlines() if line.strip().startswith("```"))
        assert fence_count % 2 == 0


def test_split_human_message_parts_handles_empty_paragraphs_and_sentences() -> None:
    assert split_human_message_parts("") == ["..."]
    assert split_human_message_parts("第一段。\n\n第二段。", max_parts=3) == ["第一段。", "第二段。"]
    assert split_human_message_parts("第一句。第二句。第三句。第四句。", max_parts=2) == [
        "第一句。第二句。第三句。第四句。"
    ]

    long_sentence = "这是一句足够长、适合被拆成多段发送的说明。" * 8
    parts = split_human_message_parts(long_sentence, max_parts=2)

    assert len(parts) == 2
    assert "".join(parts) == long_sentence


def test_split_human_message_parts_delegates_structured_content_to_markdown_chunks() -> None:
    text = "- " + "很长的项目说明" * 40

    parts = split_human_message_parts(text, max_parts=3, limit=90)

    assert len(parts) > 1
    assert "".join(parts) == text
    assert all(len(part) <= 90 for part in parts)


def test_send_human_message_parts_preserves_first_reference_and_typing(monkeypatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(human_delivery.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(human_delivery, "_typing_delay_seconds", lambda part, settings: 0.01)
    monkeypatch.setattr(human_delivery, "_part_delay_seconds", lambda settings: 0.02)

    settings = SimpleNamespace(
        human_message_max_parts=3,
        human_presence_enabled=True,
        human_typing_min_ms=0,
        human_typing_max_ms=0,
        human_part_delay_min_ms=0,
        human_part_delay_max_ms=0,
    )
    channel = FakeChannel()

    sent = asyncio.run(
        send_human_message_parts(
            channel,
            "第一段。\n\n第二段。",
            settings=settings,  # type: ignore[arg-type]
            reference="root-message",
            mention_author=True,
        )
    )

    assert sent == channel.sent
    assert [item["content"] for item in channel.sent] == ["第一段。", "第二段。"]
    assert channel.sent[0]["reference"] == "root-message"
    assert channel.sent[1]["reference"] is None
    assert all(item["mention_author"] is True for item in channel.sent)
    assert channel.typing_entries == 2
    assert channel.typing_exits == 2
    assert sleep_calls == [0.01, 0.02, 0.01]
