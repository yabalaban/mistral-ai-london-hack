"""Speech-to-text using Mistral Voxtral."""

from __future__ import annotations

import logging
from pathlib import Path

from mistralai import Mistral
from mistralai.models import File

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
