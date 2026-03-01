"""Oracle engine for group conversations.

Strategy:
1. A classifier grades the user message as "parallel" or "sequential"
   - parallel: casual / greeting → all agents respond at once, one round
   - sequential: substantive → agents go one-by-one, each seeing prior replies
2. Agents can [PASS] if they have nothing to add
3. After a round, a grader decides if the conversation is fulfilled
4. Loops up to MAX_ROUNDS if not
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid as _uuid
from typing import Any, cast

from mistralai import Mistral

from ensemble.agents.registry import AgentRegistry
from ensemble.config import settings
from ensemble.conversations.models import (
    Attachment,
    Conversation,
    Message,
    MessageRole,
)
from ensemble.oracle.turn_logger import RoundRecord, TurnRecord, log_turn
from ensemble.utils import extract_text_from_content

logger = logging.getLogger(__name__)


def _get_text(content: Any) -> str:
    """Extract text from a chat completion message content.

    Magistral models return content as a list of blocks instead of a string.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("text"):
                parts.append(block["text"])
            elif hasattr(block, "text"):
                parts.append(block.text)
        return "".join(parts).strip()
    return str(content).strip()


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json(text: str) -> dict:
    """Parse JSON from text that may contain reasoning before the JSON.

    Magistral models include chain-of-thought text before the actual JSON.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_RE.search(text)
        if match:
            return json.loads(match.group())
        raise


MAX_CONTEXT_MESSAGES = 15
MAX_ROUNDS = 10
PASS_TOKEN = "[PASS]"
PASS_VARIANTS = {"[pass]", "pass", "[pass].", "pass."}


def _is_pass(text: str) -> bool:
    """Check if agent output is a pass (case-insensitive, flexible)."""
    s = text.strip().lower()
    return s in PASS_VARIANTS or s.startswith("[pass]")


_REPLY_PREFIX_RE = re.compile(r"^\[[Nn]?(\d{1,2})\]\s*\n?")


def _parse_reply_target(text: str, index_map: dict[str, str]) -> tuple[str | None, str]:
    """Extract [N] prefix and map index to real message ID.

    Returns (reply_to_id | None, cleaned_text).
    Always strips the prefix if found.
    """
    match = _REPLY_PREFIX_RE.match(text)
    if not match:
        return None, text
    cleaned = text[match.end():]
    return index_map.get(match.group(1)), cleaned


# ── Prompts ──────────────────────────────────────────────────────────────────

CLASSIFIER_SYSTEM = """\
You classify user messages in a group chat and infer the user's concrete goal.

**parallel** — casual or social messages where everyone can respond at once.
**sequential** — substantive requests that benefit from agents building on \
each other's responses.

**goal** — a concise, evaluable description of what the user wants achieved. \
Include any specific quantities or criteria mentioned. If the message is \
casual, the goal should be simple (e.g. "greet the user").

Return JSON:
{"mode": "parallel" or "sequential", "goal": "<concise evaluable goal>"}
"""

GRADER_SYSTEM = """\
You are a conversation grader. Given the original user message and all agent \
responses so far, decide if the conversation round is complete.

The user's goal is: {goal}
Mode: {mode}

If mode is "parallel" (casual/social), the goal is met as soon as agents \
have acknowledged or responded — done after one round. Don't require depth.

If mode is "sequential" (substantive), evaluate whether responses have \
achieved the goal. Lean toward done if substantially met. Only say NOT done \
if a critical aspect of the goal is clearly unaddressed.

