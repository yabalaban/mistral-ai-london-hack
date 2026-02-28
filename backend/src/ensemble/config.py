from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from backend/ directory
load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")


@dataclass(frozen=True)
class Settings:
    mistral_api_key: str = field(default_factory=lambda: os.environ["MISTRAL_API_KEY"])
    elevenlabs_api_key: str = field(
        default_factory=lambda: os.environ.get("ELEVENLABS_API_KEY", "")
    )
    host: str = "0.0.0.0"
    port: int = 8000
    default_model: str = "mistral-medium-latest"
    oracle_model: str = "mistral-small-latest"


settings = Settings()
