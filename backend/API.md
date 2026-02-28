# Ensemble Backend API Documentation

Base URL: `http://localhost:8000`

## Quick Start

```bash
cd backend
cp .env.example .env  # Add your MISTRAL_API_KEY and ELEVENLABS_API_KEY
uv sync
PYTHONPATH=src uv run python -m ensemble
```

Server starts on `:8000`. Agents are created on Mistral at startup and cleaned up on shutdown.

---

## REST Endpoints

### Health Check

```
GET /health
```

**Response:** `{"status": "ok"}`

---

### Agents

#### List All Agents

```
GET /api/agents
```

**Response:**
```json
[
  {
    "id": "emma",
    "name": "Emma",
    "role": "Software Engineer",
    "bio": "Senior engineer with 10 years in distributed systems...",
    "personality": "Direct, pragmatic, dry humor...",
    "avatar_url": "",
    "voice_id": "",
    "ready": true
  }
]
```

- `ready`: `true` when the agent has been synced to Mistral and can participate in conversations.

#### Get Single Agent

```
GET /api/agents/{agent_id}
```

**Response:** Same shape as list item. Returns `404` if not found.

---

### Conversations

#### Create Conversation

```
POST /api/conversations
Content-Type: application/json
```

**Body:**
```json
{
  "type": "direct",
  "participant_agent_ids": ["emma"]
}
```

- `type`: `"direct"` (1:1 with one agent) or `"group"` (multiple agents, oracle-driven)
- `participant_agent_ids`: List of agent IDs. Direct must have exactly 1.

**Response:**
```json
{
  "id": "a1b2c3d4...",
  "type": "direct",
  "participants": ["emma"]
}
```

#### List Conversations

```
GET /api/conversations
```

**Response:**
```json
[
  {
    "id": "a1b2c3d4...",
    "type": "direct",
    "participants": ["emma"],
    "message_count": 5,
    "created_at": "2026-02-28T12:00:00+00:00"
  }
]
```

#### Get Conversation (with messages)

```
GET /api/conversations/{conversation_id}
```

**Response:**
```json
{
  "id": "a1b2c3d4...",
  "type": "direct",
  "participants": ["emma"],
  "messages": [
    {
      "id": "msg123",
      "role": "user",
      "agent_id": null,
      "content": "Hello!",
      "attachments": [],
      "timestamp": "2026-02-28T12:00:00+00:00"
    },
    {
      "id": "msg456",
      "role": "agent",
      "agent_id": "emma",
      "content": "Hey there! What are you working on?",
      "attachments": [],
      "timestamp": "2026-02-28T12:00:01+00:00"
    }
  ]
}
```

---

### Messages

#### Send Text Message

```
POST /api/conversations/{conversation_id}/messages
Content-Type: application/json
```

**Body:**
```json
{
  "content": "What's the best way to design a REST API?",
  "attachments": []
}
```

**For images (inline base64):**
```json
{
  "content": "What do you see in this chess position?",
  "attachments": [
    {
      "type": "image",
      "url": "data:image/png;base64,iVBOR..."
    }
  ]
}
```

**Response (direct conversation):** Single agent message:
```json
{
  "id": "msg789",
  "role": "agent",
  "agent_id": "emma",
  "content": "Great question! Here's what I'd recommend...",
  "timestamp": "2026-02-28T12:00:02+00:00"
}
```

**Response (group conversation):** Array of agent messages (one per participant, oracle-ordered):
```json
[
  {
    "id": "msg789",
    "role": "agent",
    "agent_id": "sofia",
    "content": "From a business perspective...",
    "timestamp": "2026-02-28T12:00:02+00:00"
  },
  {
    "id": "msg790",
    "role": "agent",
    "agent_id": "emma",
    "content": "Technically speaking...",
    "timestamp": "2026-02-28T12:00:03+00:00"
  }
]
```

#### Send Message with Image Upload (Multipart)

```
POST /api/conversations/{conversation_id}/messages/upload
Content-Type: multipart/form-data
```

