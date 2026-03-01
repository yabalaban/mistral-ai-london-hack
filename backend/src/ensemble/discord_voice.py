"""Discord voice handler — streams audio through ElevenLabs realtime STT.

Uses py-cord's Sink for audio capture, resamples from 48kHz stereo to
16kHz mono, and streams into ElevenLabs RealtimeSTTSession (same as the
web frontend). Agent responses are played back via ElevenLabs TTS.
"""

from __future__ import annotations

import asyncio
import audioop
import base64
import io
import logging
import struct
import tempfile
from pathlib import Path
from typing import Any

import discord
from discord.sinks import Sink

from ensemble.agents.models import AgentProfile
from ensemble.agents.registry import AgentRegistry
from ensemble.conversations.models import (
    Conversation,
    Message,
    MessageRole,
)
from ensemble.oracle.engine import OracleEngine
from ensemble.voice.stt import RealtimeSTTSession
from ensemble.voice.tts import synthesize

logger = logging.getLogger(__name__)


def _resample_48k_stereo_to_16k_mono(pcm_48k_stereo: bytes) -> bytes:
    """Convert 48kHz stereo 16-bit PCM to 16kHz mono 16-bit PCM."""
    # Stereo to mono
    mono = audioop.tomono(pcm_48k_stereo, 2, 1, 1)
    # 48kHz to 16kHz (ratio 3:1)
    mono_16k, _ = audioop.ratecv(mono, 2, 1, 48000, 16000, None)
    return mono_16k


def _make_streaming_sink(
    audio_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop
) -> Sink:
    """Create a Sink that streams audio to our queue while recording.
    
    We use a regular Sink and patch its write method to also forward
    resampled audio, avoiding issues with the @Filters.container decorator.
    """
    sink = Sink()
    original_write = sink.write

    def patched_write(data: bytes, user: int) -> None:
        # Call original (handles filters + audio_data storage)
        original_write(data, user)
        # Also resample and forward to STT queue
        try:
            mono_16k = _resample_48k_stereo_to_16k_mono(data)
            if len(mono_16k) > 0:
                loop.call_soon_threadsafe(
                    audio_queue.put_nowait, (user, mono_16k)
                )
        except Exception:
            pass

    sink.write = patched_write
    
    # py-cord calls format_audio on stop — no-op for streaming
    if not hasattr(sink, 'format_audio'):
        sink.format_audio = lambda *a, **kw: None
    
    return sink


