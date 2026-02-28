"""Structured JSONL turn logging for oracle decisions."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
LOG_FILE = LOG_DIR / "turns.jsonl"


@dataclass
class RoundRecord:
    round: int
    mode: str
    ranking: list[dict] = field(default_factory=list)
    agent_responses: list[dict] = field(default_factory=list)
    grader: dict | None = None


@dataclass
class TurnRecord:
    conversation_id: str
    user_message: str
    topic: str | None = None
    goal: str | None = None
    directed: bool = False
    directed_agent: str | None = None
    rounds: list[RoundRecord] = field(default_factory=list)
    summary: str | None = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def log_turn(record: TurnRecord) -> None:
    """Append a turn record as JSON to the JSONL log file."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(asdict(record), default=str) + "\n")
    except Exception:
        logger.exception("Failed to write turn log")
