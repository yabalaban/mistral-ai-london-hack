"""Oracle engine — orchestrates multi-agent group conversations.

The oracle is an invisible meta-agent that decides which agent should speak
next in a group conversation, using conversation context and agent profiles.
It never speaks directly to the user.
"""

from __future__ import annotations

import json
import logging

from mistralai import Mistral

from ensemble.agents.registry import AgentRegistry
from ensemble.config import settings
from ensemble.conversations.manager import _handle_function_calls
from ensemble.conversations.models import (
    Attachment,
    Conversation,
    Message,
    MessageRole,
)
from ensemble.utils import extract_reply

logger = logging.getLogger(__name__)

ORACLE_SYSTEM_PROMPT = """\
You are an invisible conversation orchestrator. You manage a group discussion between \
multiple AI agents and a human user.

Your job:
1. Decide which agent should speak next based on the conversation context
2. Optionally provide a brief steering hint to guide the next speaker's response
3. Keep the conversation flowing naturally — avoid repetition, ensure all voices are heard

You NEVER speak to the user directly. You are invisible.

Participants:
{participants}

Respond ONLY with valid JSON:
{{"next_speaker": "<agent-id>", "hint": "<optional steering hint or empty string>"}}
"""


class OracleEngine:
    """Orchestrates group conversations by deciding turn order."""

    def __init__(self, client: Mistral, registry: AgentRegistry) -> None:
        self._client = client
        self._registry = registry

    async def decide_next_speaker(
        self, conversation: Conversation, last_speaker: str | None = None
    ) -> tuple[str, str]:
        """Returns (agent_id, hint) for who should speak next."""
        participants_desc = []
        for aid in conversation.participant_agent_ids:
            agent = self._registry.get(aid)
            if agent:
                participants_desc.append(
                    f"- {aid}: {agent.name} — {agent.role}. {agent.personality}"
                )

        system_prompt = ORACLE_SYSTEM_PROMPT.format(
            participants="\n".join(participants_desc)
        )

        # Build recent conversation context for oracle
        recent = conversation.messages[-20:]  # last 20 messages
        messages = [{"role": "system", "content": system_prompt}]
        for msg in recent:
            if msg.role == MessageRole.USER:
                messages.append({"role": "user", "content": msg.content})
            else:
                label = msg.agent_id or "unknown"
                messages.append({
                    "role": "assistant",
                    "content": f"[{label}]: {msg.content}",
                })

        if last_speaker:
            messages.append({
                "role": "user",
                "content": f"[System] {last_speaker} just spoke. Who should speak next?",
            })
        else:
            messages.append({
                "role": "user",
                "content": "[System] The user just sent a message. Who should respond first?",
            })

        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content.strip()
            data = json.loads(text)
            next_speaker = data.get("next_speaker", conversation.participant_agent_ids[0])
            hint = data.get("hint", "")

            # Validate speaker is in the conversation
            if next_speaker not in conversation.participant_agent_ids:
                next_speaker = conversation.participant_agent_ids[0]

            return next_speaker, hint
        except Exception:
            logger.exception("Oracle decision failed, falling back to first agent")
            return conversation.participant_agent_ids[0], ""

    async def run_group_turn(
        self,
        conversation: Conversation,
        content: str,
        attachments: list[Attachment] | None = None,
        max_rounds: int = 1,
    ) -> list[Message]:
        """Run one or more rounds of group conversation after a user message.

        Returns the list of agent messages generated.
        """
        # Record user message
        user_msg = Message(
            role=MessageRole.USER,
            content=content,
            attachments=attachments or [],
        )
        conversation.messages.append(user_msg)

        agent_messages: list[Message] = []
        last_speaker: str | None = None

        for _ in range(max_rounds):
            # Oracle decides who speaks
            next_id, hint = await self.decide_next_speaker(conversation, last_speaker)
            agent = self._registry.get(next_id)
            if not agent or not agent.mistral_agent_id:
                logger.warning("Agent %s not ready, skipping", next_id)
                continue

            # Build prompt for the agent — include conversation context + oracle hint
            agent_prompt = self._build_agent_prompt(conversation, next_id, hint)

            # Get agent response via its own Mistral conversation
            mistral_conv_id = conversation.mistral_conversation_ids.get(next_id)
            if mistral_conv_id:
                response = await self._client.beta.conversations.append_async(
                    conversation_id=mistral_conv_id,
                    inputs=agent_prompt,
                )
            else:
                response = await self._client.beta.conversations.start_async(
                    agent_id=agent.mistral_agent_id,
                    inputs=agent_prompt,
                )
            conversation.mistral_conversation_ids[next_id] = response.conversation_id

            # Handle function calls
            response = await _handle_function_calls(
                self._client, response, conversation, next_id
            )

            reply_text = extract_reply(response)
            agent_msg = Message(
                role=MessageRole.AGENT,
                agent_id=next_id,
                content=reply_text,
            )
            conversation.messages.append(agent_msg)
            agent_messages.append(agent_msg)
            last_speaker = next_id

        return agent_messages

    def _build_agent_prompt(
        self, conversation: Conversation, agent_id: str, hint: str
    ) -> str:
        """Build a context-rich prompt for the agent in a group setting."""
        # Summarize recent messages so agent knows what's been said
        recent = conversation.messages[-10:]
        context_lines = []
        for msg in recent:
            if msg.role == MessageRole.USER:
                context_lines.append(f"User: {msg.content}")
            else:
                name = msg.agent_id or "unknown"
                agent_profile = self._registry.get(name)
                display = agent_profile.name if agent_profile else name
                context_lines.append(f"{display}: {msg.content}")

        context = "\n".join(context_lines)
        prompt = f"[Group conversation context]\n{context}\n\n"
        if hint:
            prompt += f"[Moderator note: {hint}]\n\n"
        prompt += "It's your turn to contribute. Respond naturally as yourself."
        return prompt


# _extract_reply removed — use ensemble.utils.extract_reply instead
