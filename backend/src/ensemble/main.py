from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mistralai import Mistral

from ensemble.agents.registry import AgentRegistry
from ensemble.api import routes
from ensemble.config import settings
from ensemble.conversations.manager import ConversationManager
from ensemble.oracle.engine import OracleEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "agents"


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
    routes.init(registry, conversation_mgr, oracle)

    yield

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


@app.get("/health")
async def health():
    return {"status": "ok"}
