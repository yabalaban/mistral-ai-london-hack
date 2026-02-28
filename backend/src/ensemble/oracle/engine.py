"""Oracle engine for group conversations.

The oracle is the invisible intelligence behind group chats. It:
1. Reads the room and picks the best next speaker
2. Grades user messages to extract a thread topic (when one emerges)
3. Keeps conversation focused on the topic once set
4. Provides reasoning as a visible transcript for the UI
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
MAX_SPEAKERS_PER_TURN = 7

ORACLE_SYSTEM = """\
You are the Oracle — invisible moderator for a group thread.

## Thread Topic
{topic}

## Participants
{participants}

## How to Moderate
This is a natural group thread — like humans chatting, not a panel discussion.

Pick the most relevant person to respond. Only add more speakers if they have \
something genuinely different to contribute. Not everyone needs to talk every time.

**Directed messages**: If the user addresses a specific person by name \
(e.g. "Sofia, can you..." or "Emma, what do you think..."), ONLY that person \
should respond. Set done=true after they speak. Don't let others pile on.

Give specific directives: "challenge the scaling assumption" not "share your thoughts".

Keep the thread on topic. If the topic is "General discussion" (not yet set), \
let the conversation flow naturally until one emerges.

Set done=true when key perspectives are covered or when no one would naturally add to it. \
Fewer speakers is almost always better. 2-3 max for most questions.

## Response Format (JSON)
{{
  "reasoning": "<1 sentence>",
  "next_speaker": "<agent_id or null if done>",
  "hint": "<specific directive>",
  "done": false
}}
"""

AGENT_CONTEXT_TEMPLATE = """\
[Thread — you're {name}]
[User said]: {user_message}
[Topic]: {topic}
[Focus]: {hint}

{context}

Reply like a human in a group chat. 1-2 sentences. No walls of text. \
No bullet points unless asked. Don't repeat others. \
Don't ask follow-up questions unless the topic demands it.\
"""

TOPIC_GRADER_SYSTEM = """\
You grade whether a set of user messages contains a clear discussion topic.

Rules:
- Greetings, small talk, and casual messages are NOT topics ("hey", "what's up", "how are you")
- A topic is a specific subject the user wants to discuss or get help with
- The topic should be a concise summary (1 short sentence), not the raw message
- If no clear topic yet, return null

Return JSON:
{"has_topic": true/false, "topic": "<summary>" or null}
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
        """
        agent_ids = conversation.participant_agent_ids
        participants = []
        for aid in agent_ids:
            agent = self._registry.get(aid)
            if agent:
                spoken = "spoken" if aid in (speakers_this_round or []) else "not yet"
                participants.append(
                    f"- **{aid}** ({agent.name}): {agent.role}. [{spoken}]"
                )

        recent = conversation.messages[-MAX_CONTEXT_MESSAGES:]
        history_lines = self._format_history(recent)
        topic = conversation.topic or "General discussion"

        system = ORACLE_SYSTEM.format(
            topic=topic,
            participants="\n".join(participants),
        )

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
            data = json.loads(response.choices[0].message.content.strip())

            done = data.get("done", False)
            next_id = data.get("next_speaker")
            hint = data.get("hint", "Share your perspective")
            reasoning = data.get("reasoning", "")

            if done or next_id is None:
                return None, "", reasoning, True
            if next_id not in agent_ids:
                next_id = agent_ids[0]

            return next_id, hint, reasoning, False

        except Exception:
            logger.exception("Oracle decision failed")
            for aid in agent_ids:
                if aid != last_speaker and aid not in (speakers_this_round or []):
                    return aid, "Share your thoughts", "Fallback", False
            return None, "", "All done", True

    def _detect_directed_message(self, content: str, agent_ids: list[str]) -> str | None:
        """Check if a message is directed at a specific agent by name."""
        lower = content.lower()
        for aid in agent_ids:
            agent = self._registry.get(aid)
            if not agent:
                continue
            name = agent.name.lower()
            # "Sofia, can you..." or "hey emma" or "emma:" etc.
            if lower.startswith(name) or lower.startswith(f"hey {name}") or f"{name}," in lower or f"{name}:" in lower:
                return aid
        return None

    async def grade_topic(self, conversation: Conversation) -> str | None:
        """Use Mistral to grade whether user messages contain a real topic.

        Returns the topic string if found, None otherwise.
        Only looks at USER messages — agent responses don't set the topic.
        """
        user_msgs = [
            msg.content for msg in conversation.messages
            if msg.role == MessageRole.USER
        ]
        if not user_msgs:
            return None

        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=[
                    {"role": "system", "content": TOPIC_GRADER_SYSTEM},
                    {"role": "user", "content": "\n".join(
                        f"Message {i+1}: {m}" for i, m in enumerate(user_msgs[-5:])
                    )},
                ],
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content.strip())
            if data.get("has_topic") and data.get("topic"):
                return data["topic"]
            return None
        except Exception:
            logger.exception("Topic grading failed")
            return None

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
        """Build a prompt for an agent with group context."""
        recent = conversation.messages[-MAX_CONTEXT_MESSAGES:]
        context_lines = self._format_history(recent)
        agent = self._registry.get(agent_id)
        name = agent.name if agent else agent_id

        # Find the latest user message that triggered this round
        user_message = ""
        for msg in reversed(conversation.messages):
            if msg.role == MessageRole.USER:
                user_message = msg.content
                break

        topic = conversation.topic if conversation.topic and conversation.topic != "General discussion" else "none"

        return AGENT_CONTEXT_TEMPLATE.format(
            name=name,
            user_message=user_message,
            topic=topic,
            context="\n".join(context_lines) if context_lines else "(empty)",
            hint=hint,
        )

    async def run_group_turn_streaming(
        self,
        conversation: Conversation,
        content: str,
        attachments: list[Attachment] | None = None,
    ):
        """Generator yielding events for a group conversation turn."""
        user_msg = Message(
            role=MessageRole.USER,
            content=content,
            attachments=attachments or [],
        )
        conversation.messages.append(user_msg)

        # Grade topic from user messages if not set yet
        if not conversation.topic or conversation.topic == "General discussion":
            new_topic = await self.grade_topic(conversation)
            if new_topic:
                conversation.topic = new_topic
                yield ("topic_set", {"topic": new_topic})

        last_speaker = None
        speakers_this_round: list[str] = []

        # Detect directed messages — hard cap at 1 speaker
        directed_agent = self._detect_directed_message(content, conversation.participant_agent_ids)
        max_turns = 1 if directed_agent else MAX_SPEAKERS_PER_TURN

        for _ in range(max_turns):
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

        # Summary if 2+ agents spoke
        if len(speakers_this_round) >= 2:
            summary = await self._generate_summary(conversation, speakers_this_round)
            if summary:
                yield ("summary", {"content": summary})

    async def _generate_summary(
        self, conversation: Conversation, speakers: list[str]
    ) -> str | None:
        """Generate a concise summary of the round."""
        history = self._format_history(conversation.messages[-MAX_CONTEXT_MESSAGES:])
        names = [
            self._registry.get(s).name if self._registry.get(s) else s
            for s in speakers
        ]
        topic = conversation.topic or "the discussion"

        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=[
                    {"role": "system", "content": (
                        "Summarize this discussion round in 2-3 bullet points. "
                        "Key decisions, disagreements, action items. Be concise."
                    )},
                    {"role": "user", "content": (
                        f"Topic: {topic}\nSpeakers: {', '.join(names)}\n\n"
                        + "\n".join(history)
                    )},
                ],
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("Summary generation failed")
            return None

    async def cleanup(self) -> None:
        """No-op."""
        pass
