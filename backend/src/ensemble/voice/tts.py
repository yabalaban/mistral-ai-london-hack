"""Text-to-speech using ElevenLabs — batch HTTP and realtime WebSocket streaming."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, AsyncIterator

import httpx
import websockets

from ensemble.config import settings

logger = logging.getLogger(__name__)

ELEVENLABS_API = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel — fallback


async def synthesize(
    text: str,
    voice_id: str = "",
    model_id: str = "eleven_turbo_v2_5",
) -> bytes:
    """Synthesize text to audio bytes (mp3)."""
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    vid = voice_id or DEFAULT_VOICE_ID
    url = f"{ELEVENLABS_API}/text-to-speech/{vid}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": model_id,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
        )
        resp.raise_for_status()
        return resp.content


# ---------------------------------------------------------------------------
# WebSocket-based streaming TTS (text chunks in -> audio chunks out)
# ---------------------------------------------------------------------------

TTS_WS_URL = "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"


class TTSWebSocket:
    """Manages a WebSocket connection to ElevenLabs streaming TTS.

    Sends text chunks incrementally, receives audio bytes as they are synthesized.
    """

    def __init__(
        self,
        voice_id: str = "",
        model_id: str = "eleven_turbo_v2_5",
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
        params = f"?model_id={self._model_id}"

        self._ws = await websockets.connect(
            url + params,
            ping_interval=20,
        )

        # Send initialization message
        init_msg = {
            "text": " ",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            "xi_api_key": settings.elevenlabs_api_key,
            "chunk_length_schedule": [50, 120, 200, 260],
        }
        await self._ws.send(json.dumps(init_msg))
        self._recv_task = asyncio.create_task(self._receive_loop())

    async def send_text(self, text: str) -> None:
        """Send a text chunk for synthesis."""
        if self._ws is None or self._closed:
            return
        try:
            await self._ws.send(json.dumps({
                "text": text,
                "try_trigger_generation": True,
            }))
        except Exception:
            logger.debug("Failed to send text chunk to TTS WS")

    async def finish(self) -> None:
        """Signal end of text input (flush remaining audio)."""
        if self._ws is None or self._closed:
            return
        try:
            await self._ws.send(json.dumps({"text": ""}))
        except Exception:
            logger.debug("Failed to send TTS finish signal")

    async def _receive_loop(self) -> None:
        """Background task reading audio chunks from ElevenLabs."""
        try:
            async for raw in self._ws:
                if self._closed:
                    break
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                # ElevenLabs sends {"audio": "<base64>", "isFinal": bool, ...}
                audio_b64 = msg.get("audio")
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    if audio_bytes:
                        await self._audio_queue.put(audio_bytes)

                if msg.get("isFinal"):
                    break

        except websockets.ConnectionClosed:
            logger.debug("TTS WebSocket connection closed")
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
        # Drain the queue so any waiters unblock
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break


