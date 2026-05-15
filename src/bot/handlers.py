from __future__ import annotations

import logging
from typing import Any

import discord

from src.bot.message_router import MessageRouter
from src.services.companion_service import CompanionService


logger = logging.getLogger(__name__)


class DiscordMessageHandler:
    def __init__(
        self,
        *,
        router: MessageRouter,
        companion_service: CompanionService,
    ) -> None:
        self.router = router
        self.companion_service = companion_service

    async def handle_message(self, client: discord.Client, message: discord.Message) -> None:
        if not self.router.should_handle_message(message, client.user):
            return

        user_content = self.router.extract_user_content(message, client.user)
        if not user_content and not message.attachments:
            return

        try:
            async with message.channel.typing():
                await self.companion_service.handle_message(client, message, user_content=user_content)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to handle Discord message %s", message.id)
            self.companion_service.product_store.record_error(
                component="discord_message_handler",
                message="Failed to handle incoming user message",
                details={
                    "message_id": str(message.id),
                    "user_id": str(message.author.id),
                    "channel_id": str(message.channel.id),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            await message.channel.send("抱歉，我刚刚有点走神了，能再说一次吗？")
