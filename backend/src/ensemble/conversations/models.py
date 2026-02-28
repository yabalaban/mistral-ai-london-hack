"""Pydantic models for conversations, messages, and attachments."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ConversationType(str, Enum):
    """Whether a conversation is a 1:1 direct chat or a group discussion."""

    DIRECT = "direct"
    GROUP = "group"


class MessageRole(str, Enum):
    """Who sent a message — the human user or an AI agent."""

    USER = "user"
    AGENT = "agent"


class Attachment(BaseModel):
    """A file or media attachment on a message (e.g. an image)."""

    type: str  # "image"
    url: str  # base64 data URL or file URL


class Message(BaseModel):
    """A single message in a conversation."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    role: MessageRole
    agent_id: str | None = None  # which agent sent this (None for user)
    content: str
    attachments: list[Attachment] = []
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Conversation(BaseModel):
    """A conversation between a user and one or more agents.

    For direct conversations, ``participant_agent_ids`` has exactly one entry.
    For group conversations, the oracle decides turn order among participants.

    Each agent maintains its own Mistral conversation context, tracked via
    ``mistral_conversation_ids``.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: ConversationType
    participant_agent_ids: list[str]
    messages: list[Message] = []
    mistral_conversation_ids: dict[str, str] = {}  # agent_id -> mistral conv id
    topic: str | None = None  # Thread topic — set from first user message
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CallStatus(str, Enum):
    """Whether a group call is currently active or has ended."""

    ACTIVE = "active"
    ENDED = "ended"


class GroupCall(BaseModel):
    """Tracks a voice/text group call session within a conversation."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    conversation_id: str
    status: CallStatus = CallStatus.ACTIVE
    mode: str = "text"  # "text" | "voice"
