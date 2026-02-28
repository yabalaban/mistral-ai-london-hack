# Circles (Ensemble)

Multi-agent chat platform — Discord-like experience where AI agents are participants. Users browse agents, chat 1:1, and create group threads with oracle-steered turn-taking.

## Quick Start

```bash
# Backend (Python 3.11+, uv)
cd backend && uv run python -m ensemble

# Frontend (Node 18+)
cd frontend && npm install && npm run dev
```

Backend runs on :8000, frontend on :3000. Vite proxies `/api` and `/ws` to the backend.

## Required Environment

Create `backend/.env`:
```
MISTRAL_API_KEY=...         # Required — Mistral Agents API
ELEVENLABS_API_KEY=...      # Optional — voice/TTS features
```

## Project Structure

```
backend/
  src/ensemble/
    main.py              # FastAPI app, lifespan, WS route
    config.py            # Settings from env vars
    agents/
      registry.py        # Load JSON profiles, sync to Mistral
      models.py          # AgentProfile pydantic model
    conversations/
      manager.py         # 1:1 routing, function call handling
      models.py          # Conversation, Message, Attachment models
    oracle/
      engine.py          # Group turn orchestration, topic grading
    voice/
      tts.py             # ElevenLabs TTS
      stt.py             # Mistral Voxtral STT
    tools/
      slides.py          # Reveal.js slide generation
    api/
      routes.py          # REST endpoints
      ws.py              # WebSocket handler + ConnectionManager
  agents/                # Agent profile JSON files (emma, sofia, dan, marcus, pa)
  tests/

frontend/
  src/
    app.tsx              # Router: / → Roster, /chat/:id → Chat, /group/:id → Group
    types/index.ts       # All TypeScript interfaces
    api/
      client.ts          # HTTP API wrapper (fetch-based)
      ws.ts              # WebSocketManager singleton
    state/
      agents.ts          # Agent signals + computed agentMap
      conversations.ts   # Conversation signals, streaming state
      call.ts            # Active call, speaker, mic state
    hooks/
      useAgents.ts       # Fetch agents on mount
      useConversation.ts # Load conv + connect WS
      useVoice.ts        # MediaRecorder + audio playback
      useWebSocket.ts    # WS event subscriptions
    components/
      layout/            # Shell, Header, Sidebar
      roster/            # RosterPage, AgentCard, CreateAgentModal, NewGroupModal
      chat/              # ChatPage, MessageList, MessageBubble, ChatInput, Markdown
      group/             # GroupPage, GroupMessages, ParticipantRing, CallControls
      shared/            # Avatar, Button, Spinner, ImageUpload, LogsPanel
```

## Tech Stack

- **Frontend**: Preact + Preact Signals + Preact Router + Tailwind CSS v4 + Vite
- **Backend**: Python 3.11 + FastAPI + Uvicorn + Pydantic
- **LLM**: Mistral Agents API (beta conversations + streaming)
- **Voice**: ElevenLabs TTS, Mistral Voxtral STT
- **Tools**: Reveal.js slides via Playwright PDF export
- **Storage**: In-memory (no database)

## Key Conventions

### Frontend
- **Preact, not React** — imports from `preact`, `preact/hooks`, `@preact/signals`. Vite aliases `react` → `preact/compat`.
- **Signals for state** — use `signal()` for primitives, `computed()` for derived. No Redux, no Context.
- **Tailwind utility classes** — dark theme with glass morphism (`glass`, `glass-strong`), cyan accent (`#06b6d4`).
- **`.ts` extensions in imports** — always use explicit extensions (`./foo.ts`, `./Bar.tsx`).
- Components use functional style with hooks. No class components.

### Backend
- **Ruff for linting** — line length 100, target Python 3.11.
- **Pydantic models** for validation (not TypedDict).
- **Async everywhere** — all Mistral calls use `*_async` variants.
- **Mistral beta API** — `client.beta.conversations.start_stream_async()` / `append_stream_async()` / `client.beta.agents.create_async()`.
- Agent profiles live in `backend/agents/*.json`, loaded at startup by `AgentRegistry`.

### WebSocket Protocol
Client sends: `message`, `audio`, `start_call`, `end_call`
Server sends: `message_chunk`, `message_complete`, `turn_change`, `oracle_reasoning`, `topic_set`, `summary`, `audio_chunk`, `transcription`, `call_started`, `call_ended`, `error`

### Agent JSON Schema
```json
{
  "id": "emma",
  "name": "Emma",
  "role": "Software Engineer",
  "bio": "...",
  "personality": "...",
  "instructions": "System prompt for Mistral...",
  "model": "mistral-medium-latest",
  "tools": ["code_interpreter"]
}
```
Optional fields: `voice_id`, `avatar_url`.

## Common Tasks

### Add a new agent
1. Create `backend/agents/<id>.json` following the schema above
2. Restart backend — `AgentRegistry.load_profiles()` picks it up and `sync_to_mistral()` creates the Mistral agent

### Add a new tool
1. Define handler in `backend/src/ensemble/tools/`
2. Add tool schema to `BUILT_IN_TOOLS` in `agents/registry.py`
3. Add handler to `TOOL_HANDLERS` in `conversations/manager.py`
4. Reference tool name in agent's JSON `tools` array

### Add a new WS event type
1. Add to `WSEvent` union in `frontend/src/types/index.ts`
2. Handle in `dispatch()` in `frontend/src/api/ws.ts`
3. Emit from backend in `api/ws.py`

## Architecture Notes

- **Oracle Engine** — invisible moderator for group chats. Uses `mistral-small-latest` to pick next speaker via JSON response. Handles directed messages ("Sofia, can you..."), topic extraction, and round summaries.
- **Mistral Conversations API** — each agent gets a persistent Mistral conversation per thread (`conv.mistral_conversation_ids[agent_id]`). First message uses `start_stream_async`, subsequent use `append_stream_async`.
- **Optimistic UI** — user messages appear immediately, agent responses stream in via WS chunks.
- **No persistence** — all state is in-memory. Restart clears conversations. Agent profiles reload from JSON.

## Don't

- Don't add React imports — this is Preact
- Don't use Redux, Context, or Zustand — use Signals
- Don't add a database without discussing first — in-memory is intentional for now
- Don't install new npm packages without asking — the bundle is intentionally minimal
