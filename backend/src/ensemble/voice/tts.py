"""Text-to-speech using ElevenLabs (Mistral has no TTS)."""

from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

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


async def synthesize_stream(
    text: str,
    voice_id: str = "",
    model_id: str = "eleven_turbo_v2_5",
) -> AsyncIterator[bytes]:
    """Stream synthesized audio chunks."""
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    vid = voice_id or DEFAULT_VOICE_ID
    url = f"{ELEVENLABS_API}/text-to-speech/{vid}/stream"

    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream(
            "POST",
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
        ) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(1024):
                yield chunk
