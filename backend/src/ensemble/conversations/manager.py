from __future__ import annotations

import logging

from mistralai import Mistral

from ensemble.agents.registry import AgentRegistry
from ensemble.conversations.models import (
    Attachment,
    Conversation,
    ConversationType,
    Message,
    MessageRole,
)

logger = logging.getLogger(__name__)


class ConversationManager:
    """Manages conversations and routes messages to Mistral."""

    def __init__(self, client: Mistral, registry: AgentRegistry) -> None:
        self._client = client
        self._registry = registry
        self._conversations: dict[str, Conversation] = {}

    @property
    def conversations(self) -> dict[str, Conversation]:
        return dict(self._conversations)

    def get(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(conversation_id)

    def create(
        self,
        type: ConversationType,
        participant_agent_ids: list[str],
    ) -> Conversation:
        """Create a new conversation."""
        # Validate agents exist
        for aid in participant_agent_ids:
            if not self._registry.get(aid):
                raise ValueError(f"Unknown agent: {aid}")

        conv = Conversation(type=type, participant_agent_ids=participant_agent_ids)
        self._conversations[conv.id] = conv
        logger.info("Created %s conversation %s with %s", type, conv.id, participant_agent_ids)
        return conv

    async def send_direct_message(
        self,
        conversation_id: str,
        content: str,
        attachments: list[Attachment] | None = None,
    ) -> Message:
        """Send a user message in a direct conversation, get agent reply."""
        conv = self._conversations.get(conversation_id)
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found")
        if conv.type != ConversationType.DIRECT:
            raise ValueError("Use send_group_message for group conversations")

        agent_id = conv.participant_agent_ids[0]
        agent = self._registry.get(agent_id)
        if not agent or not agent.mistral_agent_id:
            raise ValueError(f"Agent {agent_id} not ready")

        # Record user message
        user_msg = Message(
            role=MessageRole.USER,
            content=content,
            attachments=attachments or [],
        )
        conv.messages.append(user_msg)

        # Build inputs for Mistral
        inputs = _build_inputs(content, attachments)

        # Start or continue Mistral conversation
        mistral_conv_id = conv.mistral_conversation_ids.get(agent_id)
        if mistral_conv_id:
            response = await self._client.beta.conversations.append_async(
                conversation_id=mistral_conv_id,
                inputs=inputs,
            )
        else:
            response = await self._client.beta.conversations.start_async(
                agent_id=agent.mistral_agent_id,
                inputs=inputs,
            )

        conv.mistral_conversation_ids[agent_id] = response.conversation_id

        # Extract assistant reply
        reply_text = _extract_reply(response)
        agent_msg = Message(
            role=MessageRole.AGENT,
            agent_id=agent_id,
            content=reply_text,
        )
        conv.messages.append(agent_msg)
        return agent_msg

    def list_all(self) -> list[Conversation]:
        return list(self._conversations.values())


def _build_inputs(
    content: str, attachments: list[Attachment] | None = None
) -> str | list[dict]:
    """Build Mistral conversation inputs from content + optional attachments."""
    if not attachments:
        return content

    # Multimodal: build content blocks
    parts: list[dict] = [{"type": "text", "text": content}]
    for att in attachments:
        if att.type == "image":
            parts.append({"type": "image_url", "image_url": {"url": att.url}})
    return [{"role": "user", "content": parts}]


def _extract_reply(response) -> str:
    """Extract the text reply from a Mistral conversation response."""
    for output in response.outputs:
        if hasattr(output, "content") and hasattr(output, "role"):
            content = output.content
            if isinstance(content, str):
                return content
            # Could be structured content
            if isinstance(content, list):
                texts = [c.get("text", "") for c in content if isinstance(c, dict)]
                return "".join(texts)
            return str(content)
    return ""