Return JSON:
{{"reasoning": "<1 sentence>", "done": true/false}}
"""

AGENT_CONTEXT_TEMPLATE = """\
[Thread — you're {name}, {role}]
[Participants]:
{participants}
[User said]: {user_message}
[Topic]: {topic}
{hint_line}
{summary_line}

{context}

Start with the number of the message you're responding to in brackets, \
e.g. [1] to respond to message 1, [3] to respond to message 3.

Guidelines:
- Stay in your lane — contribute from your expertise as {role}. \
Don't give advice outside your domain; let others cover theirs. \
You can call on another participant by name if their expertise is needed.
- Build on what others said — add new information, a different angle, or a \
concrete next step. Never restate what's already been covered.
- Be substantive: provide actionable ideas, specific details, or clear opinions. \
Avoid filler, hedging, and generic encouragement.
- Keep it very short — 1-2 sentences max. This is a voice conversation.
- If you have nothing new to add, reply with exactly: [PASS]
"""

RANKER_SYSTEM = """\
You rank which agents should respond to a message in a group chat.

Agents:
{agent_descriptions}

First, classify the message as "generic" or "specialised":
- **generic** — greetings, casual chat, open-ended questions, opinions everyone \
can weigh in on. All agents should respond.
- **specialised** — requires specific domain expertise. Only agents with \
relevant expertise should respond.

Rules:
- generic → all agents respond (should_respond: true for everyone)
- specialised → only matching agents respond, others get should_respond: false
- Order by relevance (most relevant first)
- The hint guides the agent's angle — make it specific and actionable (3-5 words)
- At least one agent must respond
- last_speaker can appear again if they have more to add

User message: {user_message}
Topic: {topic}
Last speaker: {last_speaker}
Prior responses: {prior_summary}

Return JSON:
{{"type": "generic" or "specialised", "ranking": [{{"agent_id": "...", "should_respond": true/false, "hint": "..." or null}}, ...]}}
"""

INTERRUPTION_SYSTEM = """\
You decide whether to interrupt the current speaker in a voice group chat.

Goal: {goal}
Speaker: {agent_name} ({agent_role})
Their response so far: {partial_text}
Agents waiting to speak: {waiting_agents}

Interrupt if the speaker has made their main point and other perspectives \
are needed. Don't interrupt if the response is still building to an \
important point or is very short.

Return JSON: {{"interrupt": true/false, "reasoning": "1 sentence"}}
"""

_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?](?:\s|$)")


def _count_sentences(text: str) -> int:
    """Count completed sentences in text."""
    return len(_SENTENCE_BOUNDARY_RE.findall(text))


def _trim_to_last_sentence(text: str) -> str:
    """Trim text to the last complete sentence boundary."""
    for i in range(len(text) - 1, -1, -1):
        if text[i] in ".!?":
            return text[: i + 1]
    return text


TOPIC_GRADER_SYSTEM = """\
You grade whether a set of user messages contains a clear discussion topic.

Rules:
- Greetings, small talk, and casual messages are NOT topics
- A topic is a specific subject the user wants to discuss or get help with
- The topic should be a concise summary (1 short sentence), not the raw message
- If no clear topic yet, return null

Return JSON:
{"has_topic": true/false, "topic": "<summary>" or null}
"""


# ── Engine ───────────────────────────────────────────────────────────────────


class OracleEngine:
    """Classifies messages → parallel or sequential fan-out → grader loop."""

    def __init__(self, client: Mistral, registry: AgentRegistry) -> None:
        self._client = client
        self._registry = registry

    # ── LLM calls ────────────────────────────────────────────────────────

    async def classify_message(self, content: str) -> tuple[str, str]:
        """Classify a user message and infer goal.

        Returns (mode, goal) where mode is 'parallel' or 'sequential'.
        """
        fallback_goal = "address the user's message"
        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=cast(Any, [
                    {"role": "system", "content": CLASSIFIER_SYSTEM},
                    {"role": "user", "content": content},
                ]),
                response_format={"type": "json_object"},
            )
            data = _parse_json(_get_text(response.choices[0].message.content))
            mode = data.get("mode", "sequential")
            if mode not in ("parallel", "sequential"):
                mode = "sequential"
            goal = data.get("goal") or fallback_goal
            logger.info("Classifier: %r → %s (goal: %s)", content[:60], mode, goal)
            return mode, goal
        except Exception:
            logger.exception("Classifier failed, defaulting to sequential")
            return "sequential", fallback_goal

    async def grade_completion(
        self,
        conversation: Conversation,
        user_message: str,
        goal: str = "",
        mode: str = "sequential",
    ) -> tuple[bool, str]:
        """Grade whether the conversation round is complete against the goal."""
        # Grader sees ALL messages (not limited to MAX_CONTEXT_MESSAGES)
        # so it can evaluate cumulative progress toward the goal.
        history_lines, _ = self._format_history(conversation.messages)
        grader_prompt = GRADER_SYSTEM.format(
            goal=goal or "address the user's message",
            mode=mode,
        )
        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=cast(Any, [
                    {"role": "system", "content": grader_prompt},
                    {"role": "user", "content": (
                        f"User message: {user_message}\n\n"
                        "Conversation so far:\n"
                        + "\n".join(history_lines)
                    )},
                ]),
                response_format={"type": "json_object"},
            )
            data = _parse_json(_get_text(response.choices[0].message.content))
            return data.get("done", True), data.get("reasoning", "")
        except Exception:
            logger.exception("Grade completion failed")
            return True, "Grader failed, ending round"

    async def grade_topic(self, conversation: Conversation) -> str | None:
        """Grade whether user messages contain a discussion topic."""
        user_msgs = [
            msg.content for msg in conversation.messages
            if msg.role == MessageRole.USER
        ]
        if not user_msgs:
            return None
        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=cast(Any, [
                    {"role": "system", "content": TOPIC_GRADER_SYSTEM},
                    {"role": "user", "content": "\n".join(
                        f"Message {i+1}: {m}"
                        for i, m in enumerate(user_msgs[-5:])
                    )},
                ]),
                response_format={"type": "json_object"},
            )
            data = _parse_json(_get_text(response.choices[0].message.content))
            if data.get("has_topic") and data.get("topic"):
                return data["topic"]
            return None
        except Exception:
            logger.exception("Topic grading failed")
            return None

    async def rank_agents(
        self,
        content: str,
        conversation: Conversation,
        agent_ids: list[str],
        last_speaker: str | None = None,
    ) -> list[dict]:
        """Rank agents by relevance to decide who should respond."""
        # Build agent descriptions from registry
        descriptions = []
        for aid in agent_ids:
            agent = self._registry.get(aid)
            if agent:
                descriptions.append(
                    f"- {aid}: {agent.role} — {agent.personality.split('.')[0]}"
                )

        # Summarize prior responses in this turn
        prior = []
        for msg in conversation.messages[-MAX_CONTEXT_MESSAGES:]:
            if msg.role == MessageRole.AGENT and msg.agent_id:
                agent = self._registry.get(msg.agent_id)
                name = agent.name if agent else msg.agent_id
                prior.append(f"{name}: {msg.content[:100]}")
        prior_summary = "\n".join(prior[-5:]) if prior else "none"

        has_topic = (
            conversation.topic
            and conversation.topic != "General discussion"
        )

        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=cast(Any, [
                    {"role": "system", "content": RANKER_SYSTEM.format(
                        agent_descriptions="\n".join(descriptions),
                        user_message=content,
                        topic=conversation.topic if has_topic else "none",
                        last_speaker=last_speaker or "none",
                        prior_summary=prior_summary,
                    )},
                    {"role": "user", "content": content},
                ]),
                response_format={"type": "json_object"},
            )
            data = _parse_json(_get_text(response.choices[0].message.content))
            ranking = data.get("ranking", [])

            # Validate: only keep known agent IDs
            known = set(agent_ids)
            ranking = [r for r in ranking if r.get("agent_id") in known]

            # Ensure at least one agent responds
            if not ranking or not any(r.get("should_respond") for r in ranking):
                return [{"agent_id": aid, "should_respond": True, "hint": None}
                        for aid in agent_ids]

            logger.info(
                "Ranker: %s → %s",
                content[:60],
                [(r["agent_id"], r.get("should_respond")) for r in ranking],
            )
            return ranking
        except Exception:
            logger.exception("Ranker failed, including all agents")
            return [{"agent_id": aid, "should_respond": True, "hint": None}
                    for aid in agent_ids]

    async def check_interruption(
        self,
        agent_id: str,
        partial_text: str,
        goal: str,
        remaining_agent_ids: list[str],
    ) -> tuple[bool, str]:
        """Check if the current speaker should be interrupted mid-turn."""
        agent = self._registry.get(agent_id)
        name = agent.name if agent else agent_id
        role = agent.role if agent else "Agent"

        waiting = []
        for aid in remaining_agent_ids:
            a = self._registry.get(aid)
            if a:
                waiting.append(f"{a.name} ({a.role})")

        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=cast(Any, [
                    {"role": "system", "content": INTERRUPTION_SYSTEM.format(
                        goal=goal,
                        agent_name=name,
                        agent_role=role,
                        partial_text=partial_text,
                        waiting_agents=", ".join(waiting) or "none",
                    )},
                    {"role": "user", "content": "Should we interrupt?"},
                ]),
                response_format={"type": "json_object"},
            )
            data = _parse_json(_get_text(response.choices[0].message.content))
            should = data.get("interrupt", False)
            reasoning = data.get("reasoning", "")
            logger.info(
                "Interruption check for %s: interrupt=%s reason=%s",
                name, should, reasoning,
            )
            return should, reasoning
        except Exception:
            logger.exception("Interruption check failed")
            return False, "Check failed"

    # ── Helpers ───────────────────────────────────────────────────────────

    def _detect_directed_message(
        self, content: str, agent_ids: list[str]
    ) -> str | None:
        """Check if a message is directed at a specific agent by name."""
        lower = content.lower()
        for aid in agent_ids:
            agent = self._registry.get(aid)
            if not agent:
                continue
            name = agent.name.lower()
            starts = (
                lower.startswith(name)
                or lower.startswith(f"hey {name}")
            )
            if starts or f"{name}," in lower or f"{name}:" in lower:
                return aid
        return None

    def _format_history(
        self, messages: list[Message],
    ) -> tuple[list[str], dict[str, str]]:
        """Format messages with numeric indices.

        Returns (lines, index_map) where index_map maps "1","2",... to msg IDs.
        """
        lines: list[str] = []
        index_map: dict[str, str] = {}
        idx = 1
        for msg in messages:
            # Build attachment suffix so agents know about shared images
            attachment_suffix = ""
            if msg.attachments:
                img_count = sum(1 for a in msg.attachments if a.type == "image")
                if img_count == 1:
                    attachment_suffix = " [Image attached]"
                elif img_count > 1:
                    attachment_suffix = f" [{img_count} images attached]"

            if msg.role == MessageRole.USER:
                lines.append(f"[{idx}] **User**: {msg.content}{attachment_suffix}")
                index_map[str(idx)] = msg.id
                idx += 1
            elif msg.role == MessageRole.AGENT and msg.agent_id:
                agent = self._registry.get(msg.agent_id)
                name = agent.name if agent else msg.agent_id
                lines.append(f"[{idx}] **{name}**: {msg.content[:400]}{attachment_suffix}")
                index_map[str(idx)] = msg.id
                idx += 1
        return lines, index_map

    def _build_agent_prompt(
        self,
        conversation: Conversation,
        agent_id: str,
        hint: str | None = None,
    ) -> tuple[str, dict[str, str]]:
        """Build the context prompt for an agent.

        Uses summary for prior turns and full messages only since the last
        user message, so agents see concise history + current round detail.

        Returns (prompt, index_map) where index_map maps "1","2",... to msg IDs.
        """
        # Find messages since the last user message (current round)
        current_round_msgs: list[Message] = []
        for msg in reversed(conversation.messages):
            current_round_msgs.insert(0, msg)
            if msg.role == MessageRole.USER:
                break

        context_lines, index_map = self._format_history(current_round_msgs)
        agent = self._registry.get(agent_id)
        name = agent.name if agent else agent_id
        role = agent.role if agent else "Agent"

        user_message = ""
        for msg in reversed(conversation.messages):
            if msg.role == MessageRole.USER:
                user_message = msg.content
                break

        has_topic = (
            conversation.topic
            and conversation.topic != "General discussion"
        )
        topic = conversation.topic if has_topic else "none"
        hint_line = f"[Focus]: {hint}" if hint else ""

        # Build participant roster
        participants = []
        for aid in conversation.participant_agent_ids:
            a = self._registry.get(aid)
            if a:
                tag = " (you)" if aid == agent_id else ""
                participants.append(f"- {a.name}, {a.role}{tag}")
        participants_line = "\n".join(participants)

        # Prepend summary of prior turns if available
        summary_line = ""
        if conversation.last_summary:
            summary_line = f"[Prior discussion summary]: {conversation.last_summary}"

        prompt = AGENT_CONTEXT_TEMPLATE.format(
            name=name,
            role=role,
            participants=participants_line,
            user_message=user_message,
            topic=topic,
            hint_line=hint_line,
            summary_line=summary_line,
            context=(
                "\n".join(context_lines) if context_lines else "(empty)"
            ),
        )
        return prompt, index_map

    # Public alias for ws.py voice path
    def build_agent_prompt(
        self, conversation: Conversation, agent_id: str, hint: str | None = None
    ) -> str:
        prompt, _ = self._build_agent_prompt(conversation, agent_id, hint=hint)
        return prompt

    def _get_ready_agents(self, conversation: Conversation) -> list[str]:
        """Return agent IDs that have a Mistral agent ready."""
        out = []
        for aid in conversation.participant_agent_ids:
            agent = self._registry.get(aid)
            if agent and agent.mistral_agent_id:
                out.append(aid)
        return out

    # ── Main entry point ─────────────────────────────────────────────────

    async def run_group_turn_streaming(
        self,
        conversation: Conversation,
        content: str,
        attachments: list[Attachment] | None = None,
        voice_mode: bool = False,
    ):
        """Turn-based group conversation.

        Each round:
          1. Classifier decides: parallel or sequential
          2. parallel  → all agents at once (casual / greeting)
             sequential → one-by-one, each seeing prior replies
          3. Grader decides: done, or another round needed

        Directed messages bypass all of this (single agent, done).
        """
        # --- TOPIC_GRADE ---
        if (
            not conversation.topic
            or conversation.topic == "General discussion"
        ):
            new_topic = await self.grade_topic(conversation)
            if new_topic:
                conversation.topic = new_topic
                yield ("topic_set", {"topic": new_topic})

        # User message ID for reply threading
        user_message_id = None
        for msg in reversed(conversation.messages):
            if msg.role == MessageRole.USER:
                user_message_id = msg.id
                break

        # Turn record for logging
        turn_record = TurnRecord(
            conversation_id=conversation.id,
            user_message=content,
            topic=conversation.topic,
        )

        # --- DIRECTED MESSAGE shortcut ---
        directed_agent = self._detect_directed_message(
            content, conversation.participant_agent_ids
        )
        if directed_agent:
            agent = self._registry.get(directed_agent)
            if agent and agent.mistral_agent_id:
                turn_record.directed = True
                turn_record.directed_agent = directed_agent
                turn_record.rounds.append(RoundRecord(
                    round=1,
                    mode="directed",
                    ranking=[{
                        "agent_id": directed_agent,
                        "should_respond": True,
                        "hint": "directed",
                    }],
                ))
                yield ("oracle_start", {
                    "directed": True,
                    "directed_agent": directed_agent,
                })
                yield ("oracle", {
                    "reasoning": f"{agent.name} was addressed directly",
                    "speakers": [{
                        "agent_id": directed_agent,
                        "agent_name": agent.name,
                        "should_respond": True,
                        "hint": "directed",
                    }],
                    "round": 1,
                    "mode": "directed",
                })
                yield ("turn_change", {
                    "agent_id": directed_agent,
                    "reply_to_id": user_message_id,
                })
                async for event in self._stream_single_agent(
                    conversation, directed_agent, voice_mode,
                    reply_to_id=user_message_id,
                ):
                    yield event
                yield ("oracle_end", {})
                log_turn(turn_record)
            return

        # --- CLASSIFY ---
        mode, goal = await self.classify_message(content)
        if voice_mode:
            mode = "sequential"
        turn_record.goal = goal
        agent_ids = self._get_ready_agents(conversation)
        if not agent_ids:
            return

        yield ("oracle_start", {
            "directed": False,
            "directed_agent": None,
            "goal": goal,
        })

        speakers_so_far: list[str] = []
        last_agent_message_id = user_message_id

        # --- ROUND LOOP ---
        for round_num in range(MAX_ROUNDS):
            reply_to_id = (
                last_agent_message_id
                if round_num > 0
                else user_message_id
            )

            # Rank agents by relevance
            ranking = await self.rank_agents(
                content, conversation, agent_ids,
                last_speaker=(
                    speakers_so_far[-1] if speakers_so_far else None
                ),
            )
            ranked_ids = [
                r["agent_id"] for r in ranking if r.get("should_respond")
            ]
            if not ranked_ids:
                ranked_ids = [ranking[0]["agent_id"]]
            hint_map = {
                r["agent_id"]: r.get("hint") for r in ranking
            }

            round_record = RoundRecord(
                round=round_num + 1,
                mode=mode,
                ranking=ranking,
            )

            # Notify frontend with ranking info
            enriched = []
            for r in ranking:
                agent = self._registry.get(r["agent_id"])
                enriched.append({
                    "agent_id": r["agent_id"],
                    "agent_name": agent.name if agent else r["agent_id"],
                    "should_respond": r.get("should_respond", True),
                    "hint": r.get("hint"),
                })
            yield ("oracle", {
                "reasoning": f"Round {round_num + 1} ({mode})",
                "speakers": enriched,
                "round": round_num + 1,
                "mode": mode,
            })

            # Emit filtered verdicts for agents ranked out
            for r in ranking:
                if not r.get("should_respond"):
                    agent = self._registry.get(r["agent_id"])
                    yield ("agent_verdict", {
                        "agent_id": r["agent_id"],
                        "agent_name": agent.name if agent else r["agent_id"],
                        "verdict": "filtered",
                    })

            # Run the appropriate mode with ranked agents
            responded_ids: list[str] = []
            last_msg_id = reply_to_id

            runner = (
                self._run_parallel if mode == "parallel"
                else self._run_sequential
            )
            agent_content_map: dict[str, str] = {}
            async for ev_type, ev_data in runner(
                conversation, ranked_ids, voice_mode, reply_to_id,
                hint_map=hint_map,
                goal=goal,
            ):
                yield (ev_type, ev_data)
                if ev_type == "message":
                    responded_ids.append(ev_data.agent_id)
                    last_msg_id = ev_data.id
                    agent_content_map[ev_data.agent_id] = ev_data.content[:200]
                if ev_type == "agent_verdict":
                    entry = {
                        "agent_id": ev_data["agent_id"],
                        "verdict": ev_data["verdict"],
                    }
                    agent_text = agent_content_map.get(ev_data["agent_id"])
                    if agent_text:
                        entry["content"] = agent_text
                    if ev_data.get("reply_to_id"):
                        entry["reply_to_id"] = ev_data["reply_to_id"]
                    round_record.agent_responses.append(entry)

            for aid in responded_ids:
                if aid not in speakers_so_far:
                    speakers_so_far.append(aid)
            if last_msg_id != reply_to_id:
                last_agent_message_id = last_msg_id

            if not responded_ids:
                turn_record.rounds.append(round_record)
                break

            # Grader (skip on last allowed round)
            if round_num < MAX_ROUNDS - 1:
                done, reasoning = await self.grade_completion(
                    conversation, content, goal=goal, mode=mode,
                )
                logger.info(
                    "Grader round %d: done=%s reason=%s",
                    round_num + 1, done, reasoning,
                )
                round_record.grader = {
                    "reasoning": reasoning,
                    "done": done,
                }
                yield ("grader", {
                    "reasoning": reasoning,
                    "done": done,
                    "round": round_num + 1,
                })
                turn_record.rounds.append(round_record)
                if done:
                    break
                # After a parallel round, switch to sequential for
                # follow-up so agents build on each other
                if mode == "parallel":
                    mode = "sequential"
            else:
                turn_record.rounds.append(round_record)

        # Summary
        if len(speakers_so_far) >= 2:
            summary = await self._generate_summary(
                conversation, speakers_so_far
            )
            if summary:
                turn_record.summary = summary
                conversation.last_summary = summary
                yield ("summary", {"content": summary})

        yield ("oracle_end", {})
        log_turn(turn_record)

    # ── Parallel mode ────────────────────────────────────────────────────

    async def _run_parallel(
        self,
        conversation: Conversation,
        agent_ids: list[str],
        voice_mode: bool,
        reply_to_id: str | None,
        hint_map: dict[str, str | None] | None = None,
        goal: str = "",
    ):
        """All agents respond concurrently. Yields events via queue."""
        hint_map = hint_map or {}
        queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()

        async def _run_agent(aid: str) -> None:
            try:
                full_text, flushed, agent_reply_to = await self._stream_to_queue(
                    queue, conversation, aid, voice_mode, reply_to_id,
                    hint=hint_map.get(aid),
                )
                agent = self._registry.get(aid)
                name = agent.name if agent else aid
                if full_text and flushed:
                    msg = Message(
                        role=MessageRole.AGENT,
                        agent_id=aid,
                        content=full_text,
                        reply_to_id=agent_reply_to,
                    )
                    conversation.messages.append(msg)
                    await queue.put(("message", msg))
                    await queue.put(("agent_verdict", {
                        "agent_id": aid,
                        "agent_name": name,
                        "verdict": "responded",
                        "reply_to_id": agent_reply_to,
                    }))
                else:
                    await queue.put(("agent_verdict", {
                        "agent_id": aid,
                        "agent_name": name,
                        "verdict": "passed",
                    }))
            except Exception:
                logger.exception("Parallel agent %s failed", aid)

        tasks = [
            asyncio.create_task(_run_agent(aid)) for aid in agent_ids
        ]

        async def _sentinel() -> None:
            await asyncio.gather(*tasks, return_exceptions=True)
            await queue.put(None)

        sentinel = asyncio.create_task(_sentinel())

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

        await sentinel

    # ── Sequential mode ──────────────────────────────────────────────────

    async def _run_sequential(
        self,
        conversation: Conversation,
        agent_ids: list[str],
        voice_mode: bool,
        reply_to_id: str | None,
        hint_map: dict[str, str | None] | None = None,
        goal: str = "",
    ):
        """Agents respond one-by-one, each seeing prior responses."""
        hint_map = hint_map or {}
        current_reply_to = reply_to_id

        for aid in agent_ids:
            agent = self._registry.get(aid)
            if not agent or not agent.mistral_agent_id:
                continue

            msg_id = _uuid.uuid4().hex[:12]
            was_interrupted = False
            prev_sentences = 0

            # Rebuild prompt so this agent sees previous agents' responses
            prompt, index_map = self._build_agent_prompt(
                conversation, aid, hint=hint_map.get(aid)
            )
            mistral_conv_id = conversation.mistral_conversation_ids.get(aid)
            full_text = ""
            buffered: list[str] = []
            flushed = False
            prefix_len = 7  # [NN]\n — enough for pass and reply prefix
            agent_reply_to = current_reply_to  # fallback

            agent_inputs = prompt
            if voice_mode:
                from ensemble.utils import VOICE_MODE_PREFIX
                agent_inputs = VOICE_MODE_PREFIX + prompt

            try:
                # Retry loop for Mistral 409 Conflict (conversation lock)
                max_retries = 3
                stream = None
                for attempt in range(max_retries):
                    try:
                        if mistral_conv_id:
                            stream = (
                                await self._client.beta.conversations
                                .append_stream_async(
                                    conversation_id=mistral_conv_id,
                                    inputs=agent_inputs,
                                )
                            )
                        else:
                            stream = (
                                await self._client.beta.conversations
                                .start_stream_async(
                                    agent_id=agent.mistral_agent_id,
                                    inputs=agent_inputs,
                                )
                            )
                        break  # success — exit retry loop
                    except Exception as exc:
                        if "409" in str(exc) and attempt < max_retries - 1:
                            delay = 1.0 * (attempt + 1)
                            logger.warning(
                                "Mistral 409 on agent %s attempt %d, retrying in %.1fs",
                                aid, attempt + 1, delay,
                            )
                            await asyncio.sleep(delay)
                        else:
                            raise

                if stream is None:
                    continue

                async for event in stream:
                    data = event.data
                    if (
                        hasattr(data, "conversation_id")
                        and data.conversation_id
                    ):
                        conversation.mistral_conversation_ids[aid] = (
                            data.conversation_id
                        )
                    if hasattr(data, "content"):
                        text = extract_text_from_content(
                            getattr(data, "content", "")
                        )
                        if text:
                            full_text += text
                            if not flushed:
                                buffered.append(text)
                                if len(full_text) >= prefix_len:
                                    if _is_pass(full_text):
                                        continue
                                    # Parse [N] reply prefix
                                    target, cleaned = _parse_reply_target(
                                        full_text, index_map
                                    )
                                    if target:
                                        agent_reply_to = target
                                    if cleaned != full_text:
                                        full_text = cleaned
                                        buffered = [cleaned]
                                    flushed = True
                                    yield (
                                        "turn_change",
                                        {
                                            "agent_id": aid,
                                            "reply_to_id": agent_reply_to,
                                        },
                                    )
                                    for c in buffered:
                                        yield (
                                            "chunk",
                                            {"agent_id": aid, "content": c},
                                        )
                                    buffered.clear()
                            else:
                                yield (
                                    "chunk",
                                    {"agent_id": aid, "content": text},
                                )
                                # Voice: sentence tracking + interruption
                                if voice_mode:
                                    curr = _count_sentences(full_text)
                                    if curr > prev_sentences:
                                        prev_sentences = curr
                                        yield ("message_partial", {
                                            "agent_id": aid,
                                            "content": full_text,
                                            "message_id": msg_id,
                                            "reply_to_id": agent_reply_to,
                                        })
                                        remaining = agent_ids[
                                            agent_ids.index(aid) + 1 :
                                        ]
                                        if (
                                            curr >= 2
                                            and curr % 2 == 0
                                            and remaining
                                        ):
                                            should, reason = (
                                                await self.check_interruption(
                                                    aid,
                                                    full_text,
                                                    goal,
                                                    remaining,
                                                )
                                            )
                                            if should:
                                                logger.info(
                                                    "Interrupting %s: %s",
                                                    aid,
                                                    reason,
                                                )
                                                yield (
                                                    "agent_cancel",
                                                    {
                                                        "agent_id": aid,
                                                        "reasoning": reason,
                                                    },
                                                )
                                                was_interrupted = True
                                                break

                # Handle unflushed buffer
                if not flushed:
                    if _is_pass(full_text):
                        logger.info("Agent %s passed (seq)", aid)
                        yield ("agent_verdict", {
                            "agent_id": aid,
                            "agent_name": agent.name,
                            "verdict": "passed",
                        })
                        continue
                    if full_text:
                        # Parse >>ID prefix from short response
                        target, cleaned = _parse_reply_target(
                            full_text, index_map
                        )
                        if target:
                            agent_reply_to = target
                        if cleaned != full_text:
                            full_text = cleaned
                            buffered = [cleaned]
                        flushed = True
                        yield (
                            "turn_change",
                            {
                                "agent_id": aid,
                                "reply_to_id": agent_reply_to,
                            },
                        )
                        for c in buffered:
                            yield (
                                "chunk",
                                {"agent_id": aid, "content": c},
                            )

                if full_text and flushed:
                    final_text = (
                        _trim_to_last_sentence(full_text)
                        if was_interrupted
                        else full_text
                    )
                    msg = Message(
                        id=msg_id,
                        role=MessageRole.AGENT,
                        agent_id=aid,
                        content=final_text,
                        reply_to_id=agent_reply_to,
                    )
                    conversation.messages.append(msg)
                    yield ("message", msg)
                    yield ("agent_verdict", {
                        "agent_id": aid,
                        "agent_name": agent.name,
                        "verdict": (
                            "interrupted" if was_interrupted else "responded"
                        ),
                        "reply_to_id": agent_reply_to,
                    })
                    current_reply_to = msg.id

            except Exception:
                logger.exception("Sequential agent %s failed", aid)

    # ── Shared streaming helper (for parallel mode) ──────────────────────

    async def _stream_to_queue(
        self,
        queue: asyncio.Queue,
        conversation: Conversation,
        agent_id: str,
        voice_mode: bool,
        reply_to_id: str | None,
        hint: str | None = None,
    ) -> tuple[str, bool, str | None]:
        """Stream one agent into a queue, buffering to detect [PASS] / [N].

        Returns (full_text, flushed, resolved_reply_to_id).
        """
        agent = self._registry.get(agent_id)
        if not agent or not agent.mistral_agent_id:
            return "", False, reply_to_id

        prompt, index_map = self._build_agent_prompt(conversation, agent_id, hint=hint)
        mistral_conv_id = conversation.mistral_conversation_ids.get(agent_id)
        full_text = ""
        buffered: list[str] = []
        flushed = False
        prefix_len = 7  # [NN]\n — enough for pass and reply prefix
        agent_reply_to = reply_to_id  # fallback

        agent_inputs = prompt
        if voice_mode:
            from ensemble.utils import VOICE_MODE_PREFIX
            agent_inputs = VOICE_MODE_PREFIX + prompt

        # Retry loop for Mistral 409 Conflict (conversation lock)
        max_retries = 3
        stream = None
        for attempt in range(max_retries):
            try:
                if mistral_conv_id:
                    stream = (
                        await self._client.beta.conversations.append_stream_async(
                            conversation_id=mistral_conv_id,
                            inputs=agent_inputs,
                        )
                    )
                else:
                    stream = (
                        await self._client.beta.conversations.start_stream_async(
                            agent_id=agent.mistral_agent_id,
                            inputs=agent_inputs,
                        )
                    )
                break  # success — exit retry loop
            except Exception as exc:
                if "409" in str(exc) and attempt < max_retries - 1:
                    delay = 1.0 * (attempt + 1)
                    logger.warning(
                        "Mistral 409 on agent %s attempt %d, retrying in %.1fs",
                        agent_id, attempt + 1, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        if stream is None:
            return full_text, flushed, agent_reply_to

        async for event in stream:
            data = event.data
            if hasattr(data, "conversation_id") and data.conversation_id:
                conversation.mistral_conversation_ids[agent_id] = (
                    data.conversation_id
                )
            if hasattr(data, "content"):
                text = extract_text_from_content(
                    getattr(data, "content", "")
                )
                if text:
                    full_text += text
                    if not flushed:
                        buffered.append(text)
                        if len(full_text) >= prefix_len:
                            if _is_pass(full_text):
                                continue
                            # Parse >>ID prefix
                            target, cleaned = _parse_reply_target(
                                full_text, index_map
                            )
                            if target:
                                agent_reply_to = target
                            if cleaned != full_text:
                                full_text = cleaned
                                buffered = [cleaned]
                            flushed = True
                            await queue.put((
                                "turn_change",
                                {
                                    "agent_id": agent_id,
                                    "reply_to_id": agent_reply_to,
                                },
                            ))
                            for c in buffered:
                                await queue.put((
                                    "chunk",
                                    {"agent_id": agent_id, "content": c},
                                ))
                            buffered.clear()
                    else:
                        await queue.put((
                            "chunk",
                            {"agent_id": agent_id, "content": text},
                        ))

        # Handle unflushed
        if not flushed:
            if _is_pass(full_text):
                logger.info("Agent %s passed (parallel)", agent_id)
                return full_text, False, agent_reply_to
            if full_text:
                # Parse >>ID prefix from short response
                target, cleaned = _parse_reply_target(
                    full_text, index_map
                )
                if target:
                    agent_reply_to = target
                if cleaned != full_text:
                    full_text = cleaned
                    buffered = [cleaned]
                flushed = True
                await queue.put((
                    "turn_change",
                    {"agent_id": agent_id, "reply_to_id": agent_reply_to},
                ))
                for c in buffered:
                    await queue.put((
                        "chunk",
                        {"agent_id": agent_id, "content": c},
                    ))

        return full_text, flushed, agent_reply_to

    # ── Single agent (directed messages) ─────────────────────────────────

    async def _stream_single_agent(
        self,
        conversation: Conversation,
        agent_id: str,
        voice_mode: bool = False,
        reply_to_id: str | None = None,
    ):
        """Async generator for a single agent (directed messages)."""
        agent = self._registry.get(agent_id)
        if not agent or not agent.mistral_agent_id:
            return

        prompt, index_map = self._build_agent_prompt(conversation, agent_id)
        mistral_conv_id = conversation.mistral_conversation_ids.get(agent_id)
        full_text = ""
        buffered: list[str] = []
        flushed = False
        prefix_len = 7

        try:
            agent_inputs = prompt
            if voice_mode:
                from ensemble.utils import VOICE_MODE_PREFIX
                agent_inputs = VOICE_MODE_PREFIX + prompt

            # Retry loop for Mistral 409 Conflict (conversation lock)
            max_retries = 3
            stream = None
            for attempt in range(max_retries):
                try:
                    if mistral_conv_id:
                        stream = (
                            await self._client.beta.conversations
                            .append_stream_async(
                                conversation_id=mistral_conv_id,
                                inputs=agent_inputs,
                            )
                        )
                    else:
                        stream = (
                            await self._client.beta.conversations
                            .start_stream_async(
                                agent_id=agent.mistral_agent_id,
                                inputs=agent_inputs,
                            )
                        )
                    break  # success — exit retry loop
                except Exception as exc:
                    if "409" in str(exc) and attempt < max_retries - 1:
                        delay = 1.0 * (attempt + 1)
                        logger.warning(
                            "Mistral 409 on agent %s attempt %d, retrying in %.1fs",
                            agent_id, attempt + 1, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise

            if stream is None:
                return

            async for event in stream:
                data = event.data
                if (
                    hasattr(data, "conversation_id")
                    and data.conversation_id
                ):
                    conversation.mistral_conversation_ids[agent_id] = (
                        data.conversation_id
                    )
                if hasattr(data, "content"):
                    text = extract_text_from_content(
                        getattr(data, "content", "")
                    )
                    if text:
                        full_text += text
                        if not flushed:
                            buffered.append(text)
                            if len(full_text) >= prefix_len:
                                target, cleaned = _parse_reply_target(
                                    full_text, index_map
                                )
                                if target:
                                    reply_to_id = target
                                if cleaned != full_text:
                                    full_text = cleaned
                                    buffered = [cleaned]
                                flushed = True
                                for c in buffered:
                                    yield ("chunk", {
                                        "agent_id": agent_id,
                                        "content": c,
                                    })
                                buffered.clear()
                        else:
                            yield ("chunk", {
                                "agent_id": agent_id,
                                "content": text,
                            })

            # Handle unflushed buffer
            if not flushed and full_text:
                target, cleaned = _parse_reply_target(
                    full_text, index_map
                )
                if target:
                    reply_to_id = target
                if cleaned != full_text:
                    full_text = cleaned
                    buffered = [cleaned]
                for c in buffered:
                    yield ("chunk", {
                        "agent_id": agent_id,
                        "content": c,
                    })

            if full_text:
                msg = Message(
                    role=MessageRole.AGENT,
                    agent_id=agent_id,
                    content=full_text,
                    reply_to_id=reply_to_id,
                )
                conversation.messages.append(msg)
                yield ("message", msg)

        except Exception:
            logger.exception("Agent %s streaming failed", agent_id)

    # ── Summary ──────────────────────────────────────────────────────────

    async def _generate_summary(
        self, conversation: Conversation, speakers: list[str]
    ) -> str | None:
        history, _ = self._format_history(
            conversation.messages[-MAX_CONTEXT_MESSAGES:]
        )
        names = []
        for s in speakers:
            agent = self._registry.get(s)
            names.append(agent.name if agent else s)
        topic = conversation.topic or "the discussion"

        try:
            response = await self._client.chat.complete_async(
                model=settings.oracle_model,
                messages=cast(Any, [
                    {"role": "system", "content": (
                        "Summarize this discussion round in 2-3 bullet "
                        "points. Key decisions, disagreements, action "
                        "items. Be concise."
                    )},
                    {"role": "user", "content": (
                        f"Topic: {topic}\n"
                        f"Speakers: {', '.join(names)}\n\n"
                        + "\n".join(history)
                    )},
                ]),
            )
            return _get_text(response.choices[0].message.content)
        except Exception:
            logger.exception("Summary generation failed")
            return None
