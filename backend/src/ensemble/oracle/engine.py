"""Oracle engine for group conversations.

The oracle picks the next speaker via a lightweight chat completion call,
then each agent responds in their own Mistral Conversation (persistent history).
Group context is injected so agents know what others have said.
"""

from __future__ import annotations

import json
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

# Number of recent messages to include as context for each agent
MAX_CONTEXT_MESSAGES = 10


class OracleEngine:
    """Picks next speaker and manages per-agent Mistral conversations in groups."""

    def __init__(self, client: Mistral, registry: AgentRegistry) -> None:
        self._client = client
        self._registry = registry

    async def decide_next_speaker(
        self, conversation: Conversation, last_speaker: str | None = None
    ) -> tuple[str, str, str]:
        """Pick the next agent to speak.

        Returns (agent_id, hint, reasoning) where reasoning explains
        the oracle's decision for the transcript pane.
        """
        agent_ids = conversation.participant_agent_ids
        agents_desc = []
        for aid in agent_ids:
            agent = self._registry.get(aid)
            if agent:
                agents_desc.append(f"{aid}: {agent.name} ({agent.role})")

        recent = conversation.messages[-MAX_CONTEXT_MESSAGES:]
        history_lines = []
        for msg in recent:
            if msg.role == MessageRole.USER:
                history_lines.append(f"User: {msg.content}")
            elif msg.role == MessageRole.AGENT and msg.agent_id:
                agent = self._registry.get(msg.agent_id)
                name = agent.name if agent else msg.agent_id
                history_lines.append(f"{name}: {msg.content[:200]}")

        system = (
            "You are a conversation moderator. Pick ONE participant to speak next.\n"
            f"Participants: {', '.join(agents_desc)}\n"
            f"Last speaker: {last_speaker or 'none'}\n\n"
            "Respond with JSON:\n"
            "{\"reasoning\": \"<1-2 sentences explaining your choice>\", "
            "\"next_speaker\": \"<id>\", \"hint\": \"<brief direction for them>\"}\n"
            "Rules:\n"
            "- Rotate between participants — don't pick the same one twice in a row\n"
            "- Pick the most relevant person for the current topic\n"
            "- The hint tells them what angle to take (1 sentence)"
        )

        messages = [
            {"role": "system", "content": system},
        ]
        if history_lines:
            messages.append({"role": "user", "content": "\n".join(history_lines)})
        messages.append({"role": "user", "content": "Who should speak next?"})

        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content.strip()
            data = json.loads(text)
            next_id = data.get("next_speaker", agent_ids[0])
            hint = data.get("hint", "Share your perspective")
            reasoning = data.get("reasoning", "")

            # Validate
            if next_id not in agent_ids:
                next_id = agent_ids[0]

            return next_id, hint, reasoning
        except Exception:
            logger.exception("Oracle decision failed, picking first available")
            for aid in agent_ids:
                if aid != last_speaker:
                    return aid, "Share your thoughts", "Fallback — rotating speakers"
            return agent_ids[0], "Share your thoughts", "Fallback — only one speaker"

    def build_agent_prompt(
        self, conversation: Conversation, agent_id: str, hint: str
    ) -> str:
        """Build a prompt for an agent that includes group context."""
        recent = conversation.messages[-MAX_CONTEXT_MESSAGES:]
        context_lines = []
        for msg in recent:
            if msg.role == MessageRole.USER:
                context_lines.append(f"User: {msg.content}")
            elif msg.role == MessageRole.AGENT and msg.agent_id:
                agent = self._registry.get(msg.agent_id)
                name = agent.name if agent else msg.agent_id
                context_lines.append(f"{name}: {msg.content[:300]}")

        agent = self._registry.get(agent_id)
        name = agent.name if agent else agent_id

        context = "\n".join(context_lines)
        return (
            f"[Group Discussion]\n"
            f"{context}\n\n"
            f"[Moderator → {name}]: {hint}\n"
            f"Respond concisely (2-3 sentences). Stay in character."
        )

    async def run_group_turn_streaming(
        self,
        conversation: Conversation,
        content: str,
        attachments: list[Attachment] | None = None,
        max_speakers: int = 3,
    ):
        """Generator yielding events for a group conversation turn.

        For each speaker the oracle picks:
        1. Yields ("oracle", {"reasoning": ..., "next_speaker": ..., "hint": ...})
        2. Yields ("turn_change", {"agent_id": ...})
        3. Streams response chunks: ("chunk", {"agent_id": ..., "content": ...})
        4. Yields completed message: ("message", Message)
        """
        # Record user message
        user_msg = Message(
            role=MessageRole.USER,
            content=content,
            attachments=attachments or [],
        )
        conversation.messages.append(user_msg)

        last_speaker = None
        speakers_count = min(max_speakers, len(conversation.participant_agent_ids))

        for _ in range(speakers_count):
            # Oracle picks next speaker
            next_id, hint, reasoning = await self.decide_next_speaker(conversation, last_speaker)

            # Emit oracle reasoning for transcript pane
            agent = self._registry.get(next_id)
            yield ("oracle", {
                "reasoning": reasoning,
                "next_speaker": next_id,
                "next_speaker_name": agent.name if agent else next_id,
                "hint": hint,
            })
            agent = self._registry.get(next_id)
            if not agent or not agent.mistral_agent_id:
                continue

            yield ("turn_change", {"agent_id": next_id})

            # Build prompt with group context
            prompt = self.build_agent_prompt(conversation, next_id, hint)

            # Stream from agent's own Mistral conversation
            mistral_conv_id = conversation.mistral_conversation_ids.get(next_id)
            full_text = ""

            try:
                if mistral_conv_id:
                    stream = await self._client.beta.conversations.append_stream_async(
                        conversation_id=mistral_conv_id,
                        inputs=prompt,
                    )
                else:
                    stream = await self._client.beta.conversations.start_stream_async(
                        agent_id=agent.mistral_agent_id,
                        inputs=prompt,
                    )

                async for event in stream:
                    data = event.data
                    # Capture conversation ID
                    if hasattr(data, "conversation_id") and data.conversation_id:
                        conversation.mistral_conversation_ids[next_id] = data.conversation_id

                    if hasattr(data, "content"):
                        text = extract_text_from_content(getattr(data, "content", ""))
                        if text:
                            full_text += text
                            yield ("chunk", {"agent_id": next_id, "content": text})

                if full_text:
                    msg = Message(
                        role=MessageRole.AGENT,
                        agent_id=next_id,
                        content=full_text,
                    )
                    conversation.messages.append(msg)
                    yield ("message", msg)
                    last_speaker = next_id

            except Exception:
                logger.exception("Agent %s streaming failed", next_id)

    async def cleanup(self) -> None:
        """No-op — oracle doesn't create persistent Mistral agents."""
        pass
