from __future__ import annotations

import base64

from fastapi import APIRouter, File as FastAPIFile, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ensemble.conversations.models import Attachment, ConversationType

router = APIRouter(prefix="/api")

# These get set during app startup
_registry = None
_conversation_mgr = None
_oracle = None
_mistral_client = None


def init(registry, conversation_mgr, oracle, mistral_client=None):
    global _registry, _conversation_mgr, _oracle, _mistral_client
    _registry = registry
    _conversation_mgr = conversation_mgr
    _oracle = oracle
    _mistral_client = mistral_client


# ── Agents ──────────────────────────────────────────────────────────────────


@router.get("/agents")
async def list_agents():
    return [
        {
            "id": a.id,
            "name": a.name,
            "role": a.role,
            "bio": a.bio,
            "personality": a.personality,
            "avatar_url": a.avatar_url,
            "voice_id": a.voice_id,
            "ready": a.mistral_agent_id is not None,
        }
        for a in _registry.agents.values()
    ]


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = _registry.get(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return {
        "id": agent.id,
        "name": agent.name,
        "role": agent.role,
        "bio": agent.bio,
        "personality": agent.personality,
        "avatar_url": agent.avatar_url,
        "voice_id": agent.voice_id,
        "ready": agent.mistral_agent_id is not None,
    }


# ── Conversations ──────────────────────────────────────────────────────────


class CreateConversationRequest(BaseModel):
    type: ConversationType
    participant_agent_ids: list[str]


@router.post("/conversations")
async def create_conversation(req: CreateConversationRequest):
    try:
        conv = _conversation_mgr.create(req.type, req.participant_agent_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": conv.id, "type": conv.type, "participants": conv.participant_agent_ids}


@router.get("/conversations")
async def list_conversations():
    return [
        {
            "id": c.id,
            "type": c.type,
            "participants": c.participant_agent_ids,
            "message_count": len(c.messages),
            "created_at": c.created_at.isoformat(),
        }
        for c in _conversation_mgr.list_all()
    ]


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    conv = _conversation_mgr.get(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return {
        "id": conv.id,
        "type": conv.type,
        "participants": conv.participant_agent_ids,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "agent_id": m.agent_id,
                "content": m.content,
                "attachments": [a.model_dump() for a in m.attachments],
                "timestamp": m.timestamp.isoformat(),
            }
            for m in conv.messages
        ],
    }


class SendMessageRequest(BaseModel):
    content: str
    attachments: list[Attachment] = []


@router.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, req: SendMessageRequest):
    conv = _conversation_mgr.get(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    if conv.type == ConversationType.DIRECT:
        try:
            reply = await _conversation_mgr.send_direct_message(
                conversation_id, req.content, req.attachments or None
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {
            "id": reply.id,
            "role": reply.role,
            "agent_id": reply.agent_id,
            "content": reply.content,
            "timestamp": reply.timestamp.isoformat(),
        }
    else:
        # Group conversation — oracle-driven
        try:
            replies = await _oracle.run_group_turn(
                conv,
                req.content,
                req.attachments or None,
                max_rounds=len(conv.participant_agent_ids),
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        return [
            {
                "id": r.id,
                "role": r.role,
                "agent_id": r.agent_id,
                "content": r.content,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in replies
        ]


# ── Messages with image upload ─────────────────────────────────────────


@router.post("/conversations/{conversation_id}/messages/upload")
async def send_message_with_image(
    conversation_id: str,
    content: str = "",
    image: UploadFile | None = None,
):
    """Send a message with an optional image attachment (multipart form).

    The image is base64-encoded and sent to Mistral as a data URL.
    """
    conv = _conversation_mgr.get(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    attachments: list[Attachment] = []
    if image:
        img_bytes = await image.read()
        mime = image.content_type or "image/png"
        b64 = base64.b64encode(img_bytes).decode()
        attachments.append(Attachment(type="image", url=f"data:{mime};base64,{b64}"))

    if conv.type == ConversationType.DIRECT:
        reply = await _conversation_mgr.send_direct_message(
            conversation_id, content, attachments or None
        )
        return {
            "id": reply.id,
            "role": reply.role,
            "agent_id": reply.agent_id,
            "content": reply.content,
            "timestamp": reply.timestamp.isoformat(),
        }
    else:
        replies = await _oracle.run_group_turn(
            conv, content, attachments or None, max_rounds=len(conv.participant_agent_ids)
        )
        return [
            {
                "id": r.id,
                "role": r.role,
                "agent_id": r.agent_id,
                "content": r.content,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in replies
        ]


# ── Voice ──────────────────────────────────────────────────────────────────


@router.post("/voice/transcribe")
async def transcribe(file: UploadFile):
    """Transcribe audio to text using Mistral Voxtral STT."""
    from ensemble.voice.stt import transcribe_audio

    if not _mistral_client:
        raise HTTPException(500, "Mistral client not initialized")
    audio_data = await file.read()
    text = await transcribe_audio(_mistral_client, audio_data)
    return {"text": text}


class SynthesizeRequest(BaseModel):
    text: str
    voice_id: str = ""


@router.post("/voice/synthesize")
async def synthesize_endpoint(req: SynthesizeRequest):
    """Synthesize text to speech using ElevenLabs."""
    from ensemble.voice.tts import synthesize

    try:
        audio = await synthesize(req.text, voice_id=req.voice_id)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return Response(content=audio, media_type="audio/mpeg")
