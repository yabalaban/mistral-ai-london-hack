"""Speech-to-text: batch (Mistral Voxtral) and realtime (ElevenLabs SDK)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mistralai import Mistral
from mistralai.models import File

from ensemble.config import settings

logger = logging.getLogger(__name__)

STT_BATCH_MODEL = "voxtral-mini-latest"


async def transcribe_audio(client: Mistral, audio_data: bytes, language: str = "en") -> str:
    """Transcribe audio bytes using Mistral batch STT."""
    try:
        result = await client.audio.transcriptions.complete_async(
            model=STT_BATCH_MODEL,
            file=File(file_name="audio.wav", content=audio_data),
            language=language,
        )
        return result.text or ""
    except Exception:
        logger.exception("STT transcription failed")
        return ""


async def transcribe_file(client: Mistral, file_path: Path, language: str = "en") -> str:
    """Transcribe an audio file using Mistral batch STT."""
    audio_data = file_path.read_bytes()
    return await transcribe_audio(client, audio_data, language)


# ---------------------------------------------------------------------------
# Realtime STT via ElevenLabs SDK (manual commit for PTT)
# ---------------------------------------------------------------------------


@dataclass
class TranscriptEvent:
    """A transcript event from the realtime STT session."""

    text: str
    is_final: bool


class RealtimeSTTSession:
    """Manages a realtime STT session using the ElevenLabs SDK.

    Uses CommitStrategy.MANUAL so we can explicitly commit on PTT release.

    Usage::

        session = RealtimeSTTSession()
        await session.connect()
        await session.send_audio(pcm_base64_chunk)
        async for event in session.iter_events():
            ...
        await session.commit()  # force commit on PTT release
        await session.close()
    """

    def __init__(self, *, language: str = "en", on_commit: Any = None, auto_commit: bool = False) -> None:
        self._language = language
        self._auto_commit = auto_commit
        self._connection: Any = None
        self._queue: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()
        self._closed = False
        self._last_partial_text = ""
        self._audio_chunk_count = 0
        self._on_commit = on_commit  # optional callback(text) on committed transcript

    async def connect(self) -> None:
        """Open the realtime STT connection via the ElevenLabs SDK."""
        from elevenlabs import AudioFormat, CommitStrategy, ElevenLabs, RealtimeAudioOptions, RealtimeEvents

        if not settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")

        client = ElevenLabs(api_key=settings.elevenlabs_api_key)

        strategy = CommitStrategy.VAD if self._auto_commit else CommitStrategy.MANUAL
        logger.info("STT connecting via ElevenLabs SDK (%s commit, PCM 16kHz)", strategy)
        self._connection = await client.speech_to_text.realtime.connect(
            RealtimeAudioOptions(
                model_id="scribe_v2_realtime",
                language_code=self._language,
                audio_format=AudioFormat.PCM_16000,
                sample_rate=16000,
                commit_strategy=strategy,
            )
        )

        # Register event handlers
        def on_partial(data: Any) -> None:
            text = data.get("text", "") if isinstance(data, dict) else getattr(data, "text", "")
            if text:
                self._last_partial_text = text
                logger.info("STT partial: %s", text)
                self._queue.put_nowait(TranscriptEvent(text=text, is_final=False))

        def on_committed(data: Any) -> None:
            text = (
                data.get("text", "") if isinstance(data, dict) else getattr(data, "text", "")
            ) or self._last_partial_text
            if text:
                logger.info("STT committed: %s", text)
                self._queue.put_nowait(TranscriptEvent(text=text, is_final=True))
                if self._on_commit:
                    self._on_commit(text)
            self._last_partial_text = ""

        def on_error(error: Any) -> None:
            logger.error("STT error: %s", error)

        def on_close() -> None:
            logger.info("STT connection closed")
            self._queue.put_nowait(None)

        self._connection.on(RealtimeEvents.PARTIAL_TRANSCRIPT, on_partial)
        self._connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT, on_committed)
        self._connection.on(RealtimeEvents.ERROR, on_error)
        self._connection.on(RealtimeEvents.CLOSE, on_close)

        logger.info("STT connected, listening for transcripts")

    async def send_audio(self, pcm_base64: str) -> None:
        """Send a base64-encoded PCM 16kHz audio chunk."""
        if self._connection is None or self._closed:
            return
        try:
            await self._connection.send({"audio_base_64": pcm_base64, "sample_rate": 16000})
            self._audio_chunk_count += 1
            if self._audio_chunk_count % 50 == 1:
                logger.info("STT send_audio chunk #%d", self._audio_chunk_count)
        except Exception:
            logger.exception("Failed to send audio chunk to STT")

    async def commit(self) -> None:
        """Force-commit the current audio segment (call on PTT release)."""
        if self._connection is None or self._closed:
            return
        try:
            logger.info("STT committing (PTT release)")
            await self._connection.commit()
        except Exception:
            logger.exception("Failed to commit STT")

    @property
    def last_partial_text(self) -> str:
        """The most recent partial transcript text (not yet committed)."""
        return self._last_partial_text

    async def iter_events(self):
        """Async generator yielding TranscriptEvent objects."""
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event

    async def close(self) -> None:
        """Close the STT session and clean up."""
        self._closed = True
        if self._connection:
            try:
                await self._connection.close()
            except Exception:
                pass
            self._connection = None