class DiscordVoiceHandler:
    """Manages bot in a voice channel with streaming ElevenLabs STT."""

    def __init__(
        self,
        registry: AgentRegistry,
        oracle: OracleEngine,
        mistral_client: Any,
        webhook_mgr: Any,
    ) -> None:
        self.registry = registry
        self.oracle = oracle
        self.mistral_client = mistral_client
        self.webhook_mgr = webhook_mgr
        self._vc: discord.VoiceClient | None = None
        self._text_channel: discord.TextChannel | None = None
        self._conv: Conversation | None = None
        self._playing_lock = asyncio.Lock()
        self._active = False
        self._stt_session: RealtimeSTTSession | None = None
        self._audio_queue: asyncio.Queue | None = None
        self._feed_task: asyncio.Task | None = None
        self._listen_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        return self._vc is not None and self._vc.is_connected()

    async def join(
        self,
        voice_channel: discord.VoiceChannel,
        text_channel: discord.TextChannel,
        conv: Conversation,
    ) -> None:
        if self._vc and self._vc.is_connected():
            await self._vc.disconnect(force=True)

        self._vc = await voice_channel.connect()
        self._text_channel = text_channel
        self._conv = conv
        self._active = True

        # Set up audio queue and streaming sink
        self._audio_queue = asyncio.Queue()
        loop = asyncio.get_event_loop()
        sink = _make_streaming_sink(self._audio_queue, loop)

        # Start ElevenLabs realtime STT with MANUAL commit (mute = commit)
        self._stt_session = RealtimeSTTSession(auto_commit=False)
        await self._stt_session.connect()

        # Start recording with our streaming sink
        self._vc.start_recording(sink, self._on_recording_stopped)

        # Background tasks: feed audio to STT + listen for transcripts
        self._feed_task = asyncio.create_task(self._feed_audio_loop())
        self._listen_task = asyncio.create_task(self._listen_transcripts())

        logger.info("Joined voice channel: %s (streaming STT)", voice_channel.name)

    async def _on_recording_stopped(self, sink: Sink, *args) -> None:
        logger.info("Recording stopped")

    async def _feed_audio_loop(self) -> None:
        """Read from audio queue and feed to ElevenLabs STT."""
        chunk_count = 0
        while self._active:
            try:
                user_id, pcm_16k = await asyncio.wait_for(
                    self._audio_queue.get(), timeout=1.0
                )
                chunk_count += 1
                if chunk_count == 1:
                    logger.info("First audio chunk received from user %s (%d bytes)", user_id, len(pcm_16k))
                elif chunk_count % 100 == 0:
                    logger.info("Audio chunk #%d (queue size: %d)", chunk_count, self._audio_queue.qsize())
                if self._stt_session:
                    b64 = base64.b64encode(pcm_16k).decode()
                    await self._stt_session.send_audio(b64)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Feed audio error")

    async def _listen_transcripts(self) -> None:
        """Listen for STT events and trigger agent responses."""
        if not self._stt_session:
            return

        try:
            async for event in self._stt_session.iter_events():
                if not self._active:
                    break

                if event.is_final:
                    text = event.text.strip()
                    if not text or len(text) <= 2:
                        continue

                    logger.info("Final transcript: %s", text)

                    # Post transcription in text channel
                    if self._text_channel:
                        try:
                            await self._text_channel.send(f"🎤 {text}")
                        except discord.HTTPException:
                            pass

                    # Record and respond
                    if self._conv:
                        user_msg = Message(role=MessageRole.USER, content=text)
                        self._conv.messages.append(user_msg)
                        asyncio.create_task(self._respond(text))

                else:
                    # Partial transcript — could show typing indicator
                    pass

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Transcript listener error")

    async def _respond(self, content: str) -> None:
        if not self._conv or not self._vc:
            return

        try:
            async for event_type, data in self.oracle.run_group_turn_streaming(
                self._conv, content, None, voice_mode=True
            ):
                if event_type == "message":
                    msg = data
                    agent = self.registry.get(msg.agent_id)
                    if agent and msg.content:
                        # Post text for attribution
                        if self._text_channel:
                            try:
                                await self.webhook_mgr.send_as_agent(
                                    self._text_channel, agent, msg.content
                                )
                            except Exception:
                                logger.exception("Failed to send text for %s", msg.agent_id)

                        # Play TTS
                        await self._play_agent_tts(agent, msg.content)

        except Exception:
            logger.exception("Voice response round failed")

    async def _play_agent_tts(self, agent: AgentProfile, text: str) -> None:
        if not self._vc or not self._vc.is_connected():
            return

        voice_id = agent.voice_id or ""
        try:
            audio_bytes = await synthesize(text, voice_id=voice_id)
        except Exception:
            logger.exception("TTS failed for %s", agent.id)
            return

        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.write(audio_bytes)
        tmp.close()

        async with self._playing_lock:
            if not self._vc or not self._vc.is_connected():
                Path(tmp.name).unlink(missing_ok=True)
                return

            source = discord.FFmpegPCMAudio(tmp.name)
            done_event = asyncio.Event()

            def after_play(error: Exception | None) -> None:
                if error:
                    logger.error("Playback error: %s", error)
                Path(tmp.name).unlink(missing_ok=True)
                if self._vc and self._vc.loop:
                    self._vc.loop.call_soon_threadsafe(done_event.set)

            self._vc.play(source, after=after_play)
            await done_event.wait()

    async def on_user_mute(self) -> None:
        """User muted — commit STT to finalize transcript."""
        if self._stt_session and not self._stt_session._closed:
            logger.info("Committing STT (user muted)")
            await self._stt_session.commit()

    async def on_user_unmute(self) -> None:
        """User unmuted — reconnect STT if connection was closed."""
        if self._stt_session and self._stt_session._closed:
            logger.info("Reconnecting STT (user unmuted)")
            self._stt_session = RealtimeSTTSession(auto_commit=False)
            await self._stt_session.connect()
            # Restart the transcript listener
            if self._listen_task and self._listen_task.done():
                self._listen_task = asyncio.create_task(self._listen_transcripts())

    async def leave(self) -> None:
        self._active = False

        if self._feed_task and not self._feed_task.done():
            self._feed_task.cancel()
            try:
                await self._feed_task
            except asyncio.CancelledError:
                pass

        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self._stt_session:
            await self._stt_session.close()
            self._stt_session = None

        if self._vc:
            if self._vc.recording:
                try:
                    self._vc.stop_recording()
                except Exception:
                    pass
            if self._vc.is_connected():
                await self._vc.disconnect(force=True)
            self._vc = None

        logger.info("Left voice channel")
