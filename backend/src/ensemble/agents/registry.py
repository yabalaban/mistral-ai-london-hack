from __future__ import annotations

import json
import logging
from pathlib import Path

from mistralai import Mistral
from mistralai.models import (
    CodeInterpreterTool,
    FunctionTool,
    ImageGenerationTool,
    WebSearchTool,
)

from ensemble.agents.models import AgentProfile
from ensemble.config import settings
from ensemble.tools.slides import SLIDES_TOOL_SCHEMA

BUILT_IN_TOOLS = {
    "code_interpreter": CodeInterpreterTool(type="code_interpreter"),
    "web_search": WebSearchTool(type="web_search"),
    "image_generation": ImageGenerationTool(type="image_generation"),
    "create_slides": FunctionTool(**SLIDES_TOOL_SCHEMA),
}

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Manages agent profiles and their Mistral-side counterparts."""

    def __init__(self, client: Mistral) -> None:
        self._client = client
        self._agents: dict[str, AgentProfile] = {}

    @property
    def agents(self) -> dict[str, AgentProfile]:
        """Return a shallow copy of the agents dict."""
        return dict(self._agents)

    def get(self, agent_id: str) -> AgentProfile | None:
        """Look up an agent profile by ID, returning ``None`` if not found."""
        return self._agents.get(agent_id)

    def load_profiles(self, profiles_dir: Path) -> None:
        """Load agent profiles from JSON files in a directory."""
        if not profiles_dir.exists():
            logger.warning("Profiles directory %s does not exist", profiles_dir)
            return
        for path in sorted(profiles_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                profile = AgentProfile(**data)
                self._agents[profile.id] = profile
                logger.info("Loaded agent profile: %s", profile.id)
            except Exception:
                logger.exception("Failed to load profile from %s", path)

    async def sync_to_mistral(self) -> None:
        """Create or update agents on Mistral platform."""
        for agent_id, profile in self._agents.items():
            if profile.mistral_agent_id:
                continue
            try:
                # Map tool names to Mistral tool objects
                tools = [
                    BUILT_IN_TOOLS[t]
                    for t in profile.tools
                    if t in BUILT_IN_TOOLS
                ] or None

                result = await self._client.beta.agents.create_async(
                    model=profile.model,
                    name=profile.name,
                    instructions=profile.instructions,
                    description=profile.bio,
                    tools=tools,
                )
                profile.mistral_agent_id = result.id
                logger.info(
                    "Created Mistral agent for %s: %s", agent_id, result.id
                )
            except Exception:
                logger.exception("Failed to create Mistral agent for %s", agent_id)

    async def cleanup_mistral(self) -> None:
        """Delete agents from Mistral platform on shutdown."""
        for agent_id, profile in self._agents.items():
            if not profile.mistral_agent_id:
                continue
            try:
                await self._client.beta.agents.delete_async(
                    agent_id=profile.mistral_agent_id
                )
                logger.info("Deleted Mistral agent for %s", agent_id)
            except Exception:
                logger.exception("Failed to delete Mistral agent for %s", agent_id)
