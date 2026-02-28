"""WebSocket handler for real-time conversations and voice streaming.

Protocol:
  Client → Server (JSON):
    {"type": "message", "content": "text", "attachments": [{"type":"image","url":"data:..."}]}
    {"type": "audio", "data": "<base64 wav audio>"}
    {"type": "start_call", "mode": "text|voice"}
    {"type": "end_call"}

  Server → Client (JSON):
    {"type": "agent_message", "agent_id": "emma", "content": "text", "done": false}
    {"type": "agent_message", "agent_id": "emma", "content": "full text", "done": true}
    {"type": "turn_change", "agent_id": "dan", "hint": "optional"}
    {"type": "audio", "agent_id": "emma", "data": "<base64 mp3 audio>"}
    {"type": "transcription", "text": "what the user said"}
    {"type": "error", "detail": "what went wrong"}
    {"type": "call_started", "mode": "text|voice"}
    {"type": "call_ended"}
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ensemble.agents.registry import AgentRegistry
from ensemble.conversations.models import (
    Attachment,
    Conversation,
    ConversationType,
    Message,
    MessageRole,
)
from ensemble.oracle.engine import OracleEngine

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections per conversation."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, conversation_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(conversation_id, []).append(ws)

    def disconnect(self, conversation_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(conversation_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, conversation_id: str, data: dict[str, Any]) -> None:
        for ws in self._connections.get(conversation_id, []):
            if ws.client_state == WebSocketState.CONNECTED:
                try:
                    await ws.send_json(data)
                except Exception:
                    logger.exception("Failed to send to WebSocket")


manager = ConnectionManager()


async def handle_conversation_ws(
    ws: WebSocket,
    conversation_id: str,
    conversations: dict[str, Conversation],
    registry: AgentRegistry,
    oracle: OracleEngine,
    mistral_client: Any,
) -> None:
    """Main WebSocket handler for a conversation."""
    conv = conversations.get(conversation_id)
    if not conv:
        await ws.close(code=4004, reason="Conversation not found")
        return

    await manager.connect(conversation_id, ws)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, {"type": "error", "detail": "Invalid JSON"})
                continue

            msg_type = msg.get("type")

            if msg_type == "message":
                await _handle_message(ws, conv, msg, registry, oracle, mistral_client)
            elif msg_type == "audio":
                await _handle_audio(ws, conv, msg, registry, oracle, mistral_client)
            elif msg_type == "start_call":
                mode = msg.get("mode", "text")
                await _send(ws, {"type": "call_started", "mode": mode})
            elif msg_type == "end_call":
                await _send(ws, {"type": "call_ended"})
            else:
                await _send(ws, {"type": "error", "detail": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for conversation %s", conversation_id)
    finally:
        manager.disconnect(conversation_id, ws)


async def _handle_message(
    ws: WebSocket,
    conv: Conversation,
    msg: dict,
    registry: AgentRegistry,
    oracle: OracleEngine,
    mistral_client: Any,
) -> None:
    """Handle a text message — route to agent(s) with streaming."""
    content = msg.get("content", "")
    raw_attachments = msg.get("attachments", [])
    attachments = [Attachment(**a) for a in raw_attachments] if raw_attachments else []

    if not content and not attachments:
        await _send(ws, {"type": "error", "detail": "Empty message"})
        return

    # Record user message
    user_msg = Message(
        role=MessageRole.USER,
        content=content,
        attachments=attachments,
    )
    conv.messages.append(user_msg)

    if conv.type == ConversationType.DIRECT:
        await _handle_direct_streaming(ws, conv, content, attachments, registry, mistral_client)
    else:
        await _handle_group_streaming(ws, conv, content, attachments, registry, oracle, mistral_client)


async def _handle_direct_streaming(
    ws: WebSocket,
    conv: Conversation,
    content: str,
    attachments: list[Attachment],
    registry: AgentRegistry,
    mistral_client: Any,
) -> None:
    """Stream a direct conversation response."""
    agent_id = conv.participant_agent_ids[0]
    agent = registry.get(agent_id)
    if not agent or not agent.mistral_agent_id:
        await _send(ws, {"type": "error", "detail": f"Agent {agent_id} not ready"})
        return

    inputs = _build_inputs(content, attachments)
    mistral_conv_id = conv.mistral_conversation_ids.get(agent_id)

    try:
        full_text = await _stream_agent_response(
            ws, conv, agent_id, agent.mistral_agent_id, inputs, mistral_conv_id, mistral_client
        )

        # Record in conversation
        agent_msg = Message(role=MessageRole.AGENT, agent_id=agent_id, content=full_text)
        conv.messages.append(agent_msg)

    except Exception:
        logger.exception("Streaming failed for agent %s", agent_id)
        await _send(ws, {"type": "error", "detail": "Agent response failed"})


async def _handle_group_streaming(
    ws: WebSocket,
    conv: Conversation,
    content: str,
    attachments: list[Attachment],
    registry: AgentRegistry,
    oracle: OracleEngine,
    mistral_client: Any,
) -> None:
    """Handle group conversation with oracle-driven turns and streaming."""
    last_speaker: str | None = None

    for _ in range(len(conv.participant_agent_ids)):
        # Oracle decides next speaker
        next_id, hint = await oracle.decide_next_speaker(conv, last_speaker)
        agent = registry.get(next_id)
        if not agent or not agent.mistral_agent_id:
            continue

        # Notify turn change
        await _send(ws, {"type": "turn_change", "agent_id": next_id, "hint": hint})

        # Build agent prompt with group context
        agent_prompt = oracle._build_agent_prompt(conv, next_id, hint)
        mistral_conv_id = conv.mistral_conversation_ids.get(next_id)

        try:
            full_text = await _stream_agent_response(
                ws, conv, next_id, agent.mistral_agent_id, agent_prompt, mistral_conv_id, mistral_client
            )
            agent_msg = Message(role=MessageRole.AGENT, agent_id=next_id, content=full_text)
            conv.messages.append(agent_msg)
            last_speaker = next_id
        except Exception:
            logger.exception("Streaming failed for agent %s in group", next_id)
            await _send(ws, {"type": "error", "detail": f"Agent {next_id} response failed"})


async def _handle_audio(
    ws: WebSocket,
    conv: Conversation,
    msg: dict,
    registry: AgentRegistry,
    oracle: OracleEngine,
    mistral_client: Any,
) -> None:
    """Handle audio input: transcribe → agent → TTS → audio out."""
    from ensemble.voice.stt import transcribe_audio
    from ensemble.voice.tts import synthesize

    audio_b64 = msg.get("data", "")
    if not audio_b64:
        await _send(ws, {"type": "error", "detail": "No audio data"})
        return

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        await _send(ws, {"type": "error", "detail": "Invalid base64 audio"})
        return

    # 1. Transcribe
    text = await transcribe_audio(mistral_client, audio_bytes)
    if not text:
        await _send(ws, {"type": "error", "detail": "Could not transcribe audio"})
        return

    await _send(ws, {"type": "transcription", "text": text})

    # 2. Get agent response (reuse message handler logic)
    await _handle_message(ws, conv, {"content": text, "attachments": []}, registry, oracle, mistral_client)

    # 3. TTS for the last agent message
    last_agent_msg = None
    for m in reversed(conv.messages):
        if m.role == MessageRole.AGENT:
            last_agent_msg = m
            break

    if last_agent_msg and last_agent_msg.content:
        agent = registry.get(last_agent_msg.agent_id or "")
        voice_id = agent.voice_id if agent else ""
        try:
            audio_out = await synthesize(last_agent_msg.content, voice_id=voice_id)
            audio_out_b64 = base64.b64encode(audio_out).decode()
            await _send(ws, {
                "type": "audio",
                "agent_id": last_agent_msg.agent_id,
                "data": audio_out_b64,
            })
        except Exception:
            logger.exception("TTS failed for agent %s", last_agent_msg.agent_id)


async def _stream_agent_response(
    ws: WebSocket,
    conv: Conversation,
    agent_id: str,
    mistral_agent_id: str,
    inputs: str | list[dict],
    mistral_conv_id: str | None,
    mistral_client: Any,
) -> str:
    """Stream an agent response via Mistral Conversations API.

    Sends incremental chunks to the WebSocket and returns the full text.
    Uses start_stream_async / append_stream_async for real-time streaming.

    Event types from Mistral:
      - ResponseStartedEvent: contains conversation_id
      - MessageOutputEvent: contains content (text chunk), agent_id, role
      - ResponseDoneEvent: contains usage stats
    """
    full_text = ""

    if mistral_conv_id:
        stream = await mistral_client.beta.conversations.append_stream_async(
            conversation_id=mistral_conv_id,
            inputs=inputs,
        )
    else:
        stream = await mistral_client.beta.conversations.start_stream_async(
            agent_id=mistral_agent_id,
            inputs=inputs,
        )

    async for event in stream:
        data = event.data

        # ResponseStartedEvent — capture conversation_id
        if hasattr(data, "conversation_id") and data.conversation_id:
            conv.mistral_conversation_ids[agent_id] = data.conversation_id

        # MessageOutputEvent — stream text chunks
        if hasattr(data, "content"):
            text = _extract_chunk_text(data)
            if text:
                full_text += text
                await _send(ws, {
                    "type": "agent_message",
                    "agent_id": agent_id,
                    "content": text,
                    "done": False,
                })

    # Send done signal with full accumulated text
    await _send(ws, {
        "type": "agent_message",
        "agent_id": agent_id,
        "content": full_text,
        "done": True,
    })

    return full_text


def _build_inputs(content: str, attachments: list[Attachment]) -> str | list[dict]:
    if not attachments:
        return content
    parts: list[dict] = [{"type": "text", "text": content}]
    for att in attachments:
        if att.type == "image":
            parts.append({"type": "image_url", "image_url": {"url": att.url}})
    return [{"role": "user", "content": parts}]


def _extract_chunk_text(output) -> str:
    """Extract text from a streaming output chunk."""
    if hasattr(output, "content"):
        content = output.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for c in content:
                if isinstance(c, dict):
                    texts.append(c.get("text", ""))
                elif hasattr(c, "text"):
                    texts.append(getattr(c, "text", "") or "")
            return "".join(texts)
        if hasattr(content, "text"):
            return content.text or ""
    return ""


async def _send(ws: WebSocket, data: dict) -> None:
    """Send JSON to WebSocket, ignoring errors on closed connections."""
    if ws.client_state == WebSocketState.CONNECTED:
        try:
            await ws.send_json(data)
        except Exception:
            pass
