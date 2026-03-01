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
import logging
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
from ensemble.oracle.engine import OracleEngine
from ensemble.utils import build_inputs, extract_text_from_content

logger = logging.getLogger(__name__)

# Agent avatar URLs — DiceBear pixel-art avatars as defaults
AGENT_AVATARS = {
    "emma": "https://api.dicebear.com/9.x/personas/png?seed=emma&size=256",
    "sofia": "https://api.dicebear.com/9.x/personas/png?seed=sofia&size=256",
    "dan": "https://api.dicebear.com/9.x/personas/png?seed=dan&size=256",
    "marcus": "https://api.dicebear.com/9.x/personas/png?seed=marcus&size=256",
    "kim": "https://api.dicebear.com/9.x/personas/png?seed=kim&size=256",
}


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
    ) -> discord.WebhookMessage:
        wh = await self.get_webhook(channel, agent)
        avatar = agent.avatar_url or AGENT_AVATARS.get(agent.id, "")
        kwargs: dict[str, Any] = {
            "content": content,
            "username": f"{agent.name} • {agent.role}",
            "wait": True,
        }
        if avatar:
            kwargs["avatar_url"] = avatar
        if thread:
            kwargs["thread"] = thread
        return await wh.send(**kwargs)


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


def _get_state(channel_id: int, default_agents: list[str]) -> ChannelState:
    if channel_id not in _channels:
        _channels[channel_id] = ChannelState(default_agents)
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
        self._default_agents: list[str] = list(registry.agents.keys())
        self._channel_locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, channel_id: int) -> asyncio.Lock:
        if channel_id not in self._channel_locks:
            self._channel_locks[channel_id] = asyncio.Lock()
        return self._channel_locks[channel_id]

    async def on_ready(self) -> None:
        logger.info("Discord bot ready: %s (id=%s)", self.user, self.user.id)
        logger.info("Default agents: %s", self._default_agents)

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Auto-join/leave voice channels based on user presence."""
        if member.bot:
            return

        # User joined a voice channel
        if after.channel and (before.channel != after.channel):
            # Check if bot is already in this channel
            if self.voice_handler.is_connected:
                return

            # Find a text channel to post transcriptions in
            text_channel = None
            if after.channel.category:
                for ch in after.channel.category.text_channels:
                    text_channel = ch
                    break
            if not text_channel and member.guild.text_channels:
                text_channel = member.guild.text_channels[0]

            if not text_channel:
                return

            state = _get_state(text_channel.id, self._default_agents)

            try:
                await self.voice_handler.join(after.channel, text_channel, state.conv)
                await text_channel.send(
                    f"🎙️ Joined **{after.channel.name}** — unmute to talk, mute to send!"
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

                # Check for existing thread first
                existing_threads = channel.threads
                for t in existing_threads:
                    if t.name == f"💬 {agent.name}":
                        state.agent_threads[agent_id] = t
                        state.thread_to_agent[t.id] = agent_id
                        break

                if agent_id not in state.agent_threads:
                    # Also check archived threads
                    try:
                        async for t in channel.archived_threads():
                            if t.name == f"💬 {agent.name}":
                                await t.edit(archived=False)
                                state.agent_threads[agent_id] = t
                                state.thread_to_agent[t.id] = agent_id
                                break
                    except Exception:
                        pass

                if agent_id not in state.agent_threads:
                    try:
                        # Create a starter message for the thread
                        avatar = agent.avatar_url or AGENT_AVATARS.get(agent.id, "")
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
                        logger.info("Created thread for %s: %s", agent_id, thread.id)
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
                state = _get_state(parent.id, self._default_agents)
                agent_id = state.thread_to_agent.get(channel.id)
                if agent_id:
                    await self._handle_thread_message(
                        message, parent, channel, state, agent_id
                    )
                    return
            return  # Ignore other threads

        if not isinstance(channel, discord.TextChannel):
            return

        state = _get_state(channel.id, self._default_agents)

        content = message.content.strip()
        attachments = self._extract_attachments(message)
        if not content and not attachments:
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
        logger.info("Conv participants: %s", state.conv.participant_agent_ids)

        # Run group round inline (no thread)
        lock = self._get_lock(channel.id)
        async with lock:
            # Show typing while processing
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

    # ── Group round ──────────────────────────────────────────────────

    async def _run_group(
        self,
        conv: Conversation,
        content: str,
        attachments: list[Attachment],
        channel: discord.TextChannel,
    ) -> None:
        """Run an oracle round and post agent responses inline in the channel."""
        try:
            async for event_type, data in self.oracle.run_group_turn_streaming(
                conv, content, attachments or None
            ):
                if event_type == "message":
                    msg = data
                    agent = self.registry.get(msg.agent_id)
                    if agent and msg.content:
                        await self.webhook_mgr.send_as_agent(channel, agent, msg.content)

                elif event_type == "summary":
                    summary = data.get("content", "")
                    if summary:
                        embed = discord.Embed(
                            title="📋 Round Summary",
                            description=summary,
                            color=0x06B6D4,
                        )
                        await channel.send(embed=embed)

        except Exception:
            logger.exception("Discord group round failed")
            try:
                await channel.send("⚠️ Something went wrong processing that message.")
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
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond("Use in a text channel.", ephemeral=True)
            return

        state = _get_state(ctx.channel_id, bot._default_agents)
        await ctx.respond("⏳ Setting up agent threads...", ephemeral=True)
        await bot.ensure_agent_threads(ctx.channel, state)
        names = [bot.registry.get(a).name for a in state.agent_ids if bot.registry.get(a)]
        await ctx.edit(content=f"✅ Agent threads created: {', '.join(names)}")

    @bot.slash_command(
        name="invite",
        description="Add an agent to this channel",
        guild_ids=guild_ids,
    )
    async def cmd_invite(
        ctx: discord.ApplicationContext,
        agent: discord.Option(str, description="Agent ID (e.g. emma, sofia, dan)"),
    ) -> None:
        agent_id = agent.strip().lower()
        profile = bot.registry.get(agent_id)
        if not profile:
            available = ", ".join(bot.registry.agents.keys())
            await ctx.respond(f"Unknown agent `{agent_id}`. Available: {available}", ephemeral=True)
            return

        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond("Use in a text channel.", ephemeral=True)
            return

        state = _get_state(ctx.channel_id, bot._default_agents)
        if agent_id in state.agent_ids:
            await ctx.respond(f"**{profile.name}** is already in this channel.", ephemeral=True)
            return

        state.agent_ids.append(agent_id)
        state.conv.participant_agent_ids = list(state.agent_ids)

        # Create thread for the new agent
        await bot.ensure_agent_threads(ctx.channel, state)
        await ctx.respond(f"✅ **{profile.name}** ({profile.role}) has joined the channel!")

    @bot.slash_command(
        name="dismiss",
        description="Remove an agent from this channel",
        guild_ids=guild_ids,
    )
    async def cmd_dismiss(
        ctx: discord.ApplicationContext,
        agent: discord.Option(str, description="Agent ID to remove"),
    ) -> None:
        agent_id = agent.strip().lower()
        profile = bot.registry.get(agent_id)

        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond("Use in a text channel.", ephemeral=True)
            return

        state = _get_state(ctx.channel_id, bot._default_agents)
        if agent_id not in state.agent_ids:
            await ctx.respond(f"`{agent_id}` is not in this channel.", ephemeral=True)
            return

        state.agent_ids.remove(agent_id)
        state.conv.participant_agent_ids = list(state.agent_ids)

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
    async def cmd_topic(
        ctx: discord.ApplicationContext,
        topic: discord.Option(str, description="Topic for the agents to discuss"),
    ) -> None:
        state = _get_state(ctx.channel_id, bot._default_agents)
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
        state = _get_state(ctx.channel_id, bot._default_agents)
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
