"""Text-to-speech using ElevenLabs — SDK for batch, WebSocket for streaming."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, AsyncIterator

import websockets

from ensemble.config import settings

logger = logging.getLogger(__name__)

DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel — fallback
DEFAULT_MODEL = "eleven_flash_v2_5"  # lowest latency model


async def synthesize(
    text: str,
    voice_id: str = "",
    model_id: str = DEFAULT_MODEL,
) -> bytes:
    """Synthesize text to audio bytes using the ElevenLabs SDK."""
    from elevenlabs.client import AsyncElevenLabs

    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
    vid = voice_id or DEFAULT_VOICE_ID

    logger.info("TTS synthesize: voice_id=%s, text=%d chars, model=%s", vid, len(text), model_id)
    audio_data = b""
    audio_stream = client.text_to_speech.stream(
        text=text,
        voice_id=vid,
        model_id=model_id,
    )
    async for chunk in audio_stream:
        if isinstance(chunk, bytes):
            audio_data += chunk
    logger.info("TTS synthesize complete: %d bytes", len(audio_data))
    return audio_data


# ---------------------------------------------------------------------------
# WebSocket-based streaming TTS (text chunks in -> audio chunks out)
# ---------------------------------------------------------------------------

TTS_WS_URL = "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"


class TTSWebSocket:
    """Manages a WebSocket connection to ElevenLabs streaming TTS.

    Sends text chunks incrementally (from LLM streaming), receives audio
    bytes as they are synthesized. Uses Flash v2.5 for lowest latency and
    aggressive chunk scheduling for fast first-byte.
    """

    def __init__(
        self,
        voice_id: str = "",
        model_id: str = DEFAULT_MODEL,
    ) -> None:
        self._voice_id = voice_id or DEFAULT_VOICE_ID
        self._model_id = model_id
        self._ws: Any = None
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._recv_task: asyncio.Task | None = None
        self._closed = False

    async def connect(self) -> None:
        """Open the WebSocket connection and send the init message."""
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")

        url = TTS_WS_URL.format(voice_id=self._voice_id)
        params = (
            f"?model_id={self._model_id}"
            f"&output_format=mp3_22050_32"
            f"&optimize_streaming_latency=4"
        )

        logger.info("TTS connecting: voice=%s model=%s", self._voice_id, self._model_id)
        self._ws = await websockets.connect(
            url + params,
            ping_interval=20,
        )

        # Init message — aggressive chunk schedule + faster speech
        init_msg = {
            "text": " ",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "speed": 1.15,
            },
            "xi_api_key": settings.elevenlabs_api_key,
            "chunk_length_schedule": [20, 50, 80, 120],
        }
        await self._ws.send(json.dumps(init_msg))
        self._recv_task = asyncio.create_task(self._receive_loop())
        logger.info("TTS connected")

    async def send_text(self, text: str) -> None:
        """Send a text chunk for synthesis. Let ElevenLabs handle buffering."""
        if self._ws is None or self._closed:
            return
        try:
            await self._ws.send(json.dumps({
                "text": text,
                "try_trigger_generation": True,
            }))
        except Exception:
            logger.debug("Failed to send text chunk to TTS WS")

    async def flush(self) -> None:
        """Force-generate any buffered text without closing the stream."""
        if self._ws is None or self._closed:
            return
        try:
            await self._ws.send(json.dumps({"text": " ", "flush": True}))
        except Exception:
            logger.debug("Failed to flush TTS")

    async def finish(self) -> None:
        """Signal end of text input (flush remaining audio and close)."""
        if self._ws is None or self._closed:
            return
        try:
            await self._ws.send(json.dumps({"text": ""}))
        except Exception:
            logger.debug("Failed to send TTS finish signal")

    async def _receive_loop(self) -> None:
        """Background task reading audio chunks from ElevenLabs."""
        chunk_count = 0
        total_bytes = 0
        try:
            async for raw in self._ws:
                if self._closed:
                    break
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                audio_b64 = msg.get("audio")
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    if audio_bytes:
                        chunk_count += 1
                        total_bytes += len(audio_bytes)
                        if chunk_count <= 3 or chunk_count % 10 == 0:
                            logger.info(
                                "TTS audio chunk #%d: %d bytes (total: %d)",
                                chunk_count, len(audio_bytes), total_bytes,
                            )
                        await self._audio_queue.put(audio_bytes)

                if msg.get("isFinal"):
                    logger.info("TTS complete: %d chunks, %d bytes", chunk_count, total_bytes)
                    break

        except websockets.ConnectionClosed as e:
            logger.warning("TTS WebSocket closed: code=%s reason=%s", e.code, e.reason)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("TTS receive loop error")
        finally:
            await self._audio_queue.put(None)  # sentinel

    async def iter_audio(self) -> AsyncIterator[bytes]:
        """Async generator yielding audio bytes as they arrive."""
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                break
            yield chunk

    async def close(self) -> None:
        """Close the TTS WebSocket and clean up."""
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
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
