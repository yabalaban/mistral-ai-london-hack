# Ensemble — Multi-Agent Voice Conversations

## Deadline: Sunday March 1, 4pm UK

---

## Product Vision

Discord-like experience with AI agents as participants. Each agent has a distinct personality, background, and skills. Users can:

1. **Browse agents** — roster with profiles, avatars, bios
2. **1:1 chat** — DM any agent, ChatGPT-style text conversation
3. **Group calls** — assemble agents into a room, have voice conversations with an oracle steering turns

## Demo Script (3 conversations)

### Demo 1: Hackathon Idea Discussion
- User creates a group with 2-3 agents (e.g. engineer, designer, business strategist)
- Starts a voice call
- Group brainstorms hackathon ideas via voice
- Shows: multi-agent dialogue, personality differentiation, creative collaboration

### Demo 2: AI Gaming Companion — Chess Puzzle
- User shares a chess puzzle image in a group with 2 agents
- Agents analyze the position, discuss candidate moves, debate
- Shows: multimodal (vision), collaborative reasoning

### Demo 3: PA Slides Generation
- User asks a PA agent (1:1 or group) to create slides from notes
- Agent uses tool calling to generate a presentation
- Shows: tool use, practical utility

---

## Architecture

```
┌─────────────────────────────────────────┐
│            Frontend (Preact + Vite)      │
│  ┌──────────┬──────────┬──────────────┐ │
│  │  Roster  │  1:1 Chat│  Group Call   │ │
│  │  View    │  View    │  View        │ │
│  └──────────┴──────────┴──────────────┘ │
└──────────────┬──────────────────────────┘
               │ HTTP + WebSocket
┌──────────────▼──────────────────────────┐
│         Backend (Python + FastAPI)       │
│  ┌──────────────────────────────────┐   │
│  │  Agent Registry                  │   │
│  │  (profiles, personalities, tools)│   │
│  ├──────────────────────────────────┤   │
│  │  Conversation Manager            │   │
│  │  (1:1 history, message routing)  │   │
│  ├──────────────────────────────────┤   │
│  │  Oracle Engine                   │   │
│  │  (group orchestration, turns)    │   │
│  ├──────────────────────────────────┤   │
│  │  Voice Bridge                    │   │
│  │  (ElevenLabs TTS + STT)         │   │
│  └──────────────────────────────────┘   │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│          External APIs                   │
│  ┌────────────┐  ┌───────────────────┐  │
│  │ Mistral    │  │ ElevenLabs        │  │
│  │ Agents API │  │ TTS / STT         │  │
│  └────────────┘  └───────────────────┘  │
└─────────────────────────────────────────┘
```

## Tech Stack

| Layer    | Choice              | Why                              |
|----------|---------------------|----------------------------------|
| Frontend | Preact + Vite       | 3KB, React DX, zero bloat       |
| Backend  | Python, FastAPI, uv | Thin, fast, Alex's preference    |
| LLM      | Mistral Agents API  | Hosted, multi-agent, vision, tools|
| Voice    | ElevenLabs          | TTS + STT, multiple voice profiles|
| Linting  | Ruff                | Fast Python linting              |
| Types    | Python type hints   | Lightweight correctness          |
| Storage  | In-memory + JSON    | No DB for hackathon, extensible  |

## Data Models

### Agent Profile
```json
{
  "id": "engineer-emma",
  "name": "Emma",
  "role": "Software Engineer",
  "bio": "Senior engineer with 10 years in distributed systems...",
  "avatar": "/avatars/emma.png",
  "personality": "Pragmatic, detail-oriented, dry humor",
  "system_prompt": "You are Emma, a senior software engineer...",
  "voice_id": "elevenlabs-voice-id",
  "tools": ["code_interpreter"],
  "model": "mistral-medium-latest"
}
```

### Conversation
```json
{
  "id": "conv-uuid",
  "type": "direct | group",
  "participants": ["user", "engineer-emma"],
  "messages": [
    {
      "role": "user | assistant",
      "agent_id": "engineer-emma",
      "content": "...",
      "timestamp": "...",
      "attachments": []
    }
  ]
}
```

### Group Call
```json
{
  "id": "call-uuid",
  "conversation_id": "conv-uuid",
  "participants": ["engineer-emma", "designer-dan"],
  "oracle_agent_id": "oracle",
  "status": "active | ended",
  "mode": "text | voice"
}
```

## API Surface

### REST Endpoints

