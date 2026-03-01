"""Discord frontend for Circles — runs alongside (not instead of) FastAPI.

UX design:
  - Main text channels = group chat. All invited agents respond inline.
  - Per-agent threads = auto-created, act as 1:1 DM + "member list" in sidebar.
  - /invite and /dismiss control which agents are active per channel.
  - /call joins voice, agents listen and speak via TTS.
  - No auto-threading per message — clean, flat conversation.

Uses py-cord for Sink/voice recording support.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import re
from pathlib import Path
from typing import Any

import discord

from ensemble.agents.models import AgentProfile
from ensemble.agents.registry import AgentRegistry
from ensemble.conversations.models import (
    Attachment,
    Conversation,
    ConversationType,
    Message,
    MessageRole,
)
from ensemble.discord_voice import DiscordVoiceHandler
from ensemble.events import SystemEvent, event_bus
from ensemble.oracle.engine import OracleEngine
from ensemble.conversations.manager import _handle_function_calls
from ensemble.utils import build_inputs, extract_reply, extract_text_from_content

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message splitting for Discord's 2000-char limit
# ---------------------------------------------------------------------------


def _split_message(content: str, limit: int = 2000) -> list[str]:
    """Split content into chunks that fit within Discord's character limit.

    Tries to split at paragraph/newline boundaries first, then sentence/space
    boundaries. Avoids splitting inside fenced code blocks when possible.
    """
    if len(content) <= limit:
        return [content]

    chunks: list[str] = []
    while content:
        if len(content) <= limit:
            chunks.append(content)
            break

        # Check if we'd split inside an open code block
        candidate = content[:limit]
        fence_count = candidate.count("```")
        if fence_count % 2 == 1:
            # Odd number of fences = we're inside a code block.
            # Try to find the closing fence and split after it.
            close_idx = content.find("```", candidate.rfind("```") + 3)
            if close_idx != -1 and close_idx + 3 <= limit * 2:
                # Include the closing fence in this chunk
                split_at = close_idx + 3
                chunks.append(content[:split_at])
                content = content[split_at:].lstrip("\n")
                continue

        # Find last newline before limit
        split_at = content.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = content.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(content[:split_at])
        content = content[split_at:].lstrip("\n")

    return chunks


# ---------------------------------------------------------------------------
# Slides embed helper
# ---------------------------------------------------------------------------

_SLIDES_URL_RE = re.compile(r"(https?://[^\s]+/api/slides/([a-f0-9]+))(?:/pdf)?")


def _build_slides_embed(content: str) -> discord.Embed | None:
    """If content contains slide URLs, return a Discord embed linking to them."""
    match = _SLIDES_URL_RE.search(content)
    if not match:
        return None

    base_url = match.group(1)
    if base_url.endswith("/pdf"):
        base_url = base_url[: -len("/pdf")]

    embed = discord.Embed(
        title="Presentation Created",
        color=0x06B6D4,
    )
    embed.add_field(
        name="View Slides",
        value=f"[Open in browser]({base_url})",
        inline=True,
    )
    return embed


# ---------------------------------------------------------------------------
# Webhook manager
# ---------------------------------------------------------------------------

class WebhookManager:
    """Per-agent webhooks so each agent appears as a distinct user."""

    def __init__(self) -> None:
        self._cache: dict[tuple[int, str], discord.Webhook] = {}

    async def get_webhook(
        self, channel: discord.TextChannel, agent: AgentProfile
    ) -> discord.Webhook:
        key = (channel.id, agent.id)
        if key in self._cache:
            return self._cache[key]

        existing = await channel.webhooks()
        for wh in existing:
            if wh.name == f"circles-{agent.id}":
                self._cache[key] = wh
                return wh

        wh = await channel.create_webhook(name=f"circles-{agent.id}")
        self._cache[key] = wh
        return wh

    async def send_as_agent(
        self,
        channel: discord.TextChannel,
        agent: AgentProfile,
        content: str,
        *,
        thread: discord.Thread | None = None,
        silent: bool = False,
    ) -> discord.WebhookMessage:
        wh = await self.get_webhook(channel, agent)
        avatar = (
            agent.avatar_url
            or f"https://api.dicebear.com/9.x/personas/png?seed={agent.id}&size=256"
        )

        # Detect slide URLs and build an embed if present
        slide_embed = _build_slides_embed(content)

        chunks = _split_message(content)
        last_msg = None
        for i, chunk in enumerate(chunks):
            kwargs: dict[str, Any] = {
                "content": chunk,
                "username": f"{agent.name} • {agent.role}",
                "wait": True,
            }
            if avatar:
                kwargs["avatar_url"] = avatar
            if thread:
                kwargs["thread"] = thread
            if silent:
                # py-cord webhooks don't support flags kwarg directly;
                # pass the raw integer flag for SUPPRESS_NOTIFICATIONS (1 << 12)
                kwargs["flags"] = 4096
            # Attach the slides embed to the last chunk
            if slide_embed and i == len(chunks) - 1:
                kwargs["embeds"] = [slide_embed]
            last_msg = await wh.send(**kwargs)
        return last_msg


# ---------------------------------------------------------------------------
# Channel state
# ---------------------------------------------------------------------------

class ChannelState:
    """Tracks conversation + active agents + agent threads per channel."""

    def __init__(self, agent_ids: list[str]) -> None:
        self.agent_ids = list(agent_ids)
        self.conv = Conversation(
            type=ConversationType.GROUP if len(agent_ids) > 1 else ConversationType.DIRECT,
            participant_agent_ids=list(agent_ids),
        )
        # agent_id -> thread for 1:1 conversations
        self.agent_threads: dict[str, discord.Thread] = {}
        # thread_id -> agent_id (reverse lookup)
        self.thread_to_agent: dict[int, str] = {}
        # Per-agent 1:1 conversations (separate from group)
        self.agent_convs: dict[str, Conversation] = {}

    def update_agents(self, agent_ids: list[str]) -> None:
        self.agent_ids = list(agent_ids)
        self.conv.participant_agent_ids = list(agent_ids)


_channels: dict[int, ChannelState] = {}

_CHANNELS_FILE = Path(__file__).resolve().parent.parent.parent / "channel_agents.json"


def _load_channel_agents() -> dict[str, list[str]]:
    """Load channel→agent_ids mapping from disk."""
    if _CHANNELS_FILE.exists():
        try:
            return _json.loads(_CHANNELS_FILE.read_text())
        except Exception:
            logger.warning("Failed to load %s, starting fresh", _CHANNELS_FILE)
    return {}


def _save_channel_agents() -> None:
    """Persist current channel→agent_ids mapping to disk."""
    data: dict[str, list[str]] = {}
    for ch_id, state in _channels.items():
        if state.agent_ids:  # only persist non-empty channels
            data[str(ch_id)] = state.agent_ids
    try:
        _CHANNELS_FILE.write_text(_json.dumps(data, indent=2))
    except Exception:
        logger.exception("Failed to save channel agents")


# Load persisted mappings on module import
_persisted = _load_channel_agents()
for _ch_str, _agent_list in _persisted.items():
    try:
        _channels[int(_ch_str)] = ChannelState(_agent_list)
    except (ValueError, TypeError):
        pass
if _persisted:
    logger.info("Loaded channel agents for %d channels from disk", len(_persisted))


def _get_state(channel_id: int) -> ChannelState:
    if channel_id not in _channels:
        logger.info("Creating new empty ChannelState for %d (known: %s)", channel_id, list(_channels.keys()))
        _channels[channel_id] = ChannelState([])
    return _channels[channel_id]


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True


class CirclesBot(discord.Bot):
    """Discord bot that surfaces Circles agents."""

    def __init__(
        self,
        registry: AgentRegistry,
        oracle: OracleEngine,
        mistral_client: Any,
        guild_id: int,
    ) -> None:
        super().__init__(intents=intents)
        self.registry = registry
        self.oracle = oracle
        self.mistral_client = mistral_client
        self.guild_id = guild_id
        self.webhook_mgr = WebhookManager()
        self.voice_handler = DiscordVoiceHandler(
            registry, oracle, mistral_client, self.webhook_mgr
        )
        self._channel_locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, channel_id: int) -> asyncio.Lock:
        if channel_id not in self._channel_locks:
            self._channel_locks[channel_id] = asyncio.Lock()
        return self._channel_locks[channel_id]

    async def on_ready(self) -> None:
        logger.info("Discord bot ready: %s (id=%s)", self.user, self.user.id)
        logger.info("Available agents: %s", list(self.registry.agents.keys()))

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Auto-join/leave voice channels based on user presence."""
        if member.bot:
            return

        logger.info(
            "Voice state: user=%s before=%s(mute=%s) after=%s(mute=%s)",
            member, before.channel, before.self_mute, after.channel, after.self_mute,
        )

        # User joined a voice channel (or switched channels)
        if after.channel and (before.channel != after.channel):
            # join() handles move_to() if already connected — no manual leave needed

            # Find matching text channel by exact name
            voice_name = after.channel.name.lower().strip()
            text_channel = None
            for ch in member.guild.text_channels:
                if ch.name.lower().strip() == voice_name:
                    text_channel = ch
                    break

            if not text_channel:
                logger.warning("No text channel matching voice channel #%s", after.channel.name)
                # Try to notify any channel in same category
                fallback = None
                if after.channel.category:
                    for ch in after.channel.category.text_channels:
                        fallback = ch
                        break
                if fallback:
                    try:
                        await fallback.send(
                            f"No text channel named **#{after.channel.name}** found — "
                            f"create one to enable voice agents."
                        )
                    except Exception:
                        pass
                return

            state = _get_state(text_channel.id)
            logger.info(
                "Voice #%s → text #%s (%d agents)",
                after.channel.name, text_channel.name, len(state.agent_ids),
            )

            if not state.agent_ids:
                try:
                    await text_channel.send(
                        f"No agents in **#{text_channel.name}** — use `/invite` to add agents before joining voice."
                    )
                except Exception:
                    pass
                return

            try:
                await self.voice_handler.join(after.channel, text_channel, state.conv)
                agent_names = [
                    self.registry.get(a).name
                    for a in state.agent_ids
                    if self.registry.get(a)
                ]
                names_str = ", ".join(f"**{n}**" for n in agent_names)
                await text_channel.send(
                    f"{names_str} joined **{after.channel.name}** — unmute to talk, mute to send!",
                    silent=True,
                )
            except Exception:
                logger.exception("Auto-join voice failed")
            return

        # User muted — commit STT (acts as "send" / PTT release)
        if after.channel and not before.self_mute and after.self_mute:
            logger.info("User %s muted — committing STT", member)
            await self.voice_handler.on_user_mute()
            return

        # User unmuted — resume listening
        if after.channel and before.self_mute and not after.self_mute:
            logger.info("User %s unmuted — resuming listening", member)
            await self.voice_handler.on_user_unmute()
            return

        # User left a voice channel — check if bot should leave
        if before.channel and (before.channel != after.channel):
            if not self.voice_handler.is_connected:
                return
            if self.voice_handler._vc and self.voice_handler._vc.channel == before.channel:
                humans = [m for m in before.channel.members if not m.bot]
                if not humans:
                    text_ch = self.voice_handler._text_channel
                    await self.voice_handler.leave()
                    if text_ch:
                        try:
                            await text_ch.send("👋 Everyone left — disconnected from voice.")
                        except Exception:
                            pass

    # ── Agent thread management ──────────────────────────────────────

    async def ensure_agent_threads(
        self, channel: discord.TextChannel, state: ChannelState
    ) -> None:
        """Create threads for agents that don't have one yet.

        Each agent gets a thread named "💬 AgentName" — these appear in the
        thread sidebar, emulating a member list. Typing in them = 1:1 chat.
        """
        # Fetch ALL active threads from the API (not the stale gateway cache)
        try:
            fetched = await channel.guild.fetch_active_threads()
            active_threads = [
                t for t in fetched.threads if t.parent_id == channel.id
            ]
        except Exception:
            logger.warning("Failed to fetch active threads, falling back to cache")
            active_threads = list(channel.threads)

        for agent_id in state.agent_ids:
            if agent_id in state.agent_threads:
                # Check if thread still exists / is accessible
                thread = state.agent_threads[agent_id]
                try:
                    await thread.fetch_message(thread.id)
                except Exception:
                    # Thread might be archived — try to unarchive
                    try:
                        await thread.edit(archived=False)
                    except Exception:
                        del state.agent_threads[agent_id]
                        if thread.id in state.thread_to_agent:
                            del state.thread_to_agent[thread.id]

            if agent_id not in state.agent_threads:
                agent = self.registry.get(agent_id)
                if not agent:
                    continue

                thread_name = f"💬 {agent.name}"

                # Check active threads (fetched from API)
                for t in active_threads:
                    if t.name == thread_name:
                        logger.info("Found existing active thread for %s: %s", agent_id, t.id)
                        state.agent_threads[agent_id] = t
                        state.thread_to_agent[t.id] = agent_id
                        break

                if agent_id not in state.agent_threads:
                    # Also check archived threads
                    try:
                        async for t in channel.archived_threads():
                            if t.name == thread_name:
                                logger.info("Found archived thread for %s, unarchiving", agent_id)
                                await t.edit(archived=False)
                                state.agent_threads[agent_id] = t
                                state.thread_to_agent[t.id] = agent_id
                                break
                    except Exception:
                        pass

                if agent_id not in state.agent_threads:
                    try:
                        # Create a starter message for the thread
                        avatar = (
                            agent.avatar_url
                            or f"https://api.dicebear.com/9.x/personas/png?seed={agent.id}&size=256"
                        )
                        embed = discord.Embed(
                            title=agent.name,
                            description=f"**{agent.role}**\n\n{agent.bio}",
                            color=0x06B6D4,
                        )
                        if avatar:
                            embed.set_thumbnail(url=avatar)
                        embed.add_field(
                            name="Personality", value=agent.personality[:200], inline=False
                        )
                        if agent.tools:
                            embed.add_field(
                                name="Tools", value=", ".join(agent.tools), inline=False
                            )
                        embed.set_footer(text="Send a message in this thread to chat 1:1")

                        msg = await channel.send(embed=embed)
                        thread = await msg.create_thread(
                            name=f"💬 {agent.name}",
                            auto_archive_duration=10080,  # 7 days
                        )
                        state.agent_threads[agent_id] = thread
                        state.thread_to_agent[thread.id] = agent_id
                        logger.info("Created NEW thread for %s: %s", agent_id, thread.id)
                    except Exception:
                        logger.exception("Failed to create thread for %s", agent_id)

    # ── Message handling ─────────────────────────────────────────────

    async def on_message(self, message: discord.Message) -> None:  # noqa: C901
        logger.info(
            "on_message: author=%s bot=%s channel=%s type=%s content=%r",
            message.author, message.author.bot, message.channel,
            type(message.channel).__name__, message.content[:50],
        )

        if message.author.bot:
            logger.debug("Ignoring bot message")
            return
        if not message.guild:
            logger.debug("Ignoring DM")
            return

        # Determine if this is a thread message (1:1) or channel message (group)
        channel = message.channel

        if isinstance(channel, discord.Thread) and channel.parent:
            # Check if this is an agent thread
            parent = channel.parent
            if isinstance(parent, discord.TextChannel):
                state = _get_state(parent.id)
                agent_id = state.thread_to_agent.get(channel.id)
                if agent_id:
                    await self._handle_thread_message(
                        message, parent, channel, state, agent_id
                    )
                    return
            return  # Ignore other threads

        # Accept text channels and voice channel text chat
        if isinstance(channel, discord.VoiceChannel):
            # Voice channel text chat — route through the voice handler's conversation
            await self._handle_voice_text(message, channel)
            return

        if not isinstance(channel, discord.TextChannel):
            return

        state = _get_state(channel.id)

        content = message.content.strip()
        attachments = self._extract_attachments(message)
        if not content and not attachments:
            return

        # No agents in channel — hint to /invite (only once per channel)
        if not state.agent_ids:
            logger.info("No agents for channel_id=%d (#%s), sending hint", channel.id, channel.name)
            available = ", ".join(f"`{a}`" for a in self.registry.agents.keys())
            await channel.send(
                f"No agents in this channel yet. Use `/invite <agent>` to add one.\n"
                f"Available: {available}"
            )
            return

        # Record user message
        user_msg = Message(
            role=MessageRole.USER,
            content=content,
            attachments=attachments,
        )
        state.conv.messages.append(user_msg)

        logger.info("Processing group message in #%s: %r", channel.name, content[:50])
        logger.info("Active agents: %s", state.agent_ids)

        # Run group round inline
        lock = self._get_lock(channel.id)
        async with lock:
            async with channel.typing():
                await self._run_group(state.conv, content, attachments, channel)

    async def _handle_thread_message(
        self,
        message: discord.Message,
        parent_channel: discord.TextChannel,
        thread: discord.Thread,
        state: ChannelState,
        agent_id: str,
    ) -> None:
        """Handle a 1:1 message in an agent's thread."""
        agent = self.registry.get(agent_id)
        if not agent or not agent.mistral_agent_id:
            return

        content = message.content.strip()
        attachments = self._extract_attachments(message)
        if not content and not attachments:
            return

        # Get or create per-agent conversation
        if agent_id not in state.agent_convs:
            state.agent_convs[agent_id] = Conversation(
                type=ConversationType.DIRECT,
                participant_agent_ids=[agent_id],
            )

        conv = state.agent_convs[agent_id]
        user_msg = Message(
            role=MessageRole.USER, content=content, attachments=attachments
        )
        conv.messages.append(user_msg)

        inputs = build_inputs(content, attachments)

        async with thread.typing():
            full_text = await self._stream_agent(
                conv, agent_id, agent.mistral_agent_id, inputs
            )

        if full_text:
            agent_msg = Message(
                role=MessageRole.AGENT, agent_id=agent_id, content=full_text
            )
            conv.messages.append(agent_msg)
            await self.webhook_mgr.send_as_agent(
                parent_channel, agent, full_text, thread=thread
            )

    def _extract_attachments(self, message: discord.Message) -> list[Attachment]:
        attachments: list[Attachment] = []
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                attachments.append(Attachment(type="image", url=att.url))
        return attachments

    async def _extract_file_contents(self, message: discord.Message) -> str:
        """Download text-based file attachments and return their contents."""
        parts: list[str] = []
        TEXT_TYPES = {"text/", "application/json", "application/xml", "application/javascript"}
        TEXT_EXTS = {".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".xml", ".yaml", ".yml",
                     ".html", ".css", ".sql", ".sh", ".rb", ".go", ".rs", ".java", ".c", ".cpp",
                     ".h", ".toml", ".ini", ".cfg", ".env", ".log", ".tex", ".rst"}
        for att in message.attachments:
            is_text = (att.content_type and any(att.content_type.startswith(t) for t in TEXT_TYPES))
            is_text_ext = any(att.filename.lower().endswith(ext) for ext in TEXT_EXTS)
            if is_text or is_text_ext:
                try:
                    data = await att.read()
                    text = data.decode("utf-8", errors="replace")
                    parts.append(f"--- {att.filename} ---\n{text}")
                    logger.info("Read file attachment: %s (%d chars)", att.filename, len(text))
                except Exception:
                    logger.exception("Failed to read attachment %s", att.filename)
        return "\n\n".join(parts)

    async def _handle_voice_text(
        self, message: discord.Message, voice_channel: discord.VoiceChannel
    ) -> None:
        """Handle text messages in voice channel chat.

        Reuses the voice handler's _respond() for oracle + TTS + text channel logging.
        Also posts responses in the voice channel text chat.
        Supports images and file attachments (text files read inline).
        """
        if not self.voice_handler.is_connected or not self.voice_handler._conv:
            logger.info("Voice text ignored — not in voice")
            return

        content = message.content.strip()
        attachments = self._extract_attachments(message)
        file_contents = await self._extract_file_contents(message)

        if file_contents:
            content = f"{content}\n\n{file_contents}" if content else file_contents

        if not content and not attachments:
            return

        logger.info("Voice text chat: %r (%d attachments, %d file chars)",
                     content[:80], len(attachments), len(file_contents))

        conv = self.voice_handler._conv
        user_msg = Message(
            role=MessageRole.USER,
            content=content,
            attachments=attachments,
        )
        conv.messages.append(user_msg)

        # Reuse voice handler's _respond — handles oracle, TTS, text channel posting
        await self.voice_handler._respond(
            content, attachments=attachments or None, voice_channel=voice_channel
        )

    # ── Group round ──────────────────────────────────────────────────

    async def _run_group(
        self,
        conv: Conversation,
        content: str,
        attachments: list[Attachment],
        channel: discord.TextChannel,
    ) -> None:
        """Run an oracle round and post agent responses inline in the channel."""
        logger.info("Discord group round start: channel=#%s content=%r", channel.name, content[:80])
        source_label = f"#{channel.name}"
        conv_id = conv.id

        def _emit(etype: str, edata: dict | None = None) -> None:
            event_bus.emit(SystemEvent(
                type=etype,
                conversation_id=conv_id,
                source="discord",
                source_label=source_label,
                data=edata or {},
            ))

        _emit("user_message", {"content": content})

        try:
            async for event_type, data in self.oracle.run_group_turn_streaming(
                conv, content, attachments or None
            ):
                logger.info("Discord oracle event: %s", event_type)

                if event_type == "oracle_start":
                    logger.info("  directed=%s goal=%s", data.get("directed"), data.get("goal"))
                    _emit("oracle_start", data)

                elif event_type == "oracle":
                    logger.info("  speakers=%s round=%s", data.get("speakers"), data.get("round"))
                    _emit("oracle", data)

                elif event_type == "turn_change":
                    logger.info("  turn → %s", data.get("agent_id"))
                    _emit("turn_change", data)

                elif event_type == "message":
                    msg = data
                    logger.info("  message from %s (%d chars)", msg.agent_id, len(msg.content or ""))
                    _emit("message", {
                        "agent_id": msg.agent_id,
                        "content": msg.content or "",
                        "reply_to_id": getattr(msg, "reply_to_id", None),
                    })
                    agent = self.registry.get(msg.agent_id)
                    if agent and msg.content:
                        await self.webhook_mgr.send_as_agent(channel, agent, msg.content)

                elif event_type == "topic_set":
                    topic = data.get("topic", "")
                    logger.info("  topic=%s", topic)
                    _emit("topic_set", data)
                    if topic:
                        conv.topic = topic

                elif event_type == "grader":
                    logger.info("  grader: done=%s round=%s", data.get("done"), data.get("round"))
                    _emit("grader", data)

                elif event_type == "agent_verdict":
                    logger.info("  verdict: %s=%s", data.get("agent_id"), data.get("verdict"))
                    _emit("agent_verdict", data)

                elif event_type == "summary":
                    summary = data.get("content", "")
                    logger.info("  summary (%d chars)", len(summary))
                    _emit("summary", data)
                    if summary:
                        embed = discord.Embed(
                            title="Round Summary",
                            description=summary,
                            color=0x06B6D4,
                        )
                        await channel.send(embed=embed)

                elif event_type in ("chunk", "message_partial", "agent_cancel"):
                    pass  # Too frequent / internal — skip dashboard

                else:
                    _emit(event_type, data if isinstance(data, dict) else {})

            logger.info("Discord group round complete")
        except Exception:
            logger.exception("Discord group round failed")
            try:
                await channel.send("Something went wrong processing that message.")
            except discord.HTTPException:
                pass

    # ── Mistral streaming ────────────────────────────────────────────

    async def _stream_agent(
        self,
        conv: Conversation,
        agent_id: str,
        mistral_agent_id: str,
        inputs: str | list[dict],
    ) -> str:
        full_text = ""
        has_function_call = False
        mistral_conv_id = conv.mistral_conversation_ids.get(agent_id)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                if mistral_conv_id:
                    stream = await self.mistral_client.beta.conversations.append_stream_async(
                        conversation_id=mistral_conv_id,
                        inputs=inputs,
                        handoff_execution="client",
                    )
                else:
                    stream = await self.mistral_client.beta.conversations.start_stream_async(
                        agent_id=mistral_agent_id,
                        inputs=inputs,
                        handoff_execution="client",
                    )

                async for event in stream:
                    ev_data = event.data
                    if hasattr(ev_data, "conversation_id") and ev_data.conversation_id:
                        conv.mistral_conversation_ids[agent_id] = ev_data.conversation_id

                    # Detect function calls
                    dtype = type(ev_data).__name__
                    if "FunctionCall" in dtype:
                        has_function_call = True

                    if hasattr(ev_data, "content"):
                        text = extract_text_from_content(ev_data.content)
                        if text:
                            full_text += text
                break

            except Exception as exc:
                if "409" in str(exc) and attempt < max_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))
                else:
                    logger.exception("Mistral streaming failed for %s", agent_id)
                    break

        # If there was a function call, handle tool execution and get final response
        if has_function_call:
            mistral_conv_id = conv.mistral_conversation_ids.get(agent_id)
            if mistral_conv_id:
                try:
                    response = await self.mistral_client.beta.conversations.append_async(
                        conversation_id=mistral_conv_id,
                        inputs="Please proceed with the tool call.",
                    )
                    response = await _handle_function_calls(
                        self.mistral_client, response, conv, agent_id
                    )
                    tool_reply = extract_reply(response)
                    if tool_reply:
                        full_text = tool_reply
                except Exception:
                    logger.exception("Function call handling failed for %s", agent_id)

        return full_text


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

