"""WebSocket handler for real-time conversations and voice streaming.

Protocol:
  Client → Server (JSON):
    {"type": "message", "content": "text", "attachments": [{"type":"image","url":"data:..."}]}
    {"type": "audio", "data": "<base64 wav audio>"}
    {"type": "start_call", "mode": "text|voice"}
    {"type": "end_call"}
    {"type": "voice_state", "active": true/false}
    {"type": "audio_stream", "data": "<base64 PCM 16kHz>"}

  Server → Client (JSON):
    {"type": "message_chunk", "agent_id": "emma", "content": "text", "message_id": "..."}
    {"type": "message_complete", "message": {id, role, agent_id, content, timestamp}}
    {"type": "turn_change", "agent_id": "dan"}
    {"type": "audio_chunk", "agent_id": "emma", "data": "<base64 mp3 audio>"}
    {"type": "transcription", "text": "what the user said", "final": true}
    {"type": "partial_transcript", "text": "real-time words"}
    {"type": "agent_speaking", "agent_id": "emma"}
    {"type": "agent_done", "agent_id": "emma"}
    {"type": "interrupt"}
    {"type": "agent_interrupted", "agent_id": "emma", "by": "sofia"}
    {"type": "error", "message": "what went wrong"}
    {"type": "call_started", "call": {...}}
    {"type": "call_ended", "call_id": "..."}
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ensemble.agents.registry import AgentRegistry
from ensemble.conversations.manager import _handle_function_calls
from ensemble.conversations.models import (
    Attachment,
    Conversation,
    ConversationType,
    Message,
    MessageRole,
)
from ensemble.oracle.engine import OracleEngine
from ensemble.utils import build_inputs, extract_reply, extract_text_from_content

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manages active WebSocket connections per conversation."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, conversation_id: str, ws: WebSocket) -> None:
        """Accept a WebSocket connection and register it for the conversation."""
        await ws.accept()
        self._connections.setdefault(conversation_id, []).append(ws)

    def disconnect(self, conversation_id: str, ws: WebSocket) -> None:
        """Remove a WebSocket connection from the conversation's connection list."""
        conns = self._connections.get(conversation_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, conversation_id: str, data: dict[str, Any]) -> None:
        """Send a JSON message to all connected WebSockets for a conversation."""
        for ws in self._connections.get(conversation_id, []):
            if ws.client_state == WebSocketState.CONNECTED:
                try:
                    await ws.send_json(data)
                except Exception:
                    logger.exception("Failed to send to WebSocket")


manager = ConnectionManager()


