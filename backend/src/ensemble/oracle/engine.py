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
MAX_SPEAKERS_PER_TURN = 7

ORACLE_SYSTEM = """\
You are the Oracle — invisible moderator for a group thread.

## Thread Topic
{topic}

## Participants
{participants}

## How to Moderate
This is a natural group thread — like humans chatting. NOT a panel discussion.

**Greetings/small talk** ("hey", "what's up"): Pick ONE person to respond casually. Then IMMEDIATELY set done=true. Do NOT let others pile on. One "hey" back is enough. No follow-up questions, no hot takes, no tangents.

**Real questions/topics**: Pick the most relevant person. Only add more speakers if they have something genuinely different to add. 2-3 speakers max per round usually. Not everyone needs to talk every time.

**Directives**: Be specific. "Challenge Emma's scaling assumption" not "share your thoughts". Keep the thread focused on the topic.

**When to stop** (done=true):
- After greetings — one casual reply is enough
- When the key perspectives are covered — don't force participation
- When someone gave a complete answer and nobody would naturally add to it

## Response Format (JSON)
{{
  "reasoning": "<1 sentence — why this person>",
  "next_speaker": "<agent_id or null if done>",
  "hint": "<specific directive or 'casual' for small talk>",
  "done": false
}}
\
"""

AGENT_CONTEXT_TEMPLATE = """\
[Thread — you're {name}] [Topic: {topic}]

{context}

[→ {name}]: {hint}

Reply like a human in a group chat. 1-2 sentences. No walls of text. No bullet points unless asked. Don't repeat others. Don't ask follow-up questions unless the topic demands it.\
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

        # Extract or use existing topic
        topic = conversation.topic
        if not topic or topic == "General discussion":
            new_topic = await self._extract_topic(conversation)
            if new_topic != "General discussion":
                conversation.topic = new_topic
            topic = new_topic

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

    @staticmethod
    def _is_greeting(text: str) -> bool:
        """Check if a message is just a greeting/small talk."""
        normalized = text.lower().strip().rstrip("?!.,")
        greeting_exact = {
            "hi", "hey", "hello", "yo", "sup", "whats up", "what's up",
            "how are you", "how's it going", "howdy", "hiya", "good morning",
            "good evening", "good afternoon", "hey folks", "hi everyone",
            "hey everyone", "hey guys", "hey team", "what up", "wassup",
            "hey folks whats up", "hey folks what's up", "hi all",
            "hey all", "morning", "evening",
        }
        if normalized in greeting_exact:
            return True
        words = normalized.split()
        if len(words) <= 5 and any(g in normalized for g in ("hey", "hi ", "hello", "what's up", "whats up", "sup")):
            return True
        return False

    async def _extract_topic(self, conversation: Conversation) -> str:
        """Extract the thread topic from early user messages.

        Looks at up to the first 3 user messages and picks the most
        substantive one as the topic. Skips greetings like 'hey' or 'hi'.
        Falls back to an LLM call if ambiguous.
        """
        user_msgs = [
            msg.content for msg in conversation.messages
            if msg.role == MessageRole.USER
        ][:3]

        if not user_msgs:
            return "General discussion"

        # Filter out greetings and small talk
        GREETING_PATTERNS = {
            "hi", "hey", "hello", "yo", "sup", "whats up", "what's up",
            "how are you", "how's it going", "howdy", "hiya", "good morning",
            "good evening", "good afternoon", "hey folks", "hi everyone",
            "hey everyone", "hey guys", "hey team", "what up",
        }
        substantive = []
        for m in user_msgs:
            normalized = m.lower().strip().rstrip("?!.,")
            if normalized in GREETING_PATTERNS:
                continue
            # Also skip if it's just a greeting with filler
            words = normalized.split()
            if len(words) <= 5 and any(g in normalized for g in ("hey", "hi ", "hello", "what's up", "whats up", "sup")):
                continue
            if len(words) < 4:
                continue
            substantive.append(m)

        if len(substantive) == 1:
            return substantive[0]

        if not substantive:
            # All messages are short/greetings — no real topic yet
            return "General discussion"

        # Multiple substantive messages — ask the LLM to pick the topic
        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=[
                    {"role": "system", "content": (
                        "Extract the main discussion topic from these user messages. "
                        "Return JSON: {\"topic\": \"<1 sentence summary of what the thread is about>\"}"
                    )},
                    {"role": "user", "content": "\n".join(f"- {m}" for m in substantive)},
                ],
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content.strip())
            return data.get("topic", substantive[0])
        except Exception:
            logger.exception("Topic extraction failed")
            return substantive[0]

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

        topic = conversation.topic or "General discussion"

        return AGENT_CONTEXT_TEMPLATE.format(
            name=name,
            topic=topic,
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
        topic_before = conversation.topic

        # Detect if this is a greeting — hard cap at 1 speaker
        is_greeting = self._is_greeting(content)
        max_turns = 1 if is_greeting else MAX_SPEAKERS_PER_TURN

        for turn_idx in range(max_turns):
            next_id, hint, reasoning, done = await self.decide_next_speaker(
                conversation, last_speaker, speakers_this_round
            )

            # Emit topic when first extracted (topic changed from before)
            if conversation.topic and conversation.topic != topic_before and conversation.topic != "General discussion":
                yield ("topic_set", {"topic": conversation.topic})
                topic_before = conversation.topic

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

        # Generate round summary if multiple agents spoke
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
                        "Summarize this group discussion round in 2-3 bullet points. "
                        "Focus on key decisions, disagreements, and action items. "
                        "Be concise and sharp. Use markdown."
                    )},
                    {"role": "user", "content": (
                        f"Topic: {topic}\n"
                        f"Speakers: {', '.join(names)}\n\n"
                        + "\n".join(history)
                    )},
                ],
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("Summary generation failed")
            return None

    async def cleanup(self) -> None:
        """No-op — oracle doesn't create persistent Mistral agents."""
        pass
