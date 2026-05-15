from __future__ import annotations

import discord

from src.core.settings import Settings
from src.utils.text_utils import strip_discord_mentions


class MessageRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def should_handle_message(self, message: discord.Message, bot_user: discord.ClientUser | None) -> bool:
        if message.author.bot:
            return False
        if not isinstance(message.channel, discord.DMChannel):
            return False
        if self.settings.allowed_channel_ids and int(message.channel.id) not in self.settings.allowed_channel_ids:
            return False
        return True

    def extract_user_content(self, message: discord.Message, bot_user: discord.ClientUser | None) -> str:
        bot_user_id = bot_user.id if bot_user else None
        return strip_discord_mentions(message.content, bot_user_id)
