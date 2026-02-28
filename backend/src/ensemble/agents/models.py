"""Agent profile model — defines an AI agent's identity and capabilities."""

from __future__ import annotations

from pydantic import BaseModel


class AgentProfile(BaseModel):
    """Local agent profile — maps to a Mistral agent once created.

    Attributes:
        id: Unique identifier (e.g. ``"emma"``).
        name: Display name.
        role: Short role description (e.g. ``"Software Engineer"``).
        bio: Longer biography text.
        personality: Personality traits description.
        instructions: System prompt / instructions for the Mistral agent.
        voice_id: Optional ElevenLabs voice ID for TTS.
        model: Mistral model to use.
        tools: List of tool names the agent can use.
        avatar_url: Optional URL to the agent's avatar image.
        mistral_agent_id: Populated after the agent is created on Mistral.
    """

    id: str
    name: str
    role: str
    bio: str
    personality: str
    instructions: str
    voice_id: str = ""
    model: str = "mistral-medium-latest"
    tools: list[str] = []
    avatar_url: str = ""

    # Populated after Mistral agent creation
    mistral_agent_id: str | None = None
