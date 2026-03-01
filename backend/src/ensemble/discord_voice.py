"""Discord voice handler — streams audio through ElevenLabs realtime STT.

Uses py-cord's Sink for audio capture, resamples from 48kHz stereo to
16kHz mono, and streams into ElevenLabs RealtimeSTTSession (same as the
web frontend). Agent responses are played back via ElevenLabs TTS.
"""

from __future__ import annotations

import asyncio
import audioop
import base64
import logging
import os
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
from ensemble.events import SystemEvent, event_bus
from ensemble.oracle.engine import OracleEngine
from ensemble.voice.stt import RealtimeSTTSession
from ensemble.voice.tts import DEFAULT_MODEL, DEFAULT_VOICE_ID

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
            logger.exception("Audio resampling failed (user=%s, %d bytes)", user, len(data))

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
        self._response_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        return self._vc is not None and self._vc.is_connected()

    async def join(
        self,
        voice_channel: discord.VoiceChannel,
        text_channel: discord.TextChannel,
        conv: Conversation,
    ) -> None:
        logger.info("Voice join requested: channel=%s, text_channel=%s", voice_channel.name, text_channel.name)

        if self._vc and self._vc.is_connected():
            logger.info("Disconnecting from previous voice channel")
            await self._vc.disconnect(force=True)

        self._vc = await voice_channel.connect()
        logger.info("Voice connected to #%s", voice_channel.name)
        self._text_channel = text_channel
        self._conv = conv
        self._active = True

        # Set up audio queue and streaming sink
        self._audio_queue = asyncio.Queue()
        loop = asyncio.get_event_loop()
        sink = _make_streaming_sink(self._audio_queue, loop)
        logger.info("Audio queue and streaming sink created")

        # STT session created lazily on unmute or first audio (not eagerly)
        self._stt_session = None

        # Start recording with our streaming sink
        self._vc.start_recording(sink, self._on_recording_stopped)
        logger.info("Recording started with streaming sink")

        # Background task: feed audio to STT (listener started on demand)
        self._feed_task = asyncio.create_task(self._feed_audio_loop())
        self._listen_task = None
        logger.info("Voice pipeline active: feed_audio task started, STT on demand")

    async def _on_recording_stopped(self, sink: Sink, *args) -> None:
        logger.info("Recording stopped")

    async def _ensure_stt(self) -> None:
        """Create a fresh STT session + listener if not already active."""
        if self._stt_session and not self._stt_session._closed:
            return  # already connected
        logger.info("Creating new STT session")
        self._stt_session = RealtimeSTTSession(auto_commit=False)
        await self._stt_session.connect()
        # (Re)start the transcript listener
        if self._listen_task is None or self._listen_task.done():
            self._listen_task = asyncio.create_task(self._listen_transcripts())
        logger.info("STT session ready")

    async def _feed_audio_loop(self) -> None:
        """Read from audio queue and feed to ElevenLabs STT.

        Creates STT session on demand when audio first arrives.
        Detects PTT release: if no audio for >1.5s after receiving, commits STT.
        """
        chunk_count = 0
        _SILENCE_TIMEOUT = 1.5  # seconds without audio → commit
        was_receiving = False

        while self._active:
            try:
                user_id, pcm_16k = await asyncio.wait_for(
                    self._audio_queue.get(), timeout=_SILENCE_TIMEOUT
                )
                # Audio arrived — ensure STT is connected
                if not self._stt_session or self._stt_session._closed:
                    try:
                        await self._ensure_stt()
                    except Exception:
                        logger.exception("Failed to create STT session")
                        continue

                was_receiving = True
                chunk_count += 1
                if chunk_count == 1:
                    logger.info("First audio chunk from user %s (%d bytes)", user_id, len(pcm_16k))
                elif chunk_count % 100 == 0:
                    logger.info("Audio chunk #%d (queue size: %d)", chunk_count, self._audio_queue.qsize())
                if self._stt_session and not self._stt_session._closed:
                    b64 = base64.b64encode(pcm_16k).decode()
                    await self._stt_session.send_audio(b64)
            except asyncio.TimeoutError:
                # No audio for _SILENCE_TIMEOUT — if we were receiving, treat as PTT release
                if was_receiving and self._stt_session and not self._stt_session._closed:
                    logger.info("Audio silence detected (PTT release) — committing STT")
                    try:
                        await self._stt_session.commit()
                    except Exception:
                        logger.exception("PTT auto-commit failed")
                    was_receiving = False
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Feed audio error")

    async def _listen_transcripts(self) -> None:
        """Listen for STT events and trigger agent responses.

        Runs until the STT connection closes, then exits.
        A new listener is started by _ensure_stt() when audio resumes.
        """
        if not self._stt_session:
            return

        logger.info("Transcript listener started")
        try:
            async for event in self._stt_session.iter_events():
                if not self._active:
                    break

                if event.is_final:
                    text = event.text.strip()
                    if not text or len(text) <= 2:
                        logger.debug("Skipping short transcript: %r", event.text)
                        continue

                    logger.info("Final transcript: %r", text)

                    # Post transcription in text channel (silent — no push notification)
                    if self._text_channel:
                        try:
                            await self._text_channel.send(f"🎤 {text}", silent=True)
                        except discord.HTTPException:
                            pass

                    # Record and respond
                    if self._conv:
                        user_msg = Message(role=MessageRole.USER, content=text)
                        self._conv.messages.append(user_msg)
                        if self._response_task and not self._response_task.done():
                            self._response_task.cancel()
                        self._response_task = asyncio.create_task(self._respond(text))

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Transcript listener error")

        logger.info("Transcript listener ended (STT connection closed)")

    async def _respond(
        self,
        content: str,
        attachments: list | None = None,
        voice_channel: Any | None = None,
    ) -> None:
        """Run oracle round: post text responses + play TTS.

        Args:
            content: User message text.
            attachments: Optional image/file attachments.
            voice_channel: If set, also post text responses there (voice text chat).
        """
        if not self._conv or not self._vc:
            logger.warning("_respond called but conv=%s vc=%s", bool(self._conv), bool(self._vc))
            return

        conv_id = self._conv.id
        ch_name = self._text_channel.name if self._text_channel else "voice"
        source_label = f"🎙#{ch_name}"
        voice_mode = attachments is None  # STT = voice_mode, text chat = not

        def _emit(etype: str, edata: dict | None = None) -> None:
            event_bus.emit(SystemEvent(
                type=etype,
                conversation_id=conv_id,
                source="discord-voice",
                source_label=source_label,
                data=edata or {},
            ))

        logger.info("Oracle start (voice_mode=%s): %r", voice_mode, content[:80])
        _emit("user_message", {"content": content})

        try:
            async for event_type, data in self.oracle.run_group_turn_streaming(
                self._conv, content, attachments, voice_mode=voice_mode
            ):
                logger.info("Oracle event: %s", event_type)

                if event_type == "turn_change":
                    logger.info("  turn_change → agent_id=%s", data.get("agent_id"))
                    _emit("turn_change", data)

                elif event_type == "oracle_start":
                    _emit("oracle_start", data)

                elif event_type == "oracle":
                    _emit("oracle", data)

                elif event_type == "message":
                    msg = data
                    logger.info("  message from %s (%d chars)", msg.agent_id, len(msg.content or ""))
                    _emit("message", {
                        "agent_id": msg.agent_id,
                        "content": msg.content or "",
                    })
                    agent = self.registry.get(msg.agent_id)
                    if agent and msg.content:
                        # Post to linked text channel
                        if self._text_channel:
                            try:
                                await self.webhook_mgr.send_as_agent(
                                    self._text_channel, agent, msg.content
                                )
                            except Exception:
                                logger.exception("Failed to send text for %s", msg.agent_id)

                        # Post to voice channel text chat (if text-initiated)
                        if voice_channel:
                            try:
                                await self.webhook_mgr.send_as_agent(
                                    voice_channel, agent, msg.content
                                )
                            except Exception:
                                logger.warning("Webhook failed for voice channel, using plain send")
                                try:
                                    await voice_channel.send(f"**{agent.name}**: {msg.content}")
                                except Exception:
                                    logger.exception("Failed to send to voice channel")

                        # Queue TTS (don't block oracle loop)
                        asyncio.create_task(self._play_agent_tts(agent, msg.content))

                elif event_type == "grader":
                    logger.info("  grader: done=%s", data.get("done"))
                    _emit("grader", data)

                elif event_type == "agent_verdict":
                    _emit("agent_verdict", data)

                elif event_type == "topic_set":
                    _emit("topic_set", data)

                elif event_type == "summary":
                    _emit("summary", data)

                elif event_type in ("chunk", "message_partial", "agent_cancel"):
                    pass

                else:
                    _emit(event_type, data if isinstance(data, dict) else {})

            logger.info("Oracle round complete for: %r", content[:50])
        except Exception:
            logger.exception("Voice response round failed")

    async def _play_agent_tts(self, agent: AgentProfile, text: str) -> None:
        """Stream TTS audio to Discord voice — starts playing as chunks arrive."""
        if not self._vc or not self._vc.is_connected():
            logger.warning("TTS skipped — voice client not connected")
            return

        from elevenlabs.client import AsyncElevenLabs
        from ensemble.config import settings

        if not settings.elevenlabs_api_key:
            logger.warning("TTS skipped — no ElevenLabs API key")
            return

        voice_id = agent.voice_id or DEFAULT_VOICE_ID
        logger.info("TTS streaming: agent=%s, voice_id=%s, %d chars", agent.id, voice_id, len(text))

        # Create a pipe: we write MP3 chunks to write_fd, FFmpeg reads from read_fd
        read_fd, write_fd = os.pipe()

        async def _feed_tts() -> None:
            """Stream ElevenLabs audio chunks into the pipe."""
            total = 0
            chunks = 0
            write_file = os.fdopen(write_fd, "wb")
            try:
                client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
                audio_stream = client.text_to_speech.stream(
                    text=text,
                    voice_id=voice_id,
                    model_id=DEFAULT_MODEL,
                )
                async for chunk in audio_stream:
                    if isinstance(chunk, bytes) and chunk:
                        write_file.write(chunk)
                        write_file.flush()
                        total += len(chunk)
                        chunks += 1
                        if chunks == 1:
                            logger.info("TTS first chunk: %d bytes (agent=%s)", len(chunk), agent.id)
                logger.info("TTS stream done: %d chunks, %d bytes (agent=%s)", chunks, total, agent.id)
            except Exception:
                logger.exception("TTS streaming failed for %s", agent.id)
            finally:
                write_file.close()

        async with self._playing_lock:
            if not self._vc or not self._vc.is_connected():
                os.close(read_fd)
                os.close(write_fd)
                return

            # Start feeding TTS chunks in background
            feed_task = asyncio.create_task(_feed_tts())

            # FFmpeg reads from pipe, decodes MP3 → PCM for Discord
            read_file = os.fdopen(read_fd, "rb")
            source = discord.FFmpegPCMAudio(read_file, pipe=True)
            done_event = asyncio.Event()

            def after_play(error: Exception | None) -> None:
                if error:
                    logger.error("FFmpeg playback error: %s", error)
                else:
                    logger.info("FFmpeg playback complete for %s", agent.id)
                try:
                    read_file.close()
                except Exception:
                    pass
                if self._vc and self._vc.loop:
                    self._vc.loop.call_soon_threadsafe(done_event.set)

            try:
                logger.info("FFmpeg streaming playback started for %s", agent.id)
                self._vc.play(source, after=after_play)
            except Exception:
                logger.exception("play() raised for %s", agent.id)
                feed_task.cancel()
                try:
                    read_file.close()
                except Exception:
                    pass
                return

            await done_event.wait()
            await feed_task  # ensure feed completes cleanly

    async def on_user_mute(self) -> None:
        """User muted — commit STT to finalize transcript."""
        if self._stt_session and not self._stt_session._closed:
            logger.info("Committing STT (user muted)")
            await self._stt_session.commit()

    async def on_user_unmute(self) -> None:
        """User unmuted — create fresh STT session."""
        logger.info("User unmuted — ensuring STT session")
        try:
            await self._ensure_stt()
        except Exception:
            logger.exception("Failed to create STT on unmute")

    async def leave(self) -> None:
        logger.info("Voice leave: starting cleanup")
        self._active = False

        if self._feed_task and not self._feed_task.done():
            logger.info("  Cancelling feed_audio task")
            self._feed_task.cancel()
            try:
                await self._feed_task
            except asyncio.CancelledError:
                pass

        if self._listen_task and not self._listen_task.done():
            logger.info("  Cancelling listen_transcripts task")
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self._stt_session:
            logger.info("  Closing STT session")
            await self._stt_session.close()
            self._stt_session = None

        if self._vc:
            if self._vc.recording:
                logger.info("  Stopping recording")
                try:
                    self._vc.stop_recording()
                except Exception:
                    logger.exception("  Failed to stop recording")
            if self._vc.is_connected():
                logger.info("  Disconnecting voice client")
                await self._vc.disconnect(force=True)
            self._vc = None

        logger.info("Voice leave: cleanup complete")
