"""Oracle engine for group conversations.

The oracle is the invisible intelligence behind group chats. It:
1. Reads the room — who's spoken, what's been said, what's missing
2. Picks the best next speaker with a specific directive
3. Decides when the conversation round is complete
4. Provides its reasoning as a visible transcript for the UI

Each agent gets their own Mistral Conversation for persistent memory.
The oracle injects group context so agents build on each other's points.
"""

from __future__ import annotations

import json
import logging

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

MAX_CONTEXT_MESSAGES = 15
MAX_SPEAKERS_PER_TURN = 5

ORACLE_SYSTEM = """\
You are the Oracle — an invisible moderator orchestrating a group discussion between AI agents.

## Participants
{participants}

## Your Job
Analyze the conversation and decide:
1. **Who** should speak next (or if the round is done)
2. **What** angle they should take — be specific, not generic
3. **Why** — your reasoning is shown to users as a live transcript

## Rules
- Never pick the same speaker twice in a row
- Prefer speakers who haven't contributed yet this round
- If a topic needs a specific expertise, pick the specialist
- Give pointed directives: not "share your thoughts" but "challenge Emma's architecture choice" or "estimate the market size"
- If all relevant perspectives are covered, set `done: true` to end the round
- Keep reasoning to 1-2 punchy sentences — this is a live feed, not an essay

## Response Format (JSON)
{{
  "reasoning": "<why this person, why now — 1-2 sentences>",
  "next_speaker": "<agent_id or null if done>",
  "hint": "<specific directive for the speaker>",
  "done": false
}}

Set `done: true` and `next_speaker: null` when the round is complete.\
"""

AGENT_CONTEXT_TEMPLATE = """\
[Group Discussion — you're {name}]

What's been said:
{context}

[Moderator → {name}]: {hint}

Respond in 2-3 sentences. Be direct and in character. Build on or challenge what others said — don't repeat their points.\
"""


class OracleEngine:
    """Picks next speaker and manages per-agent Mistral conversations in groups."""

    def __init__(self, client: Mistral, registry: AgentRegistry) -> None:
        self._client = client
        self._registry = registry

    async def decide_next_speaker(
        self,
        conversation: Conversation,
        last_speaker: str | None = None,
        speakers_this_round: list[str] | None = None,
    ) -> tuple[str | None, str, str, bool]:
        """Pick the next agent to speak.

        Returns (agent_id | None, hint, reasoning, done).
        agent_id is None when done=True.
        """
        agent_ids = conversation.participant_agent_ids
        participants = []
        for aid in agent_ids:
            agent = self._registry.get(aid)
            if agent:
                spoken = "✓ spoken" if aid in (speakers_this_round or []) else "not yet spoken"
                participants.append(
                    f"- **{aid}** ({agent.name}): {agent.role}. "
                    f"Personality: {agent.personality[:80]}. [{spoken}]"
                )

        recent = conversation.messages[-MAX_CONTEXT_MESSAGES:]
        history_lines = self._format_history(recent)

        system = ORACLE_SYSTEM.format(participants="\n".join(participants))

        messages = [{"role": "system", "content": system}]
        if history_lines:
            messages.append({"role": "user", "content": "\n".join(history_lines)})
        messages.append({
            "role": "user",
            "content": f"Last speaker: {last_speaker or 'none'}. "
                       f"Speakers this round: {', '.join(speakers_this_round or [])}. "
                       f"Who speaks next?",
        })

        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content.strip()
            data = json.loads(text)

            done = data.get("done", False)
            next_id = data.get("next_speaker")
            hint = data.get("hint", "Share your perspective")
            reasoning = data.get("reasoning", "")

            # Validate
            if done or next_id is None:
                return None, "", reasoning, True
            if next_id not in agent_ids:
                next_id = agent_ids[0]

            return next_id, hint, reasoning, False

        except Exception:
            logger.exception("Oracle decision failed, picking first available")
            for aid in agent_ids:
                if aid != last_speaker and aid not in (speakers_this_round or []):
                    return aid, "Share your thoughts", "Fallback — rotating speakers", False
            return None, "", "All participants have spoken", True

    def _format_history(self, messages: list[Message]) -> list[str]:
        """Format recent messages for oracle/agent context."""
        lines = []
        for msg in messages:
            if msg.role == MessageRole.USER:
                lines.append(f"**User**: {msg.content}")
            elif msg.role == MessageRole.AGENT and msg.agent_id:
                agent = self._registry.get(msg.agent_id)
                name = agent.name if agent else msg.agent_id
                lines.append(f"**{name}**: {msg.content[:400]}")
        return lines

    def build_agent_prompt(
        self, conversation: Conversation, agent_id: str, hint: str
    ) -> str:
        """Build a prompt for an agent with full group context."""
        recent = conversation.messages[-MAX_CONTEXT_MESSAGES:]
        context_lines = self._format_history(recent)
        agent = self._registry.get(agent_id)
        name = agent.name if agent else agent_id

        return AGENT_CONTEXT_TEMPLATE.format(
            name=name,
            context="\n".join(context_lines) if context_lines else "(No messages yet)",
            hint=hint,
        )

    async def run_group_turn_streaming(
        self,
        conversation: Conversation,
        content: str,
        attachments: list[Attachment] | None = None,
    ):
        """Generator yielding events for a group conversation turn.

        The oracle dynamically decides how many speakers are needed.
        Events:
            ("oracle", {...})      — oracle reasoning for transcript
            ("turn_change", {...}) — agent is about to speak
            ("chunk", {...})       — streaming text chunk
            ("message", Message)   — completed agent message
        """
        user_msg = Message(
            role=MessageRole.USER,
            content=content,
            attachments=attachments or [],
        )
        conversation.messages.append(user_msg)

        last_speaker = None
        speakers_this_round: list[str] = []

        for _ in range(MAX_SPEAKERS_PER_TURN):
            next_id, hint, reasoning, done = await self.decide_next_speaker(
                conversation, last_speaker, speakers_this_round
            )

            if done or next_id is None:
                if reasoning:
                    yield ("oracle", {
                        "reasoning": reasoning,
                        "next_speaker": None,
                        "next_speaker_name": None,
                        "hint": "",
                    })
                break

            agent = self._registry.get(next_id)
            if not agent or not agent.mistral_agent_id:
                continue

            yield ("oracle", {
                "reasoning": reasoning,
                "next_speaker": next_id,
                "next_speaker_name": agent.name,
                "hint": hint,
            })
            yield ("turn_change", {"agent_id": next_id})

            # Stream from agent's own Mistral conversation
            prompt = self.build_agent_prompt(conversation, next_id, hint)
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
                    speakers_this_round.append(next_id)

            except Exception:
                logger.exception("Agent %s streaming failed", next_id)

    async def cleanup(self) -> None:
        """No-op — oracle doesn't create persistent Mistral agents."""
        pass
