"""NanoClaw Discord Bot — entry point."""
import logging
import os
import sys

import discord

from config.settings import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("nanoclaw")


def main():
    settings_path = os.environ.get("NANOCLAW_SETTINGS", "config/settings.json")
    try:
        settings = Settings.load(settings_path)
    except Exception as e:
        logger.error("Failed to load settings from %s: %s", settings_path, e)
        sys.exit(1)

    intents = discord.Intents.default()
    intents.message_content = True
    intents.reactions = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        logger.info("NanoClaw online as %s", client.user)

    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("DISCORD_BOT_TOKEN not set in environment")
        sys.exit(1)

    client.run(token)


if __name__ == "__main__":
    main()
