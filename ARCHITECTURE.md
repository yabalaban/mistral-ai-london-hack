# Architecture

## System Overview

```
┌──────────────────────────────────────────────────┐
│              Frontend (Preact + Vite)             │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │  Roster  │  │ 1:1 Chat │  │  Group Chat   │  │
│  │  (/)     │  │ (/chat/) │  │  (/group/)    │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
│                                                  │
│  State: Preact Signals    WS: WebSocketManager   │
└───────────────┬──────────────────────────────────┘
                │ HTTP (REST) + WebSocket
┌───────────────▼──────────────────────────────────┐
│            Backend (Python + FastAPI)             │
│                                                  │
│  ┌─────────────────┐  ┌──────────────────────┐   │
│  │ Agent Registry   │  │ Conversation Manager │   │
│  │ (profiles,sync)  │  │ (1:1 routing, tools) │   │
│  ├─────────────────┤  ├──────────────────────┤   │
│  │ Oracle Engine    │  │ Voice Bridge         │   │
│  │ (group turns)    │  │ (TTS + STT)         │   │
│  └─────────────────┘  └──────────────────────┘   │
└───────────────┬──────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────┐
│              External APIs                        │
│  ┌──────────────────┐  ┌─────────────────────┐   │
│  │ Mistral Agents   │  │ ElevenLabs TTS/STT  │   │
│  │ (LLM backbone)   │  │ (voice synthesis)   │   │
│  └──────────────────┘  └─────────────────────┘   │
└──────────────────────────────────────────────────┘
```

## Data Flow

### 1:1 Chat

```
User types message
  → ChatInput.handleSend()
  → Optimistic message added to conversation signal
  → wsManager.send({ type: 'message', content, attachments })
  → Backend ws.py: _handle_message() → _handle_direct_streaming()
  → Mistral conversations.start_stream_async / append_stream_async
  → Streaming chunks sent back as message_chunk events
  → Frontend ws.ts dispatch: streamingMessage signal updated
  → MessageBubble re-renders incrementally
  → message_complete event → final message appended to state
```

### Group Chat (Oracle-Orchestrated)

```
User sends message
  → Backend: oracle.run_group_turn_streaming()
  → Step 1: grade_topic() — extract discussion topic if not set
     → Emits topic_set event
  → Step 2: decide_next_speaker() — oracle picks who talks
     → Emits oracle_reasoning + turn_change events
  → Step 3: build_agent_prompt() → stream from agent's Mistral conversation
     → Emits message_chunk events → message_complete
  → Step 4: Loop back to step 2 until oracle says done
     → 1 speaker for directed messages, up to 7 otherwise
  → Step 5: If 2+ agents spoke → generate round summary
     → Emits summary event
```

### Voice Pipeline

```
User speaks → Browser MediaRecorder → base64 WAV
  → WS: { type: 'audio', data: '<base64>' }
  → Backend: transcribe_audio() via Mistral Voxtral
  → WS: { type: 'transcription', text }
  → Route through _handle_message() (same as text)
  → Agent responds → TTS via ElevenLabs
  → WS: { type: 'audio_chunk', data: '<base64 mp3>' }
  → Browser plays audio
```

## Core Components

### Agent Registry (`agents/registry.py`)

Manages the lifecycle of AI agents:
1. **Load** — reads `backend/agents/*.json` into `AgentProfile` models
2. **Sync** — creates corresponding agents on Mistral via `beta.agents.create_async()`
3. **Lookup** — provides `get(agent_id)` for other components
4. **Cleanup** — deletes Mistral agents on shutdown

Each agent profile maps tool names to Mistral tool objects:
- `code_interpreter` → `CodeInterpreterTool`
- `web_search` → `WebSearchTool`
- `image_generation` → `ImageGenerationTool`
- `create_slides` → `FunctionTool` (custom schema)

### Conversation Manager (`conversations/manager.py`)