**Form fields:**
- `content` (string): Text message
- `image` (file, optional): Image file (PNG, JPEG, etc.)

The image is automatically base64-encoded and sent to Mistral as a data URL.

**Response:** Same as text message endpoint.

---

### Voice

#### Transcribe Audio (Speech-to-Text)

```
POST /api/voice/transcribe
Content-Type: multipart/form-data
```

**Form fields:**
- `file` (file): Audio file (WAV, MP3, etc.)

Uses Mistral Voxtral STT.

**Response:**
```json
{
  "text": "Hello, what's the best opening in chess?"
}
```

#### Synthesize Speech (Text-to-Speech)

```
POST /api/voice/synthesize
Content-Type: application/json
```

**Body:**
```json
{
  "text": "Hello! I'd recommend the Sicilian Defense.",
  "voice_id": "optional-elevenlabs-voice-id"
}
```

Uses ElevenLabs TTS. If `voice_id` is empty, uses the default voice.

**Response:** Raw MP3 audio bytes with `Content-Type: audio/mpeg`.

---

## WebSocket

### Conversation WebSocket

```
WS /ws/conversations/{conversation_id}
```

The conversation must be created via REST first (`POST /api/conversations`).

#### Client → Server Messages

All messages are JSON.

**Send a text message:**
```json
{
  "type": "message",
  "content": "What should we build?",
  "attachments": []
}
```

**Send a text message with image:**
```json
{
  "type": "message",
  "content": "Analyze this chess position",
  "attachments": [
    {
      "type": "image",
      "url": "data:image/png;base64,iVBOR..."
    }
  ]
}
```

**Send audio for transcription + agent response:**
```json
{
  "type": "audio",
  "data": "<base64-encoded WAV audio>"
}
```

This triggers the full voice pipeline:
1. Transcribe audio → text (Mistral Voxtral)
2. Send text to agent(s)
3. Get agent response
4. Synthesize response → audio (ElevenLabs)

**Start/end a call session:**
```json
{"type": "start_call", "mode": "voice"}
{"type": "end_call"}
```

#### Server → Client Messages

**Agent message (streaming):**
```json
{
  "type": "agent_message",
  "agent_id": "emma",
  "content": "partial text chunk",
  "done": false
}
```

When `done: true`, `content` contains the **full accumulated text** of the message.

Streaming flow:
1. Multiple `{"done": false}` messages with incremental text chunks
2. One final `{"done": true}` with the complete response

**Turn change (group conversations):**
```json
{
  "type": "turn_change",
  "agent_id": "dan",
  "hint": "Share your design perspective"
}
```

Sent before each agent speaks in a group. The oracle decides the order.

**Audio transcription result:**
```json
{
  "type": "transcription",
  "text": "What the user said"
}
```

**Synthesized audio response:**
```json
{
  "type": "audio",
  "agent_id": "emma",
  "data": "<base64-encoded MP3 audio>"
}
```

**Call lifecycle:**
```json
{"type": "call_started", "mode": "voice"}
{"type": "call_ended"}
```

**Error:**
```json
{
  "type": "error",
  "detail": "Description of what went wrong"
}
```

---

## Conversation Flow Examples

### Example 1: Direct Chat (1:1)

```
1. POST /api/conversations     → {"type": "direct", "participant_agent_ids": ["emma"]}
   Response: {"id": "conv-123"}

2. WS /ws/conversations/conv-123
   → {"type": "message", "content": "What's a good tech stack for a hackathon?"}
   ← {"type": "agent_message", "agent_id": "emma", "content": "I'd ", "done": false}
   ← {"type": "agent_message", "agent_id": "emma", "content": "recommend ", "done": false}
   ← ...
   ← {"type": "agent_message", "agent_id": "emma", "content": "I'd recommend FastAPI + Preact...", "done": true}
```

### Example 2: Group Discussion (Oracle-Driven)

