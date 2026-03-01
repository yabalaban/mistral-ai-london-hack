# Circles

**Multi-agent conversation platform where AI agents are real participants — not assistants, but personalities.**

Built in 28 hours at the [Mistral AI London Hackathon](https://mistral.ai/) (March 2025). Users browse a roster of AI agents, chat 1:1, assemble groups for collaborative discussions, and hold voice calls — all orchestrated by an invisible oracle that manages turn-taking, topic extraction, and conversation flow.

> **Fully authored by [Claude Code](https://claude.ai/claude-code) (Anthropic) and the [OpenClaw](https://openclaw.ai) orchestrator.**
> Every line of code — backend, frontend, agent prompts, voice pipeline, Discord integration — was written by AI agents coordinated through Claude Code and OpenClaw, with human direction on product vision and architecture.

---

## The Idea

Most multi-agent systems treat AI as tools. Circles treats them as **people in a room**.

Each agent has a real backstory, personality quirks, communication style, and domain expertise. When you drop a question into a group, they don't just answer — they debate, build on each other's ideas, disagree, pass when they have nothing to add, and reference each other's points. An invisible **Oracle** moderates: picking who speaks next, steering the conversation toward the user's goal, and knowing when to stop.

The result feels less like prompting a chatbot and more like sitting in a meeting with opinionated colleagues.

### What Makes It Different

- **Oracle-steered turn-taking** — not round-robin, not free-for-all. The oracle classifies each message (casual vs. substantive), ranks which agents should respond, gives each a directional hint, and grades when the goal is met.
- **Personality-first agents** — each agent has a multi-paragraph backstory, voice quirks, and behavioral instructions. Emma (engineer) gives dry one-liners. Sofia (strategist) challenges your unit economics. Kim (PA) already booked the restaurant before you asked.
- **Real-time voice** — push-to-talk with ElevenLabs streaming TTS/STT. Each agent has a distinct voice. Audio streams concurrently with text generation for minimal latency.
- **Discord as a first-class frontend** — the same agents live in Discord with per-channel configuration, slash commands (`/invite`, `/dismiss`, `/call`), and voice channel support.

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│               Frontends                               │
│  ┌────────────────────┐  ┌────────────────────────┐  │
│  │  Web App            │  │  Discord Bot            │  │
│  │  (Preact + Vite)    │  │  (py-cord)              │  │
│  │  localhost:3000      │  │  Text + Voice channels  │  │
│  └─────────┬──────────┘  └──────────┬─────────────┘  │
└────────────┼─────────────────────────┼────────────────┘
             │ HTTP + WebSocket        │ Discord Gateway
┌────────────▼─────────────────────────▼────────────────┐
│              Backend (Python + FastAPI)                 │
│                                                        │
│  ┌────────────────┐  ┌─────────────────────────────┐  │
│  │ Agent Registry  │  │ Conversation Manager         │  │
│  │ JSON profiles   │  │ 1:1 routing, tool execution  │  │
│  │ Mistral sync    │  │ function call handling       │  │
│  ├────────────────┤  ├─────────────────────────────┤  │
│  │ Oracle Engine   │  │ Voice Pipeline               │  │
│  │ Turn-taking     │  │ ElevenLabs TTS (streaming)   │  │
│  │ Topic grading   │  │ ElevenLabs STT (realtime)    │  │
│  │ Goal completion │  │ Mistral Voxtral (batch)      │  │
│  └────────────────┘  └─────────────────────────────┘  │
│                                                        │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Event Bus — system-wide observability             │  │
│  │ oracle_start, turn_change, message, grader, ...   │  │
│  └─────────────────────────────────────────────────┘  │
└───────────────────────┬────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────┐
│                   External APIs                         │
│  ┌─────────────────────┐  ┌─────────────────────────┐  │
│  │ Mistral Agents API   │  │ ElevenLabs              │  │
│  │ LLM backbone         │  │ TTS + STT               │  │
│  │ Conversations API     │  │ Multiple voice profiles │  │
│  │ Tool use (code, web)  │  │ Streaming WebSocket     │  │
│  └─────────────────────┘  └─────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

---

## The Agents

| Agent | Role | Personality | Tools |
|-------|------|-------------|-------|
| **Emma** | Software Engineer | Dry, deadpan, hates unnecessary complexity. 34, Glasgow, decade of distributed systems. | `code_interpreter` |
| **Sofia** | Business Strategist | Sharp, fast-thinking, challenges ideas. Ex-McKinsey, angel investor, dark humor. | `web_search` |
| **Dan** | Product Designer | Warm, visual thinker, obsessed with how details shape feelings. East London, restless energy. | — |
| **Marcus** | Chess Coach | Patient, gets excited about tactics, chess metaphors bleed into everything. FIDE Master, Twitch streamer. | — |
| **Kim** | Personal Assistant | Impossibly organized, moves fast, borderline scary memory. Freelance PA, stress-bakes at midnight. | `create_slides` |

Each agent has a unique ElevenLabs voice and a rich system prompt that includes their bio, personality, and behavioral instructions. Agents are defined as JSON files in `backend/agents/` and synced to Mistral at startup.

---

## How the Oracle Works

The Oracle is an invisible moderator — it never speaks to the user, but controls the entire flow of group conversations.

```
User message arrives
    │
    ▼
┌─────────────────────────┐
│  1. Classify             │  Is this casual ("hey everyone") or substantive
│     Mode + Goal          │  ("let's brainstorm startup ideas")?
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│  2. Rank Agents          │  Who should respond? All (generic) or specific
│     + Hint Directives    │  (domain-matched)? Each gets a 3-5 word hint.
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│  3. Agent Responds       │  Agent sees: thread context, participants,
│     (Mistral streaming)  │  topic, hint, prior messages. Can [PASS] or
│                          │  reply to specific messages with [1], [2]...
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│  4. Grade Completion     │  Has the goal been met? Parallel mode: done
│                          │  after one round. Sequential: continues.
└────────────┬────────────┘
             ▼
        Done? ──No──► Loop (up to 5 rounds)
          │
         Yes
          ▼
┌─────────────────────────┐
│  5. Round Summary        │  Key decisions, disagreements, next steps.
└─────────────────────────┘
```

**Directed messages** ("Sofia, what's the market size?") bypass the oracle and route directly to the named agent.

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Frontend | Preact + Preact Signals + Tailwind CSS v4 + Vite | 3KB framework, reactive signals, zero bloat |
| Backend | Python 3.11+ + FastAPI + Uvicorn + Pydantic | Async-native, thin, fast |
| LLM | Mistral Agents API (beta) | Hosted agents, conversations API, streaming, tool use |
| Voice | ElevenLabs TTS + STT | Low-latency streaming, multiple voice profiles |
| Discord | py-cord | Text + voice channel integration |
| Tools | Reveal.js + Playwright | Slide generation + PDF export |
| Storage | In-memory + JSON files | No database — intentional for hackathon speed |

---

## Project Structure

```
circles/
├── run.sh                        # Start both services
│
├── backend/
│   ├── agents/                   # Agent profile JSON files
│   │   ├── emma.json
│   │   ├── sofia.json
│   │   ├── dan.json
│   │   ├── marcus.json
│   │   └── kim.json
│   ├── src/ensemble/
│   │   ├── main.py               # FastAPI app, lifespan, routes
│   │   ├── config.py             # Environment settings
│   │   ├── events.py             # Global event bus (observability)
│   │   ├── discord_bot.py        # Discord text integration
│   │   ├── discord_voice.py      # Discord voice (sink, STT)
│   │   ├── agents/
│   │   │   ├── registry.py       # Load profiles, sync to Mistral
│   │   │   └── models.py         # AgentProfile model
│   │   ├── conversations/
│   │   │   ├── manager.py        # 1:1 routing, tool execution
│   │   │   └── models.py         # Conversation, Message, Attachment
│   │   ├── oracle/
│   │   │   ├── engine.py         # Group orchestration (~1600 lines)
│   │   │   └── turn_logger.py    # Turn event logging
│   │   ├── voice/
│   │   │   ├── tts.py            # ElevenLabs TTS (SDK + WebSocket)
│   │   │   └── stt.py            # ElevenLabs realtime + Voxtral batch
│   │   ├── tools/
│   │   │   └── slides.py         # Reveal.js presentation generator
│   │   └── api/
│   │       ├── routes.py         # REST endpoints
│   │       └── ws.py             # WebSocket handler (~1100 lines)
│   └── pyproject.toml
│
├── frontend/
│   ├── src/
│   │   ├── app.tsx               # Router (Roster, Activity)
│   │   ├── types/index.ts        # All TypeScript interfaces
│   │   ├── api/
│   │   │   ├── client.ts         # REST API wrapper
│   │   │   └── eventsWs.ts       # System events WebSocket
│   │   ├── state/
│   │   │   ├── agents.ts         # Agent signals + computed map
│   │   │   ├── activity.ts       # Event rounds, filtering
│   │   │   └── ui.ts             # UI state
│   │   ├── hooks/
│   │   │   ├── useAgents.ts      # Fetch agents on mount
│   │   │   └── useActivityFeed.ts
│   │   └── components/
│   │       ├── layout/           # Shell, Header, Sidebar
│   │       ├── roster/           # RosterPage, AgentCard, CreateAgentModal
│   │       ├── activity/         # ActivityPage, EventFeed, RoundCard
│   │       └── shared/           # Avatar, Button, Spinner
│   ├── package.json
│   └── vite.config.js
│
├── CLAUDE.md                     # Project conventions for Claude Code
├── ARCHITECTURE.md               # Detailed system design
└── PLAN.md                       # Original hackathon plan
```

---

## Quick Start

### Prerequisites

- Python 3.11+ with [uv](https://docs.astral.sh/uv/)
- Node.js 18+
- Mistral API key (required)
- ElevenLabs API key (optional — for voice features)
- Discord bot token (optional — for Discord integration)

### Setup

```bash
# Clone
git clone https://github.com/yabalaban/mistral-ai-london-hack.git
cd mistral-ai-london-hack

# Backend environment
cat > backend/.env <<EOF
MISTRAL_API_KEY=your-key-here
ELEVENLABS_API_KEY=your-key-here      # optional
DISCORD_BOT_TOKEN=your-token-here     # optional
DISCORD_GUILD_ID=your-guild-id-here   # optional
EOF

# Install dependencies
cd backend && uv sync && cd ..
cd frontend && npm install && cd ..

# Run both
./run.sh
```

Backend runs on **http://localhost:8000**, frontend on **http://localhost:3000**.

---

## WebSocket Protocol

### Client → Server

| Type | Payload | Purpose |
|------|---------|---------|
| `message` | `content`, `attachments[]` | Send text message |
| `audio_stream` | `data` (base64 PCM) | Stream voice input |
| `start_call` | `mode` (text/voice) | Start group call |
| `end_call` | — | End call |
| `voice_state` | `active` (bool) | PTT press/release |

### Server → Client

| Type | Payload | Purpose |
|------|---------|---------|
| `message_chunk` | `agent_id`, `content`, `message_id` | Streaming text token |
| `message_complete` | `message` object | Final message |
| `turn_change` | `agent_id` | Next speaker selected |
| `oracle_reasoning` | `reasoning`, `speakers[]`, `mode` | Oracle's decision |
| `topic_set` | `topic` | Discussion topic extracted |
| `summary` | `content` | Round summary |
| `grader` | `reasoning`, `done`, `round` | Goal completion check |
| `audio_chunk` | `agent_id`, `data` (base64 MP3) | TTS audio output |
| `transcription` | `text`, `final` | STT result |
| `partial_transcript` | `text` | Real-time STT partial |
| `error` | `message` | Error description |

---

## Voice Pipeline

```
Push-to-talk (spacebar)
    │
    ▼
Browser MediaRecorder → PCM 16kHz mono
    │
    ▼ WebSocket (audio_stream)
    │
ElevenLabs Realtime STT (scribe_v2_realtime)
    │
    ▼ transcription
    │
Oracle routes to agent(s)
    │
    ▼ Mistral streaming response
    │
ElevenLabs TTS WebSocket (eleven_flash_v2_5)
    │ Streams audio DURING text generation
    │ Per-agent voice, 1.15x speed
    │
    ▼ audio_chunk (base64 MP3)
    │
Browser plays audio
```

---

## Discord Integration

The same agents live in Discord as a bot (`Circles`):

- **Text channels** — agents respond as group participants, oracle-steered
- **Per-agent threads** — 1:1 DMs with individual agents
- **Slash commands:**
  - `/invite {agent}` — add agent to channel
  - `/dismiss {agent}` — remove agent from channel
  - `/call` — join voice channel, agents listen and speak
- **Voice channels** — real-time STT capture (48kHz→16kHz resample), TTS playback
- **File attachments** — uploaded files parsed and included in agent context

---

## Adding an Agent

1. Create `backend/agents/<id>.json`:

```json
{
    "id": "your-agent",
    "name": "Agent Name",
    "role": "Role Title",
    "bio": "Rich backstory...",
    "personality": "Behavioral traits...",
    "instructions": "System prompt for Mistral...",
    "model": "mistral-large-2512",
    "voice_id": "elevenlabs-voice-id",
    "tools": ["code_interpreter"]
}
```

2. Restart the backend — the registry auto-discovers and syncs to Mistral.

---

## Authorship

This project was **fully authored by AI agents**:

- **[Claude Code](https://claude.ai/claude-code)** (Anthropic) — primary coding agent. Wrote all backend code, frontend components, agent profiles, WebSocket protocol, oracle engine, voice pipeline, Discord integration, and documentation.
- **[OpenClaw](https://openclaw.ai)** orchestrator — coordinated multi-agent development workflow, managed iteration cycles (PM analysis → engineer review → implementation → QA), and directed architectural decisions.

Human contributors provided product vision, architectural direction, and real-time feedback. Every line of shipped code was generated by Claude Code under OpenClaw orchestration.

---

## License

Hackathon project — no license specified.
