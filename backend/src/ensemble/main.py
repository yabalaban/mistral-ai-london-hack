from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from mistralai import Mistral
from starlette.websockets import WebSocketState

from ensemble.agents.registry import AgentRegistry
from ensemble.api import routes
from ensemble.api.ws import handle_conversation_ws
from ensemble.config import settings
from ensemble.conversations.manager import ConversationManager
from ensemble.events import event_bus
from ensemble.oracle.engine import OracleEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = Mistral(api_key=settings.mistral_api_key)
    registry = AgentRegistry(client)
    conversation_mgr = ConversationManager(client, registry)
    oracle = OracleEngine(client, registry)

    # Load agent profiles from disk
    registry.load_profiles(PROFILES_DIR)

    # Create agents on Mistral platform
    await registry.sync_to_mistral()
    logger.info("All agents synced to Mistral")

    # Wire up routes
    routes.init(registry, conversation_mgr, oracle, mistral_client=client)

    # Store refs for WebSocket handler
    app.state.registry = registry
    app.state.conversation_mgr = conversation_mgr
    app.state.oracle = oracle
    app.state.mistral_client = client

    # Optionally start Discord bot as a background task
    discord_task = None
    if settings.discord_bot_token and settings.discord_guild_id:
        try:
            from ensemble.discord_bot import CirclesBot, register_commands

            discord_bot = CirclesBot(
                registry=registry,
                oracle=oracle,
                mistral_client=client,
                guild_id=int(settings.discord_guild_id),
            )
            register_commands(discord_bot)
            discord_task = asyncio.create_task(
                discord_bot.start(settings.discord_bot_token)
            )
            logger.info("Discord bot starting...")
        except Exception:
            logger.exception("Failed to start Discord bot")

    yield

    # Cleanup Discord bot
    if discord_task and not discord_task.done():
        discord_task.cancel()
        try:
            await discord_task
        except (asyncio.CancelledError, Exception):
            pass

    # Cleanup
    await registry.cleanup_mistral()
    logger.info("Mistral agents cleaned up")


app = FastAPI(title="Ensemble", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router)


@app.websocket("/ws/conversations/{conversation_id}")
async def conversation_websocket(ws: WebSocket, conversation_id: str):
    await handle_conversation_ws(
        ws=ws,
        conversation_id=conversation_id,
        conversations=app.state.conversation_mgr._conversations,
        registry=app.state.registry,
        oracle=app.state.oracle,
        mistral_client=app.state.mistral_client,
    )


@app.websocket("/ws/events")
async def events_websocket(ws: WebSocket):
    """Stream all system events to observability dashboard clients."""
    await ws.accept()
    q = event_bus.subscribe()
    try:
        while True:
            event = await q.get()
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json(event.to_dict())
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Events WS error")
    finally:
        event_bus.unsubscribe(q)


@app.get("/health")
async def health():
    return {"status": "ok"}