def register_commands(bot: CirclesBot) -> None:
    guild_ids = [bot.guild_id]

    @bot.slash_command(
        name="agents", description="List available Circles agents", guild_ids=guild_ids
    )
    async def cmd_agents(ctx: discord.ApplicationContext) -> None:
        agents = list(bot.registry.agents.values())
        if not agents:
            await ctx.respond("No agents loaded.", ephemeral=True)
            return

        lines = []
        for a in agents:
            status = "🟢" if a.mistral_agent_id else "🔴"
            tools = f" · tools: {', '.join(a.tools)}" if a.tools else ""
            lines.append(f"{status} **{a.name}** — {a.role}{tools}")

        await ctx.respond("\n".join(lines))

    @bot.slash_command(
        name="init",
        description="Set up agent threads in this channel (run once per channel)",
        guild_ids=guild_ids,
    )
    async def cmd_init(ctx: discord.ApplicationContext) -> None:
        logger.info("/init called: channel=%s interaction_id=%s", ctx.channel, ctx.interaction.id)
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond("Use in a text channel.", ephemeral=True)
            return

        state = _get_state(ctx.channel_id)
        await ctx.respond("⏳ Setting up agent threads...", ephemeral=True)
        await bot.ensure_agent_threads(ctx.channel, state)
        names = [bot.registry.get(a).name for a in state.agent_ids if bot.registry.get(a)]
        await ctx.edit(content=f"✅ Agent threads created: {', '.join(names)}")

    @bot.slash_command(
        name="invite",
        description="Add an agent to this channel",
        guild_ids=guild_ids,
    )
    @discord.option("agent", type=str, description="Agent ID (e.g. emma, sofia, dan)")
    async def cmd_invite(ctx: discord.ApplicationContext, agent: str) -> None:
        logger.info("/invite called: agent=%r channel=%s interaction_id=%s", agent, ctx.channel, ctx.interaction.id)
        agent_id = agent.strip().lower()
        profile = bot.registry.get(agent_id)
        if not profile:
            available = ", ".join(bot.registry.agents.keys())
            await ctx.respond(f"Unknown agent `{agent_id}`. Available: {available}", ephemeral=True)
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond("Use in a text channel.", ephemeral=True)
            return

        state = _get_state(ctx.channel_id)
        if agent_id in state.agent_ids:
            await ctx.respond(f"**{profile.name}** is already in this channel.", ephemeral=True)
            return

        state.agent_ids.append(agent_id)
        state.conv.participant_agent_ids = list(state.agent_ids)
        _save_channel_agents()

        await ctx.respond(f"**{profile.name}** ({profile.role}) has joined the channel.")

    @bot.slash_command(
        name="dismiss",
        description="Remove an agent from this channel",
        guild_ids=guild_ids,
    )
    @discord.option("agent", type=str, description="Agent ID to remove")
    async def cmd_dismiss(ctx: discord.ApplicationContext, agent: str) -> None:
        logger.info("/dismiss called: agent=%r channel=%s", agent, ctx.channel)
        agent_id = agent.strip().lower()
        profile = bot.registry.get(agent_id)

        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond("Use in a text channel.", ephemeral=True)
            return

        state = _get_state(ctx.channel_id)
        if agent_id not in state.agent_ids:
            await ctx.respond(f"`{agent_id}` is not in this channel.", ephemeral=True)
            return

        state.agent_ids.remove(agent_id)
        state.conv.participant_agent_ids = list(state.agent_ids)
        _save_channel_agents()

        # Archive the agent's thread
        thread = state.agent_threads.pop(agent_id, None)
        if thread:
            state.thread_to_agent.pop(thread.id, None)
            try:
                await thread.edit(archived=True)
            except Exception:
                pass

        name = profile.name if profile else agent_id
        await ctx.respond(f"👋 **{name}** has left the channel.")

    @bot.slash_command(
        name="reset", description="Reset conversation history", guild_ids=guild_ids
    )
    async def cmd_reset(ctx: discord.ApplicationContext) -> None:
        channel_id = ctx.channel_id
        if channel_id in _channels:
            old = _channels[channel_id]
            _channels[channel_id] = ChannelState(old.agent_ids)
            # Preserve thread mappings
            _channels[channel_id].agent_threads = old.agent_threads
            _channels[channel_id].thread_to_agent = old.thread_to_agent
        await ctx.respond("🔄 Conversation history cleared.", ephemeral=True)

    @bot.slash_command(
        name="topic", description="Set the discussion topic", guild_ids=guild_ids
    )
    @discord.option("topic", type=str, description="Topic for the agents to discuss")
    async def cmd_topic(ctx: discord.ApplicationContext, topic: str) -> None:
        state = _get_state(ctx.channel_id)
        state.conv.topic = topic
        await ctx.respond(f"📌 Topic set: **{topic}**")

    @bot.slash_command(
        name="hangup", description="Force bot to leave voice channel", guild_ids=guild_ids
    )
    async def cmd_hangup(ctx: discord.ApplicationContext) -> None:
        if not bot.voice_handler.is_connected:
            await ctx.respond("Not in a voice channel.", ephemeral=True)
            return
        await bot.voice_handler.leave()
        await ctx.respond("👋 Left voice channel.")

    @bot.slash_command(
        name="who", description="Show which agents are active in this channel", guild_ids=guild_ids
    )
    async def cmd_who(ctx: discord.ApplicationContext) -> None:
        state = _get_state(ctx.channel_id)
        lines = []
        for aid in state.agent_ids:
            agent = bot.registry.get(aid)
            if agent:
                thread = state.agent_threads.get(aid)
                thread_link = f" · <#{thread.id}>" if thread else ""
                lines.append(f"• **{agent.name}** — {agent.role}{thread_link}")
        if lines:
            await ctx.respond("**Active agents:**\n" + "\n".join(lines))
        else:
            await ctx.respond("No agents in this channel. Use `/invite` to add some.")

    @bot.slash_command(
        name="create_agent",
        description="Create a new AI agent with a custom personality",
        guild_ids=guild_ids,
    )
    @discord.option("name", type=str, description="Agent name")
    @discord.option("role", type=str, description="Agent role (e.g. 'Data Scientist')")
    @discord.option("personality", type=str, description="Personality traits", required=False, default="")
    @discord.option("tools", type=str, description="Comma-separated tools: create_slides, code_interpreter, web_search, image_generation", required=False, default="")
    async def cmd_create_agent(
        ctx: discord.ApplicationContext,
        name: str,
        role: str,
        personality: str,
        tools: str,
    ) -> None:
        agent_id = name.lower().replace(" ", "_")
        if bot.registry.get(agent_id):
            await ctx.respond(f"Agent **{name}** already exists.")
            return

        tool_list = [t.strip() for t in tools.split(",") if t.strip()] if tools else []
        profile = AgentProfile(
            id=agent_id,
            name=name,
            role=role,
            bio=f"{name} is a {role}.",
            personality=personality or "Helpful, knowledgeable, collaborative",
            instructions=(
                f"You are {name}, a {role}. "
                + (f"Your personality: {personality}. " if personality else "")
                + "Be helpful and engage naturally in conversation."
            ),
            model="mistral-large-2512",
            tools=tool_list,
        )

        bot.registry.add_agent(agent_id, profile)

        # Persist to disk
        from pathlib import Path
        import json as _json

        agents_dir = Path(__file__).resolve().parent.parent / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / f"{agent_id}.json").write_text(
            _json.dumps(
                {
                    "id": agent_id,
                    "name": name,
                    "role": role,
                    "bio": profile.bio,
                    "personality": profile.personality,
                    "instructions": profile.instructions,
                    "model": profile.model,
                    "tools": tool_list,
                },
                indent=2,
            )
        )

        # Sync to Mistral
        try:
            await bot.registry.sync_single_to_mistral(agent_id)
        except Exception as e:
            logger.warning("Failed to sync agent %s to Mistral: %s", agent_id, e)

        await ctx.respond(
            f"Created agent **{name}** ({role})"
            + (f" with tools: {', '.join(tool_list)}" if tool_list else "")
            + f". Use `/invite {name}` to add them to this channel."
        )