```
1. POST /api/conversations     → {"type": "group", "participant_agent_ids": ["emma", "dan", "sofia"]}
   Response: {"id": "conv-456"}

2. WS /ws/conversations/conv-456
   → {"type": "message", "content": "Let's brainstorm a chess tutoring app"}
   ← {"type": "turn_change", "agent_id": "sofia", "hint": "market opportunity"}
   ← {"type": "agent_message", "agent_id": "sofia", "content": "The ed-tech...", "done": false}
   ← ...
   ← {"type": "agent_message", "agent_id": "sofia", "content": "The ed-tech market is...", "done": true}
   ← {"type": "turn_change", "agent_id": "emma", "hint": "technical feasibility"}
   ← {"type": "agent_message", "agent_id": "emma", "content": "...", "done": true}
   ← {"type": "turn_change", "agent_id": "dan", "hint": "user experience"}
   ← {"type": "agent_message", "agent_id": "dan", "content": "...", "done": true}
```

### Example 3: Voice Call

```
1. Create conversation + connect WS (as above)

2. → {"type": "start_call", "mode": "voice"}
   ← {"type": "call_started", "mode": "voice"}

3. → {"type": "audio", "data": "<base64 WAV>"}
   ← {"type": "transcription", "text": "What's a good opening against e4?"}
   ← {"type": "turn_change", "agent_id": "marcus", "hint": ""}
   ← {"type": "agent_message", "agent_id": "marcus", "content": "...", "done": true}
   ← {"type": "audio", "agent_id": "marcus", "data": "<base64 MP3>"}

4. → {"type": "end_call"}
   ← {"type": "call_ended"}
```

### Example 4: Chess Image Analysis (Multimodal)

```
# Via REST:
POST /api/conversations/conv-456/messages/upload
Content-Type: multipart/form-data
  content: "What's the best move here?"
  image: <chess_puzzle.png>

# Via WebSocket:
→ {
    "type": "message",
    "content": "What's the best move here?",
    "attachments": [{"type": "image", "url": "data:image/png;base64,iVBOR..."}]
  }
```

---

## Agent Profiles

Agents are defined as JSON files in `backend/agents/`. Each file has:

```json
{
  "id": "emma",
  "name": "Emma",
  "role": "Software Engineer",
  "bio": "Senior engineer with 10 years...",
  "personality": "Direct, pragmatic, dry humor...",
  "instructions": "You are Emma, a senior software engineer...",
  "model": "mistral-medium-latest",
  "tools": ["code_interpreter"],
  "voice_id": "",
  "avatar_url": ""
}
```

**Available tools:** `code_interpreter`, `web_search`

**Current agents:**
| ID | Name | Role | Tools |
|-----|------|------|-------|
| `emma` | Emma | Software Engineer | code_interpreter |
| `dan` | Dan | Product Designer | — |
| `sofia` | Sofia | Business Strategist | web_search |
| `marcus` | Marcus | Chess Coach & Analyst | — |
| `pa` | Alex's PA | Personal Assistant | code_interpreter |

---

## Configuration

Environment variables (in `backend/.env`):

| Variable | Required | Description |
|----------|----------|-------------|
| `MISTRAL_API_KEY` | Yes | Mistral API key for agents, conversations, STT |
| `ELEVENLABS_API_KEY` | No | ElevenLabs API key for TTS (voice synthesis) |

---

## Architecture Notes

- **Agent lifecycle**: Agents are created on Mistral at server startup, deleted on shutdown. Each agent gets a `mistral_agent_id` that persists for the session.
- **Conversations**: Use Mistral's Conversations API with server-side history. Each agent in a group gets its own Mistral conversation (separate context).
- **Oracle**: Uses `mistral-small-latest` with JSON mode to decide turn order. Invisible to users.
- **Streaming**: WebSocket responses use `start_stream_async` / `append_stream_async` for real-time text delivery.
- **Vision**: Images must be base64-encoded (Mistral can't reliably fetch external URLs).
- **Voice pipeline**: Mistral Voxtral for STT → Mistral agents for reasoning → ElevenLabs for TTS.
- **In-memory storage**: All conversations are in-memory. Restart = clean slate.
