"""Speech-to-text: batch (Mistral Voxtral) and realtime (ElevenLabs Scribe v2)."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websockets
from mistralai import Mistral
from mistralai.models import File

from ensemble.config import settings

logger = logging.getLogger(__name__)

STT_MODEL = "voxtral-mini-transcribe-realtime-2602"
STT_BATCH_MODEL = "mistral-stt-latest"


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
# Realtime STT via ElevenLabs Scribe v2 WebSocket
# ---------------------------------------------------------------------------

SCRIBE_WS_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"


@dataclass
class TranscriptEvent:
    """A transcript event from the realtime STT session."""

    text: str
    is_final: bool


class RealtimeSTTSession:
    """Manages a WebSocket connection to ElevenLabs Scribe v2 realtime STT.

    Usage::

        session = RealtimeSTTSession()
        await session.connect()
        # feed audio from mic
        await session.send_audio(pcm_base64_chunk)
        # consume transcript events
        async for event in session.iter_events():
            ...
        await session.close()
    """

    def __init__(
        self,
        *,
        language: str = "en",
        vad_silence_threshold_secs: float = 1.0,
    ) -> None:
        self._language = language
        self._vad_silence_threshold = vad_silence_threshold_secs
        self._ws: Any = None
        self._queue: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()
        self._recv_task: asyncio.Task | None = None
        self._closed = False

    async def connect(self) -> None:
        """Open the WebSocket connection and start receiving."""
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")

        params = (
            f"?model_id=scribe_v2"
            f"&language_code={self._language}"
            f"&sample_rate=16000"
            f"&encoding=pcm_s16le"
        )
        headers = {"xi-api-key": settings.elevenlabs_api_key}

        self._ws = await websockets.connect(
            SCRIBE_WS_URL + params,
            additional_headers=headers,
            ping_interval=20,
        )
        self._recv_task = asyncio.create_task(self._receive_loop())

    async def send_audio(self, pcm_base64: str) -> None:
        """Send a base64-encoded PCM 16kHz audio chunk to ElevenLabs."""
        if self._ws is None or self._closed:
            return
        try:
            await self._ws.send(json.dumps({
                "audio": pcm_base64,
            }))
        except Exception:
            logger.debug("Failed to send audio chunk to STT WS")

    async def _receive_loop(self) -> None:
        """Background task reading transcript events from ElevenLabs."""
        try:
            async for raw in self._ws:
                if self._closed:
                    break
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "transcript":
                    # Partial (interim) transcript
                    text = msg.get("channel", {}).get("alternatives", [{}])[0].get(
                        "transcript", ""
                    )
                    if text:
                        await self._queue.put(TranscriptEvent(text=text, is_final=False))

                elif msg_type == "speech_final":
                    # VAD detected end of utterance — committed transcript
                    text = msg.get("channel", {}).get("alternatives", [{}])[0].get(
                        "transcript", ""
                    )
                    if text:
                        await self._queue.put(TranscriptEvent(text=text, is_final=True))

        except websockets.ConnectionClosed:
            logger.debug("STT WebSocket connection closed")
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("STT receive loop error")
        finally:
            await self._queue.put(None)  # sentinel

    async def iter_events(self):
        """Async generator yielding TranscriptEvent objects.

        Yields events until the session is closed (sentinel ``None``).
        """
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event

    async def close(self) -> None:
        """Close the STT session and clean up."""
        self._closed = True
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
