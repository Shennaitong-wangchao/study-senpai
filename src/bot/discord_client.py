from __future__ import annotations

import logging

import discord

from src.bot.handlers import DiscordMessageHandler


logger = logging.getLogger(__name__)


class ShenZhiweiDiscordClient(discord.Client):
    def __init__(self, *, handler: DiscordMessageHandler) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        super().__init__(intents=intents)
        self.handler = handler

    async def on_ready(self) -> None:
        logger.info("Discord client ready as %s (%s)", self.user, self.user.id if self.user else "unknown")

    async def on_message(self, message: discord.Message) -> None:
        await self.handler.handle_message(self, message)
