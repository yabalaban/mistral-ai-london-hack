from __future__ import annotations

from pydantic import BaseModel


class AgentProfile(BaseModel):
    """Local agent profile — maps to a Mistral agent once created."""

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