class VoiceSession:
    """Manages the real-time voice pipeline for a single WebSocket connection.

    Lifecycle:
      1. start() — opens an STT session, begins listening for transcripts
      2. feed_audio(pcm_b64) — forwards PCM chunks to STT
      3. Background task listens for STT events → triggers agent responses
      4. stop() — closes STT, cancels tasks
    """

    def __init__(
        self,
        ws: WebSocket,
        conv: Conversation,
        registry: AgentRegistry,
        oracle: OracleEngine,
        mistral_client: Any,
    ) -> None:
        self._ws = ws
        self._conv = conv
        self._registry = registry
        self._oracle = oracle
        self._mistral = mistral_client
        self._stt_session = None
        self._listen_task: asyncio.Task | None = None
        self._response_task: asyncio.Task | None = None
        self._active_tts = None  # TTSWebSocket for cancellation
        self._active = False

    async def start(self) -> None:
        """Start the realtime STT session and begin listening."""
        from ensemble.voice.stt import RealtimeSTTSession

        logger.info("VoiceSession starting — opening STT connection")
        self._stt_session = RealtimeSTTSession()
        await self._stt_session.connect()
        self._active = True
        self._listen_task = asyncio.create_task(self._listen_for_transcripts())
        logger.info("VoiceSession started — STT connected, listening for transcripts")

    async def feed_audio(self, pcm_b64: str) -> None:
        """Forward a PCM audio chunk to the STT session."""
        if self._stt_session and self._active:
            await self._stt_session.send_audio(pcm_b64)
        else:
            logger.debug("feed_audio called but STT session not active")

    async def _listen_for_transcripts(self) -> None:
        """Background task consuming STT events and triggering responses."""
        if not self._stt_session:
            return
        try:
            async for event in self._stt_session.iter_events():
                if not self._active:
                    break

                if not event.is_final:
                    # Partial transcript — show user their words in real-time
                    await _send(self._ws, {
                        "type": "partial_transcript",
                        "text": event.text,
                    })
                else:
                    # Committed transcript (VAD detected silence)
                    if not event.text.strip():
                        continue

                    # If an agent is currently responding, interrupt it
                    if self._response_task and not self._response_task.done():
                        self._response_task.cancel()
                        try:
                            await self._response_task
                        except asyncio.CancelledError:
                            pass
                        if self._active_tts:
                            await self._active_tts.close()
                            self._active_tts = None
                        await _send(self._ws, {"type": "interrupt"})

                    await _send(self._ws, {
                        "type": "transcription",
                        "text": event.text,
                        "final": True,
                    })

                    # Start new response
                    self._response_task = asyncio.create_task(
                        self._trigger_response(event.text)
                    )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Voice transcript listener error")

    async def _trigger_response(self, text: str) -> None:
        """Handle a committed transcript by routing to agent(s) with TTS."""
        try:
            if self._conv.type == ConversationType.DIRECT:
                await self._direct_voice_response(text)
            else:
                await self._group_voice_response(text)
        except asyncio.CancelledError:
            logger.debug("Voice response cancelled (interrupted)")
        except Exception:
            logger.exception("Voice response failed")
            await _send(self._ws, {"type": "error", "message": "Voice response failed"})

    async def _direct_voice_response(self, text: str) -> None:
        """Stream a direct agent response with TTS."""
        from ensemble.voice.tts import TTSWebSocket

        # Record user message
        user_msg = Message(role=MessageRole.USER, content=text)
        self._conv.messages.append(user_msg)

        agent_id = self._conv.participant_agent_ids[0]
        agent = self._registry.get(agent_id)
        if not agent or not agent.mistral_agent_id:
            await _send(self._ws, {"type": "error", "message": f"Agent {agent_id} not ready"})
            return

        await _send(self._ws, {"type": "agent_speaking", "agent_id": agent_id})

        # Create an async generator from Mistral streaming
        text_queue: asyncio.Queue[str | None] = asyncio.Queue()
        full_text = ""
        msg_id = _uuid.uuid4().hex[:12]

        async def _stream_agent_text() -> None:
            nonlocal full_text
            inputs = build_inputs(text, None)
            mistral_conv_id = self._conv.mistral_conversation_ids.get(agent_id)

            if mistral_conv_id:
                stream = await self._mistral.beta.conversations.append_stream_async(
                    conversation_id=mistral_conv_id,
                    inputs=inputs,
                    handoff_execution="client",
                )
            else:
                stream = await self._mistral.beta.conversations.start_stream_async(
                    agent_id=agent.mistral_agent_id,
                    inputs=inputs,
                    handoff_execution="client",
                )

            async for event in stream:
                data = event.data
                if hasattr(data, "conversation_id") and data.conversation_id:
                    self._conv.mistral_conversation_ids[agent_id] = data.conversation_id
                if hasattr(data, "content"):
                    chunk_text = _extract_chunk_text(data)
                    if chunk_text:
                        full_text += chunk_text
                        await text_queue.put(chunk_text)
                        # Also send text chunk for the chat UI
                        await _send(self._ws, {
                            "type": "message_chunk",
                            "agent_id": agent_id,
                            "content": chunk_text,
                            "message_id": msg_id,
                        })
            await text_queue.put(None)  # signal done

        # Start text streaming task
        text_task = asyncio.create_task(_stream_agent_text())

        # Create text chunk async iterator
        async def _text_iter() -> AsyncIterator[str]:
            while True:
                chunk = await text_queue.get()
                if chunk is None:
                    break
                yield chunk

        # Stream through TTS
        voice_id = agent.voice_id if agent else ""
        tts = TTSWebSocket(voice_id=voice_id)
        self._active_tts = tts
        await tts.connect()

        _sentence_end = re.compile(r"[.!?\n]")
        buffer = ""

        async def _feed_tts() -> None:
            nonlocal buffer
            try:
                async for chunk in _text_iter():
                    buffer += chunk
                    while True:
                        match = _sentence_end.search(buffer)
                        if not match:
                            break
                        end = match.end()
                        sentence = buffer[:end]
                        buffer = buffer[end:]
                        await tts.send_text(sentence)
                if buffer.strip():
                    await tts.send_text(buffer)
                await tts.finish()
            except asyncio.CancelledError:
                pass

        feed_task = asyncio.create_task(_feed_tts())

        try:
            async for audio_bytes in tts.iter_audio():
                audio_b64 = base64.b64encode(audio_bytes).decode()
                await _send(self._ws, {
                    "type": "audio_chunk",
                    "agent_id": agent_id,
                    "data": audio_b64,
                })
        finally:
            if not feed_task.done():
                feed_task.cancel()
                try:
                    await feed_task
                except asyncio.CancelledError:
                    pass
            if not text_task.done():
                text_task.cancel()
                try:
                    await text_task
                except asyncio.CancelledError:
                    pass
            await tts.close()
            self._active_tts = None

        # Record and complete
        agent_msg = Message(role=MessageRole.AGENT, agent_id=agent_id, content=full_text)
        self._conv.messages.append(agent_msg)

        await _send(self._ws, {
            "type": "message_complete",
            "message": {
                "id": msg_id,
                "role": "assistant",
                "agent_id": agent_id,
                "content": full_text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        })
        await _send(self._ws, {"type": "agent_done", "agent_id": agent_id})

    async def _group_voice_response(self, text: str) -> None:
        """Handle group conversation voice response with oracle orchestration and TTS."""
        from ensemble.voice.tts import TTSWebSocket

        msg_ids: dict[str, str] = {}

        async for event_type, data in self._oracle.run_group_turn_streaming(
            self._conv, text, None
        ):
            if event_type == "topic_set":
                await _send(self._ws, {"type": "topic_set", "topic": data.get("topic", "")})

            elif event_type == "oracle":
                await _send(self._ws, {
                    "type": "oracle_reasoning",
                    "reasoning": data.get("reasoning", ""),
                    "next_speaker": data.get("next_speaker"),
                    "next_speaker_name": data.get("next_speaker_name"),
                    "hint": data.get("hint", ""),
                })

            elif event_type == "turn_change":
                agent_id = data.get("agent_id")
                msg_ids[agent_id] = _uuid.uuid4().hex[:12]
                await _send(self._ws, {"type": "turn_change", "agent_id": agent_id})
                await _send(self._ws, {"type": "agent_speaking", "agent_id": agent_id})

            elif event_type == "chunk":
                # Buffer chunks for TTS — we handle TTS at message completion
                agent_id = data.get("agent_id")
                await _send(self._ws, {
                    "type": "message_chunk",
                    "agent_id": agent_id,
                    "content": data.get("content", ""),
                    "message_id": msg_ids.get(agent_id, ""),
                })

            elif event_type == "message":
                msg = data  # Message object
                agent_id = msg.agent_id
                agent = self._registry.get(agent_id or "")
                voice_id = agent.voice_id if agent else ""

                # Synthesize the full agent response via TTS WebSocket
                if msg.content and voice_id:
                    tts = TTSWebSocket(voice_id=voice_id)
                    self._active_tts = tts
                    await tts.connect()
                    await tts.send_text(msg.content)
                    await tts.finish()

                    try:
                        async for audio_bytes in tts.iter_audio():
                            audio_b64 = base64.b64encode(audio_bytes).decode()
                            await _send(self._ws, {
                                "type": "audio_chunk",
                                "agent_id": agent_id,
                                "data": audio_b64,
                            })
                    finally:
                        await tts.close()
                        self._active_tts = None

                await _send(self._ws, {
                    "type": "message_complete",
                    "message": {
                        "id": msg_ids.get(agent_id, _uuid.uuid4().hex[:12]),
                        "role": "assistant",
                        "agent_id": agent_id,
                        "content": msg.content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                })
                await _send(self._ws, {"type": "agent_done", "agent_id": agent_id})

            elif event_type == "summary":
                await _send(self._ws, {
                    "type": "summary",
                    "content": data.get("content", ""),
                })

    async def stop(self) -> None:
        """Close the voice session and clean up all resources."""
        self._active = False

        if self._response_task and not self._response_task.done():
            self._response_task.cancel()
            try:
                await self._response_task
            except asyncio.CancelledError:
                pass

        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self._active_tts:
            await self._active_tts.close()
            self._active_tts = None

        if self._stt_session:
            await self._stt_session.close()
            self._stt_session = None


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
        await ws.accept()
        await _send(ws, {"type": "error", "message": "Conversation not found"})
        await ws.close(code=4004, reason="Conversation not found")
        return

    await manager.connect(conversation_id, ws)
    voice_session: VoiceSession | None = None

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, {"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type")

            if msg_type == "message":
                await _handle_message(ws, conv, msg, registry, oracle, mistral_client)
            elif msg_type == "audio":
                await _handle_audio(ws, conv, msg, registry, oracle, mistral_client)
            elif msg_type == "voice_state":
                active = msg.get("active", False)
                logger.info("voice_state received: active=%s", active)
                if active and voice_session is None:
                    voice_session = VoiceSession(ws, conv, registry, oracle, mistral_client)
                    await voice_session.start()
                elif not active and voice_session is not None:
                    await voice_session.stop()
                    voice_session = None
            elif msg_type == "audio_stream":
                data = msg.get("data", "")
                if voice_session and data:
                    await voice_session.feed_audio(data)
            elif msg_type == "start_call":
                mode = msg.get("mode", "text")
                call_data = {
                    "id": _uuid.uuid4().hex[:12],
                    "conversation_id": conversation_id,
                    "participants": conv.participant_agent_ids,
                    "oracle_agent_id": "oracle",
                    "status": "active",
                    "mode": mode,
                }
                await _send(ws, {"type": "call_started", "call": call_data})
            elif msg_type == "end_call":
                if voice_session:
                    await voice_session.stop()
                    voice_session = None
                await _send(ws, {"type": "call_ended", "call_id": conversation_id})
            else:
                await _send(ws, {"type": "error", "message": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for conversation %s", conversation_id)
    finally:
        if voice_session:
            await voice_session.stop()
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
        await _send(ws, {"type": "error", "message": "Empty message"})
        return

    if conv.type == ConversationType.DIRECT:
        # Record user message here (direct streaming doesn't do it)
        user_msg = Message(
            role=MessageRole.USER,
            content=content,
            attachments=attachments,
        )
        conv.messages.append(user_msg)
        await _handle_direct_streaming(ws, conv, content, attachments, registry, mistral_client)
    else:
        # Group streaming handler (oracle) records the user message internally
        await _handle_group_streaming(
            ws, conv, content, attachments, registry, oracle, mistral_client
        )


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
        await _send(ws, {"type": "error", "message": f"Agent {agent_id} not ready"})
        return

    inputs = build_inputs(content, attachments)
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
        await _send(ws, {"type": "error", "message": "Agent response failed"})


async def _handle_group_streaming(
    ws: WebSocket,
    conv: Conversation,
    content: str,
    attachments: list[Attachment],
    registry: AgentRegistry,
    oracle: OracleEngine,
    mistral_client: Any,
) -> None:
    """Handle group conversation using Mistral native handoffs with streaming."""
    try:
        msg_ids: dict[str, str] = {}  # agent_id -> current message_id

        async for event_type, data in oracle.run_group_turn_streaming(
            conv, content, attachments or None
        ):
            if event_type == "topic_set":
                await _send(ws, {
                    "type": "topic_set",
                    "topic": data.get("topic", ""),
                })

            elif event_type == "oracle":
                await _send(ws, {
                    "type": "oracle_reasoning",
                    "reasoning": data.get("reasoning", ""),
                    "next_speaker": data.get("next_speaker"),
                    "next_speaker_name": data.get("next_speaker_name"),
                    "hint": data.get("hint", ""),
                })

            elif event_type == "turn_change":
                agent_id = data.get("agent_id")
                msg_ids[agent_id] = _uuid.uuid4().hex[:12]
                await _send(ws, {
                    "type": "turn_change",
                    "agent_id": agent_id,
                })

            elif event_type == "chunk":
                agent_id = data.get("agent_id")
                await _send(ws, {
                    "type": "message_chunk",
                    "agent_id": agent_id,
                    "content": data.get("content", ""),
                    "message_id": msg_ids.get(agent_id, ""),
                })

            elif event_type == "message":
                msg = data  # This is a Message object
                await _send(ws, {
                    "type": "message_complete",
                    "message": {
                        "id": msg_ids.get(msg.agent_id, _uuid.uuid4().hex[:12]),
                        "role": "assistant",
                        "agent_id": msg.agent_id,
                        "content": msg.content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                })

            elif event_type == "summary":
                await _send(ws, {
                    "type": "summary",
                    "content": data.get("content", ""),
                })

    except Exception:
        logger.exception("Group streaming failed")
        await _send(ws, {"type": "error", "message": "Group conversation failed"})


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
        await _send(ws, {"type": "error", "message": "No audio data"})
        return

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        await _send(ws, {"type": "error", "message": "Invalid base64 audio"})
        return

    # 1. Transcribe
    text = await transcribe_audio(mistral_client, audio_bytes)
    if not text:
        await _send(ws, {"type": "error", "message": "Could not transcribe audio"})
        return

    await _send(ws, {"type": "transcription", "text": text})

    # 2. Get agent response (reuse message handler logic)
    await _handle_message(
        ws, conv, {"content": text, "attachments": []},
        registry, oracle, mistral_client,
    )

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
                "type": "audio_chunk",
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

    If a function call is detected, falls back to non-streaming to handle
    tool execution and re-prompting.

    Event types from Mistral:
      - ResponseStartedEvent: contains conversation_id
      - MessageOutputEvent: contains content (text chunk), agent_id, role
      - FunctionCallEvent: agent wants to call a tool
      - ResponseDoneEvent: contains usage stats
    """
    full_text = ""
    has_function_call = False
    msg_id = _uuid.uuid4().hex[:12]

    if mistral_conv_id:
        stream = await mistral_client.beta.conversations.append_stream_async(
            conversation_id=mistral_conv_id,
            inputs=inputs,
            handoff_execution="client",
        )
    else:
        stream = await mistral_client.beta.conversations.start_stream_async(
            agent_id=mistral_agent_id,
            inputs=inputs,
            handoff_execution="client",
        )

    async for event in stream:
        data = event.data

        # ResponseStartedEvent — capture conversation_id
        if hasattr(data, "conversation_id") and data.conversation_id:
            conv.mistral_conversation_ids[agent_id] = data.conversation_id

        # Detect function calls
        dtype = type(data).__name__
        if "FunctionCall" in dtype:
            has_function_call = True

        # MessageOutputEvent — stream text chunks
        if hasattr(data, "content"):
            text = _extract_chunk_text(data)
            if text:
                full_text += text
                await _send(ws, {
                    "type": "message_chunk",
                    "agent_id": agent_id,
                    "content": text,
                    "message_id": msg_id,
                })

    # If there was a function call, handle it via non-streaming path
    if has_function_call:
        mistral_conv_id = conv.mistral_conversation_ids.get(agent_id)
        if mistral_conv_id:
            response = await mistral_client.beta.conversations.append_async(
                conversation_id=mistral_conv_id,
                inputs="Please proceed with the tool call.",
            )
            response = await _handle_function_calls(
                mistral_client, response, conv, agent_id
            )
            tool_reply = extract_reply(response)
            if tool_reply:
                full_text = tool_reply
                await _send(ws, {
                    "type": "message_chunk",
                    "agent_id": agent_id,
                    "content": tool_reply,
                    "message_id": msg_id,
                })

    # Send complete message
    await _send(ws, {
        "type": "message_complete",
        "message": {
            "id": msg_id,
            "role": "assistant",
            "agent_id": agent_id,
            "content": full_text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    })

    return full_text


def _extract_chunk_text(output) -> str:
    """Extract text from a streaming output chunk.

    Delegates to the shared ``extract_text_from_content`` helper.
    Returns empty string if the output has no ``content`` attribute.
    """
    if hasattr(output, "content"):
        return extract_text_from_content(output.content)
    return ""


async def _send(ws: WebSocket, data: dict) -> None:
    """Send JSON to WebSocket, ignoring errors on closed connections."""
    if ws.client_state == WebSocketState.CONNECTED:
        try:
            await ws.send_json(data)
        except Exception:
            pass
