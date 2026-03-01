"""Entrypoint for the Discord bot frontend.

Shares the same backend (Mistral agents, oracle, registry) as the FastAPI app
but presents it through Discord instead of WebSocket + Preact.

Usage:
    cd backend && PYTHONPATH=src uv run python -m ensemble.discord_main

Both frontends can run simultaneously — they share no mutable state.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from mistralai import Mistral

from ensemble.agents.registry import AgentRegistry
from ensemble.config import settings
from ensemble.discord_bot import CirclesBot, register_commands
from ensemble.oracle.engine import OracleEngine

# Load .env
_backend_dir = Path(__file__).resolve().parent.parent.parent
load_dotenv(_backend_dir / ".env")
load_dotenv(_backend_dir.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


def main() -> None:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    guild_id_str = os.environ.get("DISCORD_GUILD_ID", "")

    if not token:
        logger.error("DISCORD_BOT_TOKEN not set")
        return
    if not guild_id_str:
        logger.error("DISCORD_GUILD_ID not set")
        return

    guild_id = int(guild_id_str)

    # Initialise shared backend (same as FastAPI lifespan)
    client = Mistral(api_key=settings.mistral_api_key)
    registry = AgentRegistry(client)
    oracle = OracleEngine(client, registry)

    registry.load_profiles(PROFILES_DIR)

    # Create bot — sync agents in on_ready to avoid blocking the event loop
    bot = CirclesBot(registry, oracle, client, guild_id)
    register_commands(bot)

    original_on_ready = bot.on_ready

    @bot.event
    async def on_ready():
        # Sync agents to Mistral on first ready
        if not any(a.mistral_agent_id for a in registry.agents.values()):
            await registry.sync_to_mistral()
            logger.info("All agents synced to Mistral")
        await original_on_ready()

    bot.run(token)


if __name__ == "__main__":
    main()
