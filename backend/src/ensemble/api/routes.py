from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ensemble.conversations.models import Attachment, ConversationType

router = APIRouter(prefix="/api")

# These get set during app startup
_registry = None
_conversation_mgr = None
_oracle = None


def init(registry, conversation_mgr, oracle):
    global _registry, _conversation_mgr, _oracle
    _registry = registry
    _conversation_mgr = conversation_mgr
    _oracle = oracle


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
