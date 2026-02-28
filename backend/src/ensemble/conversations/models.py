from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ConversationType(str, Enum):
    DIRECT = "direct"
    GROUP = "group"


class MessageRole(str, Enum):
    USER = "user"
    AGENT = "agent"


class Attachment(BaseModel):
    type: str  # "image"
    url: str  # base64 data URL or file URL


class Message(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    role: MessageRole
    agent_id: str | None = None  # which agent sent this (None for user)
    content: str
    attachments: list[Attachment] = []
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Conversation(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: ConversationType
    participant_agent_ids: list[str]
    messages: list[Message] = []
    # Mistral conversation ID (for 1:1 — one per agent; for group — one per agent + oracle)
    mistral_conversation_ids: dict[str, str] = {}  # agent_id -> mistral conv id
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CallStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"


class GroupCall(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    conversation_id: str
    status: CallStatus = CallStatus.ACTIVE
    mode: str = "text"  # "text" | "voice"
