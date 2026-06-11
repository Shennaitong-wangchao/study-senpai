"""Discord 文本命令处理器测试。"""
from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.commands import CommandRouter, HELP_TEXT
from src.db.database import Database


@pytest.fixture()
def command_router(tmp_path) -> Iterator[CommandRouter]:
    db = Database(str(tmp_path / "cmd_test.sqlite3"))
    db.initialize()
    try:
        yield CommandRouter(db=db)
    finally:
        db.close()


def _make_message(content: str, user_id: str = "user-123", channel_id: str = "chan-456") -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.author.id = int(user_id.replace("user-", "")) if user_id.replace("user-", "").isdigit() else 123
    msg.channel.id = int(channel_id.replace("chan-", "")) if channel_id.replace("chan-", "").isdigit() else 456
    return msg


def test_is_command_detects_slash_prefix(command_router: CommandRouter) -> None:
    assert command_router.is_command("/help") is True
    assert command_router.is_command("/goals") is True
    assert command_router.is_command("hello world") is False
    assert command_router.is_command("") is False


@pytest.mark.anyio
async def test_help_command_returns_text(command_router: CommandRouter) -> None:
    msg = _make_message("/help")
    result = await command_router.handle_command(msg)
    assert result is not None
    assert "help" in result.lower() or "命令" in result


@pytest.mark.anyio
async def test_stats_command_returns_stats(command_router: CommandRouter) -> None:
    msg = _make_message("/stats")
    result = await command_router.handle_command(msg)
    assert result is not None
    assert "天" in result or "streak" in result.lower() or "学习" in result


@pytest.mark.anyio
async def test_goals_empty_returns_prompt(command_router: CommandRouter) -> None:
    msg = _make_message("/goals")
    result = await command_router.handle_command(msg)
    assert result is not None
    assert "addgoal" in result.lower() or "目标" in result


@pytest.mark.anyio
async def test_addgoal_creates_goal(command_router: CommandRouter) -> None:
    msg = _make_message("/addgoal 高考数学备考 | 数学")
    result = await command_router.handle_command(msg)
    assert result is not None
    assert "高考数学备考" in result or "✅" in result

    # 再次查询目标列表
    msg2 = _make_message("/goals")
    result2 = await command_router.handle_command(msg2)
    assert result2 is not None
    assert "高考数学备考" in result2


@pytest.mark.anyio
async def test_addgoal_missing_args_returns_usage(command_router: CommandRouter) -> None:
    msg = _make_message("/addgoal")
    result = await command_router.handle_command(msg)
    assert result is not None
    assert "addgoal" in result.lower() or "用法" in result


@pytest.mark.anyio
async def test_addcard_creates_card(command_router: CommandRouter) -> None:
    msg = _make_message("/addcard 牛顿第一定律 | 惯性定律")
    result = await command_router.handle_command(msg)
    assert result is not None
    assert "牛顿第一定律" in result or "✅" in result


@pytest.mark.anyio
async def test_addcard_missing_separator_returns_usage(command_router: CommandRouter) -> None:
    msg = _make_message("/addcard 没有分隔符")
    result = await command_router.handle_command(msg)
    assert result is not None
    assert "addcard" in result.lower() or "用法" in result


@pytest.mark.anyio
async def test_review_empty_returns_empty_message(command_router: CommandRouter) -> None:
    msg = _make_message("/review")
    result = await command_router.handle_command(msg)
    assert result is not None
    assert "到期" in result or "完成" in result or "addcard" in result.lower()


@pytest.mark.anyio
async def test_unknown_command_returns_none(command_router: CommandRouter) -> None:
    msg = _make_message("/unknowncmd")
    result = await command_router.handle_command(msg)
    assert result is None


@pytest.mark.anyio
async def test_non_command_returns_none(command_router: CommandRouter) -> None:
    msg = _make_message("普通消息，不是命令")
    result = await command_router.handle_command(msg)
    assert result is None
