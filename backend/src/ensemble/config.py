"""Application configuration — loaded from environment variables.

Settings are frozen (immutable) after creation. The ``MISTRAL_API_KEY``
environment variable is required; all others have sensible defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from backend/ directory
# Try backend/.env first, then repo root .env
_backend_dir = Path(__file__).resolve().parent.parent.parent
load_dotenv(_backend_dir / ".env")
load_dotenv(_backend_dir.parent / ".env")


@dataclass(frozen=True)
class Settings:
    """Application-wide configuration.

    Attributes:
        mistral_api_key: API key for Mistral (required).
        elevenlabs_api_key: API key for ElevenLabs TTS (optional).
        host: Bind host for the server.
        port: Bind port for the server.
        default_model: Default Mistral model for agents.
        oracle_model: Mistral model used by the oracle engine.
    """

    mistral_api_key: str = field(default_factory=lambda: os.environ.get("MISTRAL_API_KEY", ""))
    elevenlabs_api_key: str = field(
        default_factory=lambda: os.environ.get("ELEVENLABS_API_KEY", "")
    )
    host: str = "0.0.0.0"
    port: int = 8000
    default_model: str = "mistral-medium-latest"
    oracle_model: str = "ministral-14b-2512"


settings = Settings()