Handles 1:1 conversations:
- Creates conversations (validates agent exists, enforces type constraints)
- Routes user messages to the agent's Mistral conversation
- Handles function calls (tool use) — executes locally, feeds results back to Mistral
- Stores conversations in-memory dict

### Oracle Engine (`oracle/engine.py`)

The invisible intelligence behind group chats:

**Speaker Selection**: Sends conversation context + participant info to `mistral-small-latest` with JSON response format. Oracle returns `{ next_speaker, hint, reasoning, done }`.

**Topic Grading**: Uses a separate Mistral call to determine if user messages contain a real discussion topic (filters out greetings/small talk). Sets `conversation.topic` when found.

**Directed Messages**: Detects when user addresses a specific agent by name ("Sofia, can you..."). Caps response to that single agent.

**Agent Prompting**: Builds per-agent prompts with thread context, user message, topic, and oracle's hint directive. Keeps responses short ("1-2 sentences, like a human in a group chat").

**Round Summaries**: When 2+ agents spoke, generates a bullet-point summary of key decisions and disagreements.

### WebSocket Layer

**Backend** (`api/ws.py`):
- `ConnectionManager` — tracks active WS connections per conversation
- `handle_conversation_ws()` — main loop dispatching message types
- Streaming: sends incremental `message_chunk` events during Mistral streaming

**Frontend** (`api/ws.ts`):
- `WebSocketManager` singleton — connect/disconnect/send/onEvent
- Auto-reconnect on disconnect (2s delay)
- `dispatch()` updates global signals based on event type

### State Management (Frontend)

Three signal modules, no stores or reducers:

**`state/agents.ts`**: `agents` signal (all agents), `agentMap` computed (id → agent lookup), loading/error signals.

**`state/conversations.ts`**: `conversations` signal, `activeConversationId`, `streamingMessage`/`streamingAgentId` for real-time streaming, `activeConversation` computed. Mutation helpers: `upsertConversation`, `appendMessage`, `updateConversationTopic`.

**`state/call.ts`**: `activeCall`, `currentSpeaker`, `callMode` (text/voice), `isMicOn`, `isRecording`.

## API Surface

### REST

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/agents` | List all agents |
| GET | `/api/agents/:id` | Get agent profile |
| POST | `/api/conversations` | Create conversation (direct/group) |
| GET | `/api/conversations` | List conversations |
| GET | `/api/conversations/:id` | Get conversation + messages |
| POST | `/api/conversations/:id/messages` | Send message (non-streaming) |
| POST | `/api/conversations/:id/messages/upload` | Send with image (multipart) |
| POST | `/api/conversations/:id/call` | Start group call |
| DELETE | `/api/conversations/:id/call` | End call |
| GET | `/slides` | List generated presentations |
| GET | `/slides/:id` | View presentation HTML |
| GET | `/slides/:id/pdf` | Download presentation PDF |
| POST | `/voice/transcribe` | Audio → text (Mistral Voxtral) |
| POST | `/voice/synthesize` | Text → audio (ElevenLabs) |

### WebSocket (`/ws/conversations/:id`)

**Client → Server:**
| Type | Payload | Purpose |
|------|---------|---------|
| `message` | `content`, `attachments[]` | Send text message |
| `audio` | `data` (base64 WAV) | Send voice input |
| `start_call` | `mode` (text/voice) | Start group call |
| `end_call` | — | End call |

**Server → Client:**
| Type | Payload | Purpose |
|------|---------|---------|
| `message_chunk` | `agent_id`, `content`, `message_id` | Streaming text |
| `message_complete` | `message` object | Final message |
| `turn_change` | `agent_id` | Next speaker in group |
| `oracle_reasoning` | `reasoning`, `next_speaker`, `hint` | Oracle's decision |
| `topic_set` | `topic` | Thread topic extracted |
| `summary` | `content` | Round summary |
| `audio_chunk` | `agent_id`, `data` (base64 MP3) | TTS output |
| `transcription` | `text` | STT result |
| `call_started` | `call` object | Call began |
| `call_ended` | `call_id` | Call ended |
| `error` | `message` | Error description |

## Data Models

### Backend (Pydantic)

```python
class AgentProfile(BaseModel):
    id: str
    name: str
    role: str
    bio: str
    personality: str
    instructions: str
    model: str = "mistral-medium-latest"
    tools: list[str] = []
    voice_id: str = ""
    avatar_url: str = ""
    mistral_agent_id: str | None = None  # Set after sync

