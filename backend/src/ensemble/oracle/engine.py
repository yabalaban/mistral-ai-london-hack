"""Oracle engine using Mistral native handoffs.

Instead of manually routing between agents, we create:
- An oracle agent with handoffs to all participant agents
- Each participant agent with cross-handoffs to all other participants
- One Mistral Conversation per group — Mistral handles all orchestration

The oracle's job is simple: receive the user's message and hand off to
the most relevant agent. That agent responds and can hand off to the next.
"""

from __future__ import annotations

import logging
from typing import Any

from mistralai import Mistral

from ensemble.agents.registry import AgentRegistry
from ensemble.config import settings
from ensemble.conversations.models import (
    Attachment,
    Conversation,
    Message,
    MessageRole,
)
from ensemble.utils import build_inputs, extract_text_from_content

logger = logging.getLogger(__name__)

ORACLE_INSTRUCTIONS = """\
You are an invisible conversation moderator for a group discussion.

Participants:
{participants}

Rules:
- When a user sends a message, hand off to the most relevant participant first.
- Do NOT answer yourself — always hand off.
- The participants will hand off to each other after responding.
- You are invisible to the user.
"""


class OracleEngine:
    """Orchestrates group conversations using Mistral native handoffs."""

    def __init__(self, client: Mistral, registry: AgentRegistry) -> None:
        self._client = client
        self._registry = registry
        # Oracle Mistral agent IDs per group conversation
        self._oracle_agents: dict[str, str] = {}  # conv_id -> oracle mistral agent id

    async def setup_group(self, conversation: Conversation) -> str:
        """Create an oracle agent with handoffs for a group conversation.

        Sets up cross-handoffs between all participant agents.
        Returns the oracle's Mistral agent ID.
        """
        agent_ids = conversation.participant_agent_ids
        mistral_ids = []
        for aid in agent_ids:
            agent = self._registry.get(aid)
            if agent and agent.mistral_agent_id:
                mistral_ids.append((aid, agent.mistral_agent_id))

        if len(mistral_ids) < 2:
            raise ValueError("Need at least 2 ready agents for a group")

        # Set up cross-handoffs: each agent can hand off to all others
        for i, (aid, mid) in enumerate(mistral_ids):
            other_ids = [m for j, (_, m) in enumerate(mistral_ids) if j != i]
            try:
                await self._client.beta.agents.update_async(
                    agent_id=mid,
                    handoffs=other_ids,
                )
                logger.info("Set handoffs for %s → %d others", aid, len(other_ids))
            except Exception:
                logger.exception("Failed to set handoffs for %s", aid)

        # Create oracle agent
        participants_desc = []
        for aid, mid in mistral_ids:
            agent = self._registry.get(aid)
            if agent:
                participants_desc.append(f"- {agent.name}: {agent.role}. {agent.personality}")

        oracle = await self._client.beta.agents.create_async(
            model=settings.oracle_model,
            name="Oracle",
            instructions=ORACLE_INSTRUCTIONS.format(
                participants="\n".join(participants_desc)
            ),
            handoffs=[mid for _, mid in mistral_ids],
        )

        self._oracle_agents[conversation.id] = oracle.id
        logger.info("Created oracle %s for conversation %s", oracle.id, conversation.id)
        return oracle.id

    async def run_group_turn(
        self,
        conversation: Conversation,
        content: str,
        attachments: list[Attachment] | None = None,
        max_rounds: int = 1,
    ) -> list[Message]:
        """Run a group conversation turn using native handoffs.

        Returns the list of agent messages generated.
        """
        # Record user message
        user_msg = Message(
            role=MessageRole.USER,
            content=content,
            attachments=attachments or [],
        )
        conversation.messages.append(user_msg)

        # Ensure oracle is set up
        oracle_id = self._oracle_agents.get(conversation.id)
        if not oracle_id:
            oracle_id = await self.setup_group(conversation)

        # Build inputs
        inputs = build_inputs(content, attachments)

        # Start or continue Mistral conversation
        mistral_conv_id = conversation.mistral_conversation_ids.get("__group__")
        if mistral_conv_id:
            response = await self._client.beta.conversations.append_async(
                conversation_id=mistral_conv_id,
                inputs=inputs,
                handoff_execution="server",
            )
        else:
            response = await self._client.beta.conversations.start_async(
                agent_id=oracle_id,
                inputs=inputs,
                handoff_execution="server",
            )

        conversation.mistral_conversation_ids["__group__"] = response.conversation_id

        # Parse outputs — extract messages and handoffs
        agent_messages: list[Message] = []
        for output in response.outputs:
            otype = type(output).__name__

            if otype == "MessageOutputEntry":
                text = extract_text_from_content(output.content)
                if text:
                    # Map Mistral agent ID back to our agent ID
                    mistral_aid = getattr(output, "agent_id", None)
                    our_aid = self._resolve_agent_id(mistral_aid)
                    msg = Message(
                        role=MessageRole.AGENT,
                        agent_id=our_aid,
                        content=text,
                    )
                    conversation.messages.append(msg)
                    agent_messages.append(msg)

            elif otype == "AgentHandoffEntry":
                # Log handoff for debugging / UI
                prev = getattr(output, "previous_agent_name", "?")
                next_name = getattr(output, "next_agent_name", "?")
                logger.info("Handoff: %s → %s", prev, next_name)

        return agent_messages

    async def run_group_turn_streaming(
        self,
        conversation: Conversation,
        content: str,
        attachments: list[Attachment] | None = None,
    ):
        """Generator that yields (event_type, data) for streaming group turns.

        Yields:
            ("handoff", {"from": "name", "to": "name", "agent_id": "our_id"})
            ("chunk", {"agent_id": "our_id", "content": "text"})
            ("message", Message)
        """
        # Record user message
        user_msg = Message(
            role=MessageRole.USER,
            content=content,
            attachments=attachments or [],
        )
        conversation.messages.append(user_msg)

        # Ensure oracle
        oracle_id = self._oracle_agents.get(conversation.id)
        if not oracle_id:
            oracle_id = await self.setup_group(conversation)

        # Build inputs
        inputs = build_inputs(content, attachments)

        # Stream
        mistral_conv_id = conversation.mistral_conversation_ids.get("__group__")
        if mistral_conv_id:
            stream = await self._client.beta.conversations.append_stream_async(
                conversation_id=mistral_conv_id,
                inputs=inputs,
                handoff_execution="server",
            )
        else:
            stream = await self._client.beta.conversations.start_stream_async(
                agent_id=oracle_id,
                inputs=inputs,
                handoff_execution="server",
            )

        current_agent_id = None
        current_text = ""

        async for event in stream:
            data = event.data
            dtype = type(data).__name__

            # Capture conversation ID
            if hasattr(data, "conversation_id") and data.conversation_id:
                conversation.mistral_conversation_ids["__group__"] = data.conversation_id

            if "Handoff" in dtype:
                # Emit any pending message before handoff
                if current_text and current_agent_id:
                    msg = Message(
                        role=MessageRole.AGENT,
                        agent_id=current_agent_id,
                        content=current_text,
                    )
                    conversation.messages.append(msg)
                    yield ("message", msg)
                    current_text = ""

                prev = getattr(data, "previous_agent_name", "?")
                next_name = getattr(data, "next_agent_name", "?")
                next_mid = getattr(data, "next_agent_id", None)
                current_agent_id = self._resolve_agent_id(next_mid)
                yield ("handoff", {
                    "from": prev,
                    "to": next_name,
                    "agent_id": current_agent_id,
                })

            elif hasattr(data, "content"):
                text = extract_text_from_content(getattr(data, "content", ""))
                if text:
                    current_text += text
                    yield ("chunk", {
                        "agent_id": current_agent_id,
                        "content": text,
                    })

        # Emit final message
        if current_text and current_agent_id:
            msg = Message(
                role=MessageRole.AGENT,
                agent_id=current_agent_id,
                content=current_text,
            )
            conversation.messages.append(msg)
            yield ("message", msg)

    def _resolve_agent_id(self, mistral_agent_id: str | None) -> str | None:
        """Map a Mistral agent ID back to our local agent ID."""
        if not mistral_agent_id:
            return None
        for aid, profile in self._registry.agents.items():
            if profile.mistral_agent_id == mistral_agent_id:
                return aid
        return mistral_agent_id  # fallback to Mistral ID

    async def cleanup(self) -> None:
        """Delete oracle agents on shutdown."""
        for conv_id, oracle_id in self._oracle_agents.items():
            try:
                await self._client.beta.agents.delete_async(agent_id=oracle_id)
                logger.info("Deleted oracle for conversation %s", conv_id)
            except Exception:
                logger.exception("Failed to delete oracle for %s", conv_id)


