from __future__ import annotations

from io import BytesIO
from pathlib import Path

import discord
from docx import Document
from pypdf import PdfReader

from src.core.settings import Settings
from src.llm.client import LLMClient
from src.product.models import AttachmentInsight
from src.product.store import ProductStore
from src.utils.text_utils import compact_text, truncate_text


class AttachmentService:
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac"}
    DOCUMENT_EXTENSIONS = {".txt", ".pdf", ".docx"}

    def __init__(
        self,
        *,
        settings: Settings,
        llm_client: LLMClient,
        product_store: ProductStore,
    ) -> None:
        self.settings = settings
        self.llm_client = llm_client
        self.product_store = product_store

    async def analyze_attachments(
        self,
        *,
        attachments: list[discord.Attachment],
        user_id: str,
        conversation_id: str,
        platform_message_id: str | None,
    ) -> list[AttachmentInsight]:
        insights: list[AttachmentInsight] = []
        total_chars = 0
        for attachment in attachments:
            try:
                insight = await self._analyze_single_attachment(attachment)
            except Exception as exc:  # noqa: BLE001
                insight = AttachmentInsight(
                    filename=attachment.filename,
                    artifact_type="unknown",
                    content_type=attachment.content_type,
                    extracted_text="",
                    summary_text=f"附件处理失败：{type(exc).__name__}",
                    truncated=False,
                    metadata={"size": attachment.size, "error": str(exc)},
                )
            if not insight:
                continue
            artifact_text = insight.extracted_text if self.settings.attachment_artifact_store_text else ""
            if insight.extracted_text:
                remaining = max(self.settings.attachment_total_char_limit - total_chars, 0)
                if remaining <= 0:
                    insight.extracted_text = ""
                    insight.summary_text = truncate_text(insight.summary_text, 180)
                    insight.truncated = True
                elif len(insight.extracted_text) > remaining:
                    insight.extracted_text = truncate_text(insight.extracted_text, remaining)
                    insight.truncated = True
                total_chars += len(insight.extracted_text)
            self.product_store.record_attachment_artifact(
                platform_message_id=platform_message_id,
                user_id=user_id,
                conversation_id=conversation_id,
                filename=insight.filename,
                content_type=insight.content_type,
                artifact_type=insight.artifact_type,
                extracted_text=artifact_text,
                summary_text=insight.summary_text,
                truncated=insight.truncated,
                metadata=insight.metadata,
            )
            insights.append(insight)
        return insights

    async def analyze_file_payloads(
        self,
        *,
        files: list[dict],
        user_id: str,
        conversation_id: str,
        platform_message_id: str | None,
    ) -> list[AttachmentInsight]:
        insights: list[AttachmentInsight] = []
        total_chars = 0
        for file_payload in files:
            filename = str(file_payload.get("filename") or "attachment")
            content_type = file_payload.get("content_type")
            raw_bytes = bytes(file_payload.get("data") or b"")
            size = int(file_payload.get("size") or len(raw_bytes))
            try:
                insight = await self._analyze_bytes(
                    filename=filename,
                    content_type=None if content_type is None else str(content_type),
                    size=size,
                    raw_bytes=raw_bytes,
                )
            except Exception as exc:  # noqa: BLE001
                insight = AttachmentInsight(
                    filename=filename,
                    artifact_type="unknown",
                    content_type=None if content_type is None else str(content_type),
                    extracted_text="",
                    summary_text=f"附件处理失败：{type(exc).__name__}",
                    truncated=False,
                    metadata={"size": size, "error": str(exc), "source": "mobile_upload"},
                )
            if not insight:
                continue
            artifact_text = insight.extracted_text if self.settings.attachment_artifact_store_text else ""
            if insight.extracted_text:
                remaining = max(self.settings.attachment_total_char_limit - total_chars, 0)
                if remaining <= 0:
                    insight.extracted_text = ""
                    insight.summary_text = truncate_text(insight.summary_text, 180)
                    insight.truncated = True
                elif len(insight.extracted_text) > remaining:
                    insight.extracted_text = truncate_text(insight.extracted_text, remaining)
                    insight.truncated = True
                total_chars += len(insight.extracted_text)
            insight.metadata = {**insight.metadata, "source": "mobile_upload"}
            self.product_store.record_attachment_artifact(
                platform_message_id=platform_message_id,
                user_id=user_id,
                conversation_id=conversation_id,
                filename=insight.filename,
                content_type=insight.content_type,
                artifact_type=insight.artifact_type,
                extracted_text=artifact_text,
                summary_text=insight.summary_text,
                truncated=insight.truncated,
                metadata=insight.metadata,
            )
            insights.append(insight)
        return insights

    def build_context(self, insights: list[AttachmentInsight]) -> str:
        if not insights:
            return ""
        lines = ["本轮附件上下文："]
        for insight in insights:
            lines.append(f"- {insight.context_line()}")
            if insight.extracted_text and insight.extracted_text != insight.summary_text:
                lines.append(f"  参考文本：{truncate_text(insight.extracted_text, 420)}")
        return "\n".join(lines)

    async def _analyze_single_attachment(self, attachment: discord.Attachment) -> AttachmentInsight | None:
        raw_bytes = await attachment.read()
        return await self._analyze_bytes(
            filename=attachment.filename,
            content_type=attachment.content_type,
            size=int(attachment.size or 0),
            raw_bytes=raw_bytes,
        )

    async def _analyze_bytes(
        self,
        *,
        filename: str,
        content_type: str | None,
        size: int,
        raw_bytes: bytes,
    ) -> AttachmentInsight | None:
        suffix = Path(filename).suffix.lower()
        artifact_type = self._artifact_type(content_type, suffix)
        if artifact_type is None:
            return None
        byte_limit = self._byte_limit_for(artifact_type)
        if byte_limit > 0 and size > byte_limit:
            return AttachmentInsight(
                filename=filename,
                artifact_type=artifact_type,
                content_type=content_type,
                extracted_text="",
                summary_text=f"附件超过当前{artifact_type}大小上限，已跳过读取。",
                truncated=True,
                metadata={"size": size, "byte_limit": byte_limit, "skipped_before_read": True},
            )

        if artifact_type == "image":
            summary = await self.llm_client.vision_completion(
                prompt="请抓住图片里最重要、最适合被拿来继续聊天的内容，控制在 120 字以内。",
                image_bytes=raw_bytes,
                mime_type=content_type or "image/png",
                max_tokens=280,
            )
            return AttachmentInsight(
                filename=filename,
                artifact_type="image",
                content_type=content_type,
                extracted_text="",
                summary_text=compact_text(summary),
                metadata={"size": size},
            )

        if artifact_type == "audio":
            transcript = await self.llm_client.transcribe_audio(
                audio_bytes=raw_bytes,
                filename=filename,
                content_type=content_type,
            )
            transcript = compact_text(transcript)
            truncated = len(transcript) > self.settings.attachment_text_char_limit
            transcript = truncate_text(transcript, self.settings.attachment_text_char_limit)
            summary = truncate_text(transcript, 200)
            return AttachmentInsight(
                filename=filename,
                artifact_type="audio",
                content_type=content_type,
                extracted_text=transcript,
                summary_text=summary,
                truncated=truncated,
                metadata={"size": size},
            )

        text = self._extract_document_text(raw_bytes, suffix)
        if not text:
            return AttachmentInsight(
                filename=filename,
                artifact_type="document",
                content_type=content_type,
                extracted_text="",
                summary_text="文档可读取，但没有提取到有效文本。",
                metadata={"size": size},
            )
        text = compact_text(text)
        truncated = len(text) > self.settings.attachment_text_char_limit
        text = truncate_text(text, self.settings.attachment_text_char_limit)
        summary = truncate_text(text, 220)
        return AttachmentInsight(
            filename=filename,
            artifact_type="document",
            content_type=content_type,
            extracted_text=text,
            summary_text=summary,
            truncated=truncated,
            metadata={"size": size},
        )

    def _artifact_type(self, content_type: str | None, suffix: str) -> str | None:
        lowered = (content_type or "").lower()
        if lowered.startswith("image/") or suffix in self.IMAGE_EXTENSIONS:
            return "image"
        if lowered.startswith("audio/") or suffix in self.AUDIO_EXTENSIONS:
            return "audio"
        if lowered.startswith("text/") or suffix in self.DOCUMENT_EXTENSIONS:
            return "document"
        return "document" if suffix else None

    def _byte_limit_for(self, artifact_type: str) -> int:
        global_limit = max(int(self.settings.attachment_max_bytes), 0)
        specific_limit = {
            "image": self.settings.attachment_image_max_bytes,
            "audio": self.settings.attachment_audio_max_bytes,
            "document": self.settings.attachment_document_max_bytes,
        }.get(artifact_type, global_limit)
        specific_limit = max(int(specific_limit), 0)
        if global_limit and specific_limit:
            return min(global_limit, specific_limit)
        return specific_limit or global_limit

    def _extract_document_text(self, raw_bytes: bytes, suffix: str) -> str:
        if suffix == ".txt":
            return raw_bytes.decode("utf-8", errors="ignore")
        if suffix == ".pdf":
            reader = PdfReader(BytesIO(raw_bytes))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if suffix == ".docx":
            document = Document(BytesIO(raw_bytes))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)
        return ""