class Conversation(BaseModel):
    id: str                              # Auto-generated UUID
    type: ConversationType               # direct | group
    participant_agent_ids: list[str]
    messages: list[Message]
    topic: str | None = None
    mistral_conversation_ids: dict[str, str]  # agent_id → mistral conv ID
    created_at: datetime

class Message(BaseModel):
    id: str
    role: MessageRole                    # user | agent | system
    agent_id: str | None = None
    content: str
    attachments: list[Attachment] = []
    timestamp: datetime
```

### Frontend (TypeScript)

```typescript
interface Agent { id, name, role, bio, avatar, personality, voice_id?, tools? }
interface Message { id, role, agent_id?, content, timestamp, attachments? }
interface Conversation { id, type, participants, messages, topic?, created_at }
interface GroupCall { id, conversation_id, participants, oracle_agent_id, status, mode }
type WSEvent = message_chunk | message_complete | turn_change | oracle_reasoning | topic_set | summary | call_started | call_ended | audio_chunk | transcription | error
```

## Mistral Integration Details

### Agent Lifecycle
1. JSON profile loaded from disk → `AgentProfile`
2. `registry.sync_to_mistral()` → `client.beta.agents.create_async()` → stores `mistral_agent_id`
3. On user message → `client.beta.conversations.start_stream_async(agent_id=...)` → stores `mistral_conversation_id`
4. Subsequent messages → `client.beta.conversations.append_stream_async(conversation_id=...)`
5. On shutdown → `client.beta.agents.delete_async()` cleans up

### Per-Agent Conversations in Groups
Each agent maintains its own Mistral conversation within a group thread (`conv.mistral_conversation_ids[agent_id]`). The oracle builds a context prompt with thread history, so each agent sees what others said even though their Mistral conversations are separate.

### Function Calls (Tool Use)
When Mistral returns a `FunctionCallEvent`:
1. Backend detects `"FunctionCall"` in event type name
2. Falls back to non-streaming `append_async` with `"Please proceed with the tool call."`
3. Extracts function name + arguments from response
4. Executes handler from `TOOL_HANDLERS` dict
5. Sends `FunctionResultEntry` back to Mistral conversation
6. Loops up to 3 rounds for chained tool calls

## UI Design System

- **Theme**: Dark mode, gradient background (`#0a0a1a` → `#1a0a2e`), cyan accent (`#06b6d4`)
- **Font**: Inter (400/500/600/700)
- **Effects**: Glass morphism (`backdrop-blur`), glowing shadows, smooth transitions
- **Components**: Functional Preact + Tailwind utilities
- **Animations**: `dot-pulse` (typing indicator), `speaking-glow` (active speaker ring)

## Current Agents

| ID | Name | Role | Tools | Voice |
|----|------|------|-------|-------|
| emma | Emma | Software Engineer | code_interpreter | - |
| sofia | Sofia | Business Strategist | web_search | - |
| dan | Dan | Product Designer | — | - |
| marcus | Marcus | Chess Coach & Analyst | — | - |
| pa | Alex | Personal Assistant | create_slides, web_search | - |

## Known Limitations

- **No persistence** — conversations lost on restart
- **In-memory storage** — not suitable for production scale
- **No auth** — open access, single user assumed
- **Oracle cost** — each group message triggers 1+ oracle calls + 1 per agent response
- **Function call fallback** — tool use drops from streaming to non-streaming mode
