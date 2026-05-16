from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.exceptions import LLMClientError
from src.core.settings import Settings
from src.llm.client import LLMClient


def _load_settings(temp_dir: Path, *, base_url: str, cache_enabled: bool = True) -> Settings:
    os.environ["DISCORD_BOT_TOKEN"] = "dummy"
    os.environ["LLM_API_KEY"] = "dummy"
    os.environ["LLM_MODEL"] = "claude-sonnet-4-6"
    os.environ["LLM_BASE_URL"] = base_url
    os.environ["LLM_PROMPT_CACHING_ENABLED"] = "true" if cache_enabled else "false"
    os.environ["RUN_DISCORD_BOT"] = "false"
    os.environ["DATABASE_PATH"] = str(temp_dir / "verify.sqlite3")
    os.environ["LOG_FILE_PATH"] = str(temp_dir / "verify.log")
    return Settings.load()


async def _verify_anthropic_cache_payload() -> None:
    with TemporaryDirectory() as raw_temp_dir:
        settings = _load_settings(Path(raw_temp_dir), base_url="https://api.anthropic.com/v1")
        client = LLMClient(settings)
        try:
            system_text = (
                "[System Prompt]\nstatic persona\n\n"
                "[Memory Use Note]\nstatic memory policy\n\n"
                "[Turn Calibration]\nchanges with current turn\n\n"
                "[What You Already Know]\nretrieved memory"
            )
            system_blocks, messages = client._messages_to_anthropic_payload(
                [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": "hello"},
                ]
            )

            assert messages == [
                {"role": "user", "content": [{"type": "text", "text": "hello"}]}
            ]
            assert len(system_blocks) == 2
            assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}
            assert "[System Prompt]" in system_blocks[0]["text"]
            assert "[Memory Use Note]" in system_blocks[0]["text"]
            assert "[Turn Calibration]" not in system_blocks[0]["text"]
            assert "[Turn Calibration]" in system_blocks[1]["text"]
        finally:
            await client.aclose()


async def _verify_openai_responses_payload_stays_openai_shaped() -> None:
    with TemporaryDirectory() as raw_temp_dir:
        settings = _load_settings(Path(raw_temp_dir), base_url="https://api.openai.com/v1")
        client = LLMClient(settings)
        try:
            payload = client._messages_to_responses_input(
                [
                    {"role": "system", "content": "static"},
                    {"role": "user", "content": "hello"},
                ]
            )
            assert payload[0]["content"] == [{"type": "input_text", "text": "static"}]
            assert "cache_control" not in payload[0]["content"][0]
        finally:
            await client.aclose()


async def _verify_anthropic_native_search_rejected() -> None:
    with TemporaryDirectory() as raw_temp_dir:
        settings = _load_settings(Path(raw_temp_dir), base_url="https://api.anthropic.com/v1")
        client = LLMClient(settings)
        try:
            try:
                await client.native_search_completion([{"role": "user", "content": "hello"}])
            except LLMClientError as exc:
                assert "OpenAI Responses-compatible" in str(exc)
            else:
                raise AssertionError(
                    "Anthropic native search should be rejected before making a network request"
                )
        finally:
            await client.aclose()


async def _verify_anthropic_messages_api_without_cache_control() -> None:
    with TemporaryDirectory() as raw_temp_dir:
        settings = _load_settings(Path(raw_temp_dir), base_url="https://api.anthropic.com/v1", cache_enabled=False)
        client = LLMClient(settings)
        try:
            assert client._use_anthropic_messages_api
            system_blocks, _ = client._messages_to_anthropic_payload(
                [
                    {"role": "system", "content": "[System Prompt]\nstatic\n\n[Turn Calibration]\ndynamic"},
                    {"role": "user", "content": "hello"},
                ]
            )
            assert system_blocks == [
                {"type": "text", "text": "[System Prompt]\nstatic\n\n[Turn Calibration]\ndynamic"}
            ]
        finally:
            await client.aclose()


async def main() -> None:
    await _verify_anthropic_cache_payload()
    await _verify_openai_responses_payload_stays_openai_shaped()
    await _verify_anthropic_native_search_rejected()
    await _verify_anthropic_messages_api_without_cache_control()
    print("verify_prompt_caching.py: prompt caching payload checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