```
GET    /api/agents                  — list all agents
GET    /api/agents/:id              — agent profile
POST   /api/conversations           — create conversation (direct or group)
GET    /api/conversations/:id       — get conversation with messages
POST   /api/conversations/:id/messages — send message (user text or image)
POST   /api/conversations/:id/call  — start group call
DELETE /api/conversations/:id/call  — end group call
```

### WebSocket

```
WS /ws/conversations/:id
  → server sends: agent responses (streamed), turn changes, call events
  ← client sends: user messages, voice audio chunks
```

## Agent Registry (Demo Set)

| Agent | Personality | Skills | Demo Role |
|-------|------------|--------|-----------|
| Emma | Pragmatic engineer, dry humor | code, reasoning | Demo 1 |
| Dan | Creative designer, visual thinker | vision, ideation | Demo 1, 2 |
| Sofia | Business strategist, data-driven | analysis, slides | Demo 1, 3 |
| Marcus | Chess enthusiast, analytical | vision, reasoning | Demo 2 |
| PA (Alex) | Efficient assistant, organized | tools, slides | Demo 3 |
| Oracle | Meta-orchestrator (invisible) | conversation steering | All groups |

## Oracle Design

The Oracle is a Mistral agent with a meta-prompt:
- Receives full conversation context
- Decides who speaks next based on: topic relevance, recency, expertise
- Outputs: `{"next_speaker": "agent-id", "prompt": "optional steering hint"}`
- Never speaks to the user directly — invisible conductor
- Uses Mistral's handoff capability to route to the next agent

## Voice Pipeline (Step 3)

```
User speaks → Browser MediaRecorder → WebSocket → Backend
  → STT (ElevenLabs/Whisper) → text
  → Oracle decides next speaker
  → Agent responds (Mistral) → text
  → TTS (ElevenLabs, agent's voice) → audio
  → WebSocket → Browser plays audio
```

## Work Split

### Alex (Claude Code, local)
- Frontend: Preact app, views, components, styling
- Voice integration (browser-side MediaRecorder, audio playback)

### Jerry (Pi)
- Backend: FastAPI app, agent registry, conversation manager
- Oracle engine
- Mistral API integration
- ElevenLabs integration
- Agent profiles and prompts

## Project Structure

```
mistral-ai-london-hack/
├── PLAN.md
├── README.md
├── backend/
│   ├── pyproject.toml
│   ├── src/
│   │   └── ensemble/
│   │       ├── __init__.py
│   │       ├── main.py          # FastAPI app
│   │       ├── config.py        # settings, env vars
│   │       ├── agents/
│   │       │   ├── __init__.py
│   │       │   ├── registry.py  # agent profiles, loading
│   │       │   └── profiles/    # agent JSON configs
│   │       ├── conversations/
│   │       │   ├── __init__.py
│   │       │   ├── manager.py   # conversation CRUD
│   │       │   └── models.py    # pydantic models
│   │       ├── oracle/
│   │       │   ├── __init__.py
│   │       │   └── engine.py    # orchestration logic
│   │       ├── voice/
│   │       │   ├── __init__.py
│   │       │   ├── tts.py       # ElevenLabs TTS
│   │       │   └── stt.py       # STT integration
│   │       └── api/
│   │           ├── __init__.py
│   │           ├── routes.py    # REST endpoints
│   │           └── ws.py        # WebSocket handlers
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── app.jsx
│       ├── components/
│       └── styles/
└── agents/                      # agent profile configs
    ├── emma.json
    ├── dan.json
    ├── sofia.json
    ├── marcus.json
    ├── pa.json
    └── oracle.json
```

## Timeline (28 hours)

### Phase 1: Foundation (Sat evening, ~6h)
- [ ] Scaffold backend + frontend
- [ ] Agent registry + profiles
- [ ] 1:1 chat working (text, no voice)
- [ ] Basic frontend with roster + chat view

### Phase 2: Multi-Agent (Sun morning, ~6h)
- [ ] Oracle engine
- [ ] Group conversations
- [ ] Vision support (image upload → Mistral)
- [ ] Group chat view in frontend

### Phase 3: Voice (Sun afternoon, ~4h)
- [ ] ElevenLabs TTS integration
- [ ] STT integration
- [ ] Voice call UI
- [ ] Audio streaming via WebSocket

### Phase 4: Polish (Sun, final ~4h)
- [ ] Slides tool for Demo 3
- [ ] Demo rehearsal
- [ ] Bug fixes, UX polish
- [ ] Deploy decision (local vs Pi)

---

## Open Questions
- Slides format: TBD (python-pptx? Reveal.js? PDF?)
- ElevenLabs voice IDs: need to pick/clone voices per agent
- Mistral agent IDs: create via API or La Plateforme?
