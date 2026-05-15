from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from src.core.exceptions import LLMClientError
from src.core.settings import Settings
from src.utils.json_utils import extract_json_object


logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 700,
        reasoning_effort: str | None = None,
        response_format: dict[str, Any] | None = None,
        use_native_search: bool = False,
    ) -> str:
        if use_native_search:
            if not self.settings.llm_native_search_enabled:
                raise LLMClientError("Native search is disabled for search-style replies")
            try:
                return await self.native_search_completion(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    reasoning_effort=reasoning_effort,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Native search request failed: %s", exc)
                raise LLMClientError("Native search request failed") from exc

        payload: dict[str, Any] = {
            "model": model or self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if response_format:
            payload["response_format"] = response_format

        response = await self._request_completion(payload, allow_retry_without_json=bool(response_format))
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(f"Unexpected completion payload: {response}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("LLM returned empty content")
        return content.strip()

    async def stream_chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 700,
        reasoning_effort: str | None = None,
        use_native_search: bool = False,
    ):
        if use_native_search:
            if not self.settings.llm_native_search_enabled:
                raise LLMClientError("Native search is disabled for search-style replies")
            try:
                text = await self.native_search_completion(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    reasoning_effort=reasoning_effort,
                )
                for chunk in self._chunk_text_for_stream(text):
                    yield chunk
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Native search streaming failed: %s", exc)
                raise LLMClientError("Native search streaming failed") from exc

        payload: dict[str, Any] = {
            "model": model or self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        url = f"{self.settings.llm_base_url}/chat/completions"
        async with self._client.stream(
            "POST",
            url,
            headers=self._build_headers(),
            json=payload,
        ) as response:
            if not response.is_success:
                raise LLMClientError(f"Streaming request failed [{response.status_code}]: {await response.aread()}")
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = payload.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    yield content

    async def json_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 900,
    ) -> dict[str, Any]:
        content = await self.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=model or self.settings.llm_extraction_model or self.settings.llm_model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        try:
            return extract_json_object(content)
        except Exception as exc:  # noqa: BLE001
            raise LLMClientError(f"Failed to parse JSON completion: {content}") from exc

    async def summarize(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 900,
    ) -> str:
        return await self.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=self.settings.llm_summary_model or self.settings.llm_model,
            temperature=0.3,
            max_tokens=max_tokens,
        )

    async def native_search_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 700,
        reasoning_effort: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.settings.llm_model,
            "input": self._messages_to_responses_input(messages),
            "tools": [{"type": self.settings.llm_native_search_tool_type}],
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}

        response = await self._client.post(
            f"{self.settings.llm_base_url}/responses",
            headers=self._build_headers(),
            json=payload,
        )
        if not response.is_success:
            raise LLMClientError(f"Native search request failed [{response.status_code}]: {response.text}")
        data = response.json()
        content = self._extract_response_text(data)
        if not content:
            raise LLMClientError(f"Native search returned empty content: {data}")
        return content.strip()

    async def list_models(self) -> list[str]:
        response = await self._client.get(
            f"{self.settings.llm_base_url}/models",
            headers=self._build_headers(),
        )
        if not response.is_success:
            raise LLMClientError(f"Model list request failed [{response.status_code}]: {response.text}")
        data = response.json()
        return [str(item.get("id")) for item in data.get("data", []) if item.get("id")]

    async def vision_completion(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        max_tokens: int = 500,
    ) -> str:
        image_data = base64.b64encode(image_bytes).decode("utf-8")
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": "你负责提炼图片里和当前聊天最相关的信息，描述要自然、克制、不要胡编。",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
                ],
            },
        ]
        return await self.chat_completion(
            messages,
            model=self.settings.llm_vision_model or self.settings.llm_model,
            temperature=0.2,
            max_tokens=max_tokens,
        )

    async def transcribe_audio(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None = None,
    ) -> str:
        files = {
            "file": (filename, audio_bytes, content_type or "application/octet-stream"),
            "model": (None, self.settings.llm_audio_model or "whisper-1"),
        }
        response = await self._client.post(
            f"{self.settings.llm_base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            files=files,
        )
        if not response.is_success:
            raise LLMClientError(f"Audio transcription failed [{response.status_code}]: {response.text}")
        payload = response.json()
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise LLMClientError("Audio transcription returned empty text")
        return text.strip()

    async def generate_image(
        self,
        *,
        prompt: str,
        output_path: str,
    ) -> str:
        payload = {
            "model": self.settings.llm_image_model or "gpt-image-1",
            "prompt": prompt,
            "size": self.settings.llm_image_size,
        }
        response = await self._client.post(
            f"{self.settings.llm_base_url}/images/generations",
            headers=self._build_headers(),
            json=payload,
        )
        if not response.is_success:
            raise LLMClientError(f"Image generation failed [{response.status_code}]: {response.text}")
        data = response.json().get("data") or []
        if not data:
            raise LLMClientError("Image generation returned no data")
        item = data[0]
        image_bytes: bytes | None = None
        if item.get("b64_json"):
            image_bytes = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            download = await self._client.get(item["url"])
            if not download.is_success:
                raise LLMClientError(f"Generated image download failed [{download.status_code}]")
            image_bytes = download.content
        if not image_bytes:
            raise LLMClientError("Image generation response had neither b64_json nor url")

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image_bytes)
        return str(path)

    async def _request_completion(
        self,
        payload: dict[str, Any],
        *,
        allow_retry_without_json: bool,
    ) -> dict[str, Any]:
        url = f"{self.settings.llm_base_url}/chat/completions"
        response = await self._client.post(url, headers=self._build_headers(), json=payload)
        if response.is_success:
            return response.json()

        if allow_retry_without_json and payload.get("response_format"):
            logger.warning("LLM backend rejected JSON response_format; retrying without it: %s", response.text)
            payload = dict(payload)
            payload.pop("response_format", None)
            response = await self._client.post(url, headers=self._build_headers(), json=payload)
            if response.is_success:
                return response.json()

        if payload.get("reasoning_effort"):
            logger.warning("LLM backend rejected reasoning_effort; retrying without it: %s", response.text)
            payload = dict(payload)
            payload.pop("reasoning_effort", None)
            response = await self._client.post(url, headers=self._build_headers(), json=payload)
            if response.is_success:
                return response.json()

        raise LLMClientError(f"LLM request failed [{response.status_code}]: {response.text}")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

    def _messages_to_responses_input(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role", "user"))
            content = message.get("content", "")
            if isinstance(content, str):
                converted.append(
                    {
                        "role": role,
                        "content": [{"type": "input_text", "text": content}],
                    }
                )
                continue
            if isinstance(content, list):
                response_parts: list[dict[str, Any]] = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text" and part.get("text"):
                        response_parts.append({"type": "input_text", "text": str(part["text"])})
                        continue
                    if part.get("type") == "image_url" and part.get("image_url"):
                        image_url = part["image_url"]
                        url = image_url.get("url") if isinstance(image_url, dict) else None
                        if url:
                            response_parts.append({"type": "input_image", "image_url": url})
                if response_parts:
                    converted.append({"role": role, "content": response_parts})
        return converted

    def _extract_response_text(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        lines: list[str] = []
        for item in payload.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message":
                continue
            for content in item.get("content", []) or []:
                if not isinstance(content, dict):
                    continue
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    lines.append(str(content["text"]))
        return "\n".join(line for line in lines if line.strip())

    def _chunk_text_for_stream(self, text: str) -> list[str]:
        chunks: list[str] = []
        current = ""
        for line in text.splitlines(keepends=True):
            if len(current) + len(line) >= 120 and current:
                chunks.append(current)
                current = line
            else:
                current += line
        if current:
            chunks.append(current)
        return chunks or [text]
