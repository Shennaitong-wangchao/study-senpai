from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from src.product.attachments import AttachmentService
from src.product.models import AttachmentInsight


class FakeAttachmentLLM:
    def __init__(self) -> None:
        self.vision_calls: list[dict[str, Any]] = []
        self.audio_calls: list[dict[str, Any]] = []

    async def vision_completion(self, **kwargs: Any) -> str:
        self.vision_calls.append(kwargs)
        return "  图片里有 一张 清晰的 学习计划 截图  "

    async def transcribe_audio(self, **kwargs: Any) -> str:
        self.audio_calls.append(kwargs)
        return "  今天 复习 英语 听力 并 做 错题  "


class FakeAttachmentStore:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_attachment_artifact(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


def attachment_settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "attachment_artifact_store_text": True,
        "attachment_total_char_limit": 120,
        "attachment_text_char_limit": 80,
        "attachment_max_bytes": 1024,
        "attachment_image_max_bytes": 1024,
        "attachment_audio_max_bytes": 1024,
        "attachment_document_max_bytes": 1024,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def attachment_service(**settings_overrides: Any) -> tuple[AttachmentService, FakeAttachmentLLM, FakeAttachmentStore]:
    llm = FakeAttachmentLLM()
    store = FakeAttachmentStore()
    service = AttachmentService(
        settings=attachment_settings(**settings_overrides),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        product_store=store,  # type: ignore[arg-type]
    )
    return service, llm, store


def test_analyze_file_payloads_extracts_text_and_records_mobile_source() -> None:
    service, llm, store = attachment_service(attachment_text_char_limit=20)

    insights = asyncio.run(
        service.analyze_file_payloads(
            files=[
                {
                    "filename": "notes.txt",
                    "content_type": "text/plain",
                    "data": "第一段\n第二段\n第三段".encode("utf-8"),
                }
            ],
            user_id="user-1",
            conversation_id="conv-1",
            platform_message_id="mobile-msg-1",
        )
    )

    assert len(insights) == 1
    assert insights[0].filename == "notes.txt"
    assert insights[0].artifact_type == "document"
    assert insights[0].extracted_text == "第一段 第二段 第三段"
    assert insights[0].summary_text == "第一段 第二段 第三段"
    assert insights[0].metadata == {"size": 29, "source": "mobile_upload"}
    assert llm.vision_calls == []
    assert llm.audio_calls == []
    assert store.records[0]["platform_message_id"] == "mobile-msg-1"
    assert store.records[0]["extracted_text"] == "第一段 第二段 第三段"
    assert store.records[0]["metadata"] == {"size": 29, "source": "mobile_upload"}


def test_analyze_file_payloads_applies_total_context_limit_without_losing_artifact_storage() -> None:
    service, _, store = attachment_service(attachment_total_char_limit=10, attachment_text_char_limit=80)

    insights = asyncio.run(
        service.analyze_file_payloads(
            files=[
                {"filename": "first.txt", "content_type": "text/plain", "data": b"abcdefghij"},
                {"filename": "second.txt", "content_type": "text/plain", "data": b"klmnopqrst"},
            ],
            user_id="user-1",
            conversation_id="conv-1",
            platform_message_id="mobile-msg-2",
        )
    )

    assert [item.extracted_text for item in insights] == ["abcdefghij", ""]
    assert [item.truncated for item in insights] == [False, True]
    assert store.records[0]["extracted_text"] == "abcdefghij"
    assert store.records[1]["extracted_text"] == "klmnopqrst"


def test_analyze_file_payloads_skips_oversized_document_before_reading_text() -> None:
    service, _, store = attachment_service(
        attachment_artifact_store_text=False,
        attachment_max_bytes=0,
        attachment_document_max_bytes=4,
    )

    insights = asyncio.run(
        service.analyze_file_payloads(
            files=[{"filename": "large.txt", "content_type": "text/plain", "size": 10, "data": b"0123456789"}],
            user_id="user-1",
            conversation_id="conv-1",
            platform_message_id=None,
        )
    )

    assert len(insights) == 1
    assert insights[0].summary_text == "附件超过当前document大小上限，已跳过读取。"
    assert insights[0].truncated is True
    assert insights[0].metadata == {
        "size": 10,
        "byte_limit": 4,
        "skipped_before_read": True,
        "source": "mobile_upload",
    }
    assert store.records[0]["extracted_text"] == ""


def test_analyze_file_payloads_uses_vision_and_audio_models() -> None:
    service, llm, _ = attachment_service(attachment_text_char_limit=12)

    insights = asyncio.run(
        service.analyze_file_payloads(
            files=[
                {"filename": "plan.png", "content_type": "image/png", "data": b"fake-image"},
                {"filename": "voice.m4a", "content_type": "audio/mp4", "data": b"fake-audio"},
            ],
            user_id="user-1",
            conversation_id="conv-1",
            platform_message_id="mobile-msg-3",
        )
    )

    assert [(item.filename, item.artifact_type, item.summary_text) for item in insights] == [
        ("plan.png", "image", "图片里有 一张 清晰的 学习计划 截图"),
        ("voice.m4a", "audio", "今天 复习 英语 听力…"),
    ]
    assert insights[0].extracted_text == ""
    assert insights[1].extracted_text == "今天 复习 英语 听力…"
    assert llm.vision_calls[0]["mime_type"] == "image/png"
    assert llm.vision_calls[0]["image_bytes"] == b"fake-image"
    assert llm.audio_calls[0]["filename"] == "voice.m4a"
    assert llm.audio_calls[0]["audio_bytes"] == b"fake-audio"


def test_build_context_includes_summary_and_distinct_reference_text() -> None:
    service, _, _ = attachment_service()

    context = service.build_context(
        [
            AttachmentInsight(
                filename="notes.txt",
                artifact_type="document",
                content_type="text/plain",
                extracted_text="完整参考文本比摘要更长",
                summary_text="摘要",
            )
        ]
    )

    assert context == "本轮附件上下文：\n- notes.txt（document）：摘要\n  参考文本：完整参考文本比摘要更长"
    assert service.build_context([]) == ""
