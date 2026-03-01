"""End-to-end voice test — no Discord needed.

Simulates: User speech (TTS) → STT → Oracle → Agent response → TTS output

Usage:
    cd backend && PYTHONPATH=src uv run python test_voice_e2e.py "Hey everyone, what should we build for the hackathon?"
"""

from __future__ import annotations

import asyncio
import base64
import logging
import struct
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("e2e_test")

from mistralai import Mistral

from ensemble.agents.registry import AgentRegistry
from ensemble.config import settings
from ensemble.conversations.models import (
    Conversation,
    ConversationType,
    Message,
    MessageRole,
)
from ensemble.oracle.engine import OracleEngine
from ensemble.voice.stt import RealtimeSTTSession
from ensemble.voice.tts import synthesize


async def generate_user_audio(text: str) -> bytes:
    """Generate fake 'user speech' audio via TTS."""
    logger.info("=== STEP 1: Generating user audio via TTS ===")
    logger.info("User says: %r", text)
    audio = await synthesize(text, voice_id="onwK4e9ZLuTAKqWW03F9")  # Daniel voice
    logger.info("Generated %d bytes of audio", len(audio))

    # Save for debugging
    path = Path("/tmp/test_user_speech.mp3")
    path.write_bytes(audio)
    logger.info("Saved to %s", path)
    return audio


async def test_stt(audio_bytes: bytes) -> str:
    """Test ElevenLabs realtime STT with audio."""
    logger.info("=== STEP 2: Testing ElevenLabs STT ===")

    # For STT we need PCM 16kHz. Let's use the batch Mistral STT instead
    # since ElevenLabs realtime needs streaming PCM which is hard to
    # generate from MP3 without ffmpeg piping.
    # Actually let's use ffmpeg to convert MP3 → PCM 16kHz mono
    import subprocess

    tmp_pcm = tempfile.NamedTemporaryFile(suffix=".pcm", delete=False)
    tmp_pcm.close()

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", "/tmp/test_user_speech.mp3",
            "-f", "s16le", "-ar", "16000", "-ac", "1",
            tmp_pcm.name,
        ],
        capture_output=True,
    )

    pcm_data = Path(tmp_pcm.name).read_bytes()
    logger.info("Converted to PCM: %d bytes", len(pcm_data))

    # Stream into ElevenLabs realtime STT
    session = RealtimeSTTSession(auto_commit=True)
    await session.connect()

    # Send in chunks (simulating real-time streaming)
    chunk_size = 3200  # 100ms at 16kHz mono 16-bit
    for i in range(0, len(pcm_data), chunk_size):
        chunk = pcm_data[i : i + chunk_size]
        b64 = base64.b64encode(chunk).decode()
        await session.send_audio(b64)
        await asyncio.sleep(0.05)  # ~50ms between chunks

    logger.info("All audio sent, waiting for transcript...")

    # Wait for committed transcript
    final_text = ""
    try:
        async for event in session.iter_events():
            if event.is_final:
                final_text = event.text
                logger.info("STT FINAL: %s", final_text)
                break
            else:
                logger.info("STT partial: %s", event.text)
    except asyncio.TimeoutError:
        logger.warning("STT timeout — using last partial")
        final_text = session.last_partial_text

    await session.close()
    Path(tmp_pcm.name).unlink(missing_ok=True)

    if not final_text:
        logger.error("No transcript received!")
        return ""

    return final_text


async def test_oracle(text: str, registry: AgentRegistry, oracle: OracleEngine) -> list[tuple[str, str]]:
    """Test oracle round — returns list of (agent_name, response_text)."""
    logger.info("=== STEP 3: Testing Oracle ===")
    logger.info("User message: %r", text)

    conv = Conversation(
        type=ConversationType.GROUP,
        participant_agent_ids=list(registry.agents.keys()),
    )
    user_msg = Message(role=MessageRole.USER, content=text)
    conv.messages.append(user_msg)

    responses = []
    async for event_type, data in oracle.run_group_turn_streaming(
        conv, text, None, voice_mode=True
    ):
        if event_type == "oracle":
            logger.info(
                "Oracle: round=%s mode=%s speakers=%s",
                data.get("round"), data.get("mode"), data.get("speakers"),
            )
        elif event_type == "message":
            msg = data
            agent = registry.get(msg.agent_id)
            name = agent.name if agent else msg.agent_id
            logger.info("Agent %s: %s", name, msg.content[:100])
            responses.append((msg.agent_id, msg.content))
        elif event_type == "summary":
            logger.info("Summary: %s", data.get("content", "")[:100])

    logger.info("Got %d agent responses", len(responses))
    return responses


async def test_tts(responses: list[tuple[str, str]], registry: AgentRegistry) -> None:
    """Test TTS for each agent response."""
    logger.info("=== STEP 4: Testing TTS ===")

    for agent_id, text in responses:
        agent = registry.get(agent_id)
        voice_id = agent.voice_id if agent else ""
        name = agent.name if agent else agent_id

        logger.info("Synthesizing %s (voice=%s): %s", name, voice_id[:10], text[:60])
        try:
            audio = await synthesize(text, voice_id=voice_id)
            path = Path(f"/tmp/test_tts_{agent_id}.mp3")
            path.write_bytes(audio)
            logger.info("  ✅ %s: %d bytes → %s", name, len(audio), path)
        except Exception as e:
            logger.error("  ❌ %s TTS failed: %s", name, e)


async def main():
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Hey everyone, what should we build for the hackathon?"

    # Init backend
    client = Mistral(api_key=settings.mistral_api_key)
    registry = AgentRegistry(client)
    oracle = OracleEngine(client, registry)

    profiles_dir = Path(__file__).parent / "agents"
    registry.load_profiles(profiles_dir)
    await registry.sync_to_mistral()
    logger.info("Agents synced: %s", list(registry.agents.keys()))

    try:
        # Step 1: Generate user audio
        audio = await generate_user_audio(text)

        # Step 2: STT
        transcript = await test_stt(audio)
        if not transcript:
            logger.error("STT failed — testing oracle with original text instead")
            transcript = text

        # Step 3: Oracle
        responses = await test_oracle(transcript, registry, oracle)

        # Step 4: TTS
        if responses:
            await test_tts(responses, registry)

        logger.info("=== E2E TEST COMPLETE ===")
        logger.info("User said: %r", text)
        logger.info("STT heard: %r", transcript)
        logger.info("Agents responded: %d", len(responses))
        for agent_id, resp in responses:
            agent = registry.get(agent_id)
            logger.info("  %s: %s", agent.name if agent else agent_id, resp[:80])

    finally:
        await registry.cleanup_mistral()


if __name__ == "__main__":
    asyncio.run(main())
