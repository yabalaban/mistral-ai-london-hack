# Discord Frontend & Control Plane Review

**Branch**: `discord-frontend`
**Commits reviewed**:
1. `6b67c8b feat: Discord frontend with text, voice (ElevenLabs STT/TTS), webhook agent identities`
2. `a61cb93 feat: control plane — dynamic agent CRUD, oracle monitor sidebar, mute-to-commit voice`

**Reviewer**: Staff Engineer
**Date**: 2026-03-01

---

## 1. Architecture Summary

### What was added

The branch introduces two major capabilities:

**A. Discord Bot Frontend** -- A second frontend for the Ensemble platform that runs alongside (not instead of) the existing FastAPI + Preact web app. It surfaces the same agent ecosystem through Discord's UX primitives:

- **Text channels** act as group chat rooms with oracle-steered turn-taking.
- **Per-agent threads** auto-created off the channel, function as 1:1 DM sidebars and emulate a "member list."
- **Slash commands** (`/init`, `/invite`, `/dismiss`, `/agents`, `/who`, `/reset`, `/topic`, `/hangup`) for channel management.
- **Webhooks** give each agent a distinct identity (name, avatar) in Discord -- messages appear as if sent by different users.
- **Voice** -- bot joins voice channels, uses ElevenLabs realtime STT (mute-to-commit model), and plays back agent TTS via FFmpeg.

**B. Control Plane** -- Dynamic agent management and observability:

- **Agent CRUD** REST endpoints (`POST /api/agents`, `PATCH /api/agents/:id`, `DELETE /api/agents/:id`).
- **Frontend agent management** -- "Add Agent" modal with templates, delete button on agent cards.
- **OracleMonitor** sidebar component in group chat showing real-time oracle decision-making (goal, topic, rounds, speakers, verdicts, grader results, summary).

### Data Flow

```
Discord User Message
  -> CirclesBot.on_message()
  -> ChannelState (in-memory, per-channel)
  -> OracleEngine.run_group_turn_streaming() (same as web)
  -> WebhookManager.send_as_agent() (webhook per agent)
  -> Discord channel

Discord Voice
  -> py-cord Sink (48kHz stereo)
  -> _resample_48k_stereo_to_16k_mono()
  -> ElevenLabs RealtimeSTTSession
  -> on_user_mute -> commit -> final transcript
  -> OracleEngine.run_group_turn_streaming()
  -> ElevenLabs synthesize() -> FFmpegPCMAudio -> Discord voice
```

---

## 2. Discord Bot Analysis

### 2.1 Connection Model

The bot uses **py-cord** (`discord.Bot` from `py-cord`, not `discord.py`). This is important because py-cord has Sink/voice recording support that `discord.py` dropped. The bot connects to a single guild (specified by `DISCORD_GUILD_ID`). Intents required: `message_content`, `guilds`, `voice_states`.

### 2.2 Channel-to-Conversation Mapping

Each Discord text channel gets a `ChannelState` object stored in module-level dict `_channels: dict[int, ChannelState]`. The ChannelState holds:

- A `Conversation` object (group or direct depending on agent count)
- `agent_ids` -- which agents are active in this channel
- `agent_threads` -- maps `agent_id -> discord.Thread` for 1:1 sidebars
- `thread_to_agent` -- reverse lookup `thread_id -> agent_id`
- `agent_convs` -- separate `Conversation` per agent for 1:1 thread chats

This is a clean design. Each channel gets its own isolated conversation state.

### 2.3 Text Message Handling

The `on_message` handler:
1. Ignores bot messages and DMs
2. Detects thread messages (for 1:1) vs channel messages (for group)
3. For threads: looks up the agent via `thread_to_agent`, creates a per-agent `Conversation`, streams via `_stream_agent()`, sends via webhook
4. For channels: records user message in `conv.messages`, acquires a per-channel lock, runs `_run_group()` inside `channel.typing()` context

The group round uses `oracle.run_group_turn_streaming()` -- the same oracle as the web frontend. It only handles `"message"` and `"summary"` events, posting complete messages via webhooks and summaries as embeds.

### 2.4 Voice Pipeline

**Mute-to-commit model**: Users unmute to talk, mute to send. This maps PTT semantics onto Discord's native mute toggle -- creative and practical.

Voice flow:
1. `on_voice_state_update` auto-joins when a user enters a voice channel
2. Creates a `StreamingSink` that patches `Sink.write()` to resample and queue audio
3. `_feed_audio_loop()` reads from queue and sends to ElevenLabs STT
4. `_listen_transcripts()` waits for final transcripts
5. On mute: `on_user_mute()` calls `stt_session.commit()` to force finalization
6. Final transcript triggers `_respond()` which runs oracle and plays TTS

TTS playback uses `synthesize()` (batch, not streaming) -- generates full audio, writes to temp file, plays via `FFmpegPCMAudio`. This means the TTS is **not streaming** like the web frontend's `TTSWebSocket`. The trade-off is simplicity vs latency.

### 2.5 Webhook Identity System

`WebhookManager` creates one webhook per (channel, agent) pair, caches them, and sends messages with the agent's name + role as username and their avatar URL. This gives each agent a distinct identity in Discord -- a Discord-native approach that works well.

### 2.6 Oracle Integration

The Discord bot calls `oracle.run_group_turn_streaming()` the same way as the web WS handler. However, it only processes two event types (`"message"` and `"summary"`), ignoring:
- `oracle_start` / `oracle_end`
- `oracle` (reasoning/speakers)
- `turn_change`
- `chunk` (streaming text)
- `message_partial`
- `agent_cancel`
- `grader`
- `agent_verdict`
- `topic_set`

This is intentional -- Discord doesn't have a streaming text UI, so it waits for complete messages. But it means topic extraction results are silently dropped.

---

## 3. Control Plane Analysis

### 3.1 Agent CRUD

**New REST endpoints** in `routes.py`:

| Endpoint | Method | Purpose |
|---|---|---|
| `POST /api/agents` | Create | Creates agent from `CreateAgentRequest`, generates ID from name, syncs to Mistral |
| `DELETE /api/agents/:id` | Delete | Removes agent, cleans up Mistral agent |
| `PATCH /api/agents/:id` | Update | Partial update of agent properties |

**New `AgentRegistry` method**: `sync_single_to_mistral(agent_id)` -- identical logic to `sync_to_mistral()` but for a single agent.

**Frontend changes**:
- `client.ts` -- added `createAgent()`, `deleteAgent()`, `updateAgent()` API functions
- `RosterPage.tsx` -- "Add Agent" button opens `CreateAgentModal`, calls `createAgent()` API then adds to local signal
- `AgentCard.tsx` -- delete button (X icon) on hover, calls `deleteAgent()` API then filters from local signal
- `CreateAgentModal.tsx` -- two-step modal: pick from templates (4 built-in) or start blank, then customize name/role/bio/personality

### 3.2 OracleMonitor Component

New component at `frontend/src/components/oracle/OracleMonitor.tsx`. Renders a sidebar panel (hidden on small screens, visible on `lg:` breakpoints) inside `GroupPage.tsx`.

Displays:
- Active/inactive status indicator (green pulse when active)
- Directed message detection badge
- Current goal
- Current topic
- Per-round cards showing: round number, mode, reasoning (mono font), speaker list with status, verdict badges (color-coded), grader results
- Summary section

Reads from `oracleState` signal (already existed in `state/oracle.ts`). No new state was added -- it consumes existing signals that were already being populated by the WS event handlers.

The component is well-structured with clean Tailwind styling consistent with the glass morphism theme.

---

## 4. Code Quality Issues

### P0 -- Broken

#### D-001: `CreateAgentRequest` missing `instructions` field -- agents created via API have no system prompt
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/routes.py` lines 46-54, 66-75
**Description**: `CreateAgentRequest` does not include an `instructions` field. `AgentProfile` requires `instructions: str` (no default). When the route creates `AgentProfile(...)` on line 66-75, it does not pass `instructions`, which will raise a Pydantic `ValidationError`.
**Impact**: `POST /api/agents` will crash with a 500 error for every request.
**Suggested fix**: Either add `instructions: str = ""` to `CreateAgentRequest` and pass it through, or add a default value to `AgentProfile.instructions`, or auto-generate instructions from name/role/bio/personality.

#### D-002: `CreateAgentRequest` missing `model` field -- agents created via API always use the Pydantic default
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/routes.py` lines 46-54, 66-75
**Description**: `AgentProfile` has `model: str = "mistral-medium-latest"`, so this won't crash, but there's no way to specify a model through the API. This is P0 because without `instructions`, the agent creation crashes anyway, but if `instructions` is fixed with a default, the model issue becomes P2.
**Impact**: All dynamically created agents use `mistral-medium-latest` regardless of intent.
**Suggested fix**: Add `model: str = "mistral-medium-latest"` to `CreateAgentRequest`.

#### D-003: Registry `.agents` property returns a copy -- mutations in routes don't persist
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/agents/registry.py` line 37; `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/routes.py` lines 77, 104
**Description**: `AgentRegistry.agents` is a `@property` that returns `dict(self._agents)` -- a **shallow copy**. But `routes.py` does `_registry.agents[agent_id] = profile` (line 77) and `del _registry.agents[agent_id]` (line 104). These mutations operate on the copy, not the original `_agents` dict. The agent is never actually added to or removed from the registry.
**Impact**: Agent creation and deletion silently fail -- the API returns success but the agent doesn't actually exist in the registry. Subsequent requests to `/api/agents` won't show the created agent, and delete won't actually remove anything.
**Suggested fix**: Add explicit `add_agent(agent_id, profile)` and `remove_agent(agent_id)` methods to `AgentRegistry` that operate on `self._agents` directly. Or change the property to return the underlying dict (but this breaks encapsulation).

#### D-004: `PATCH /api/agents/:id` uses `CreateAgentRequest` which requires all fields
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/routes.py` lines 108-123
**Description**: The PATCH endpoint reuses `CreateAgentRequest` as its request body. `name: str` and `role: str` are required (no defaults). A PATCH request that only updates `bio` will fail with a 422 validation error because `name` and `role` are missing.
**Impact**: Partial updates don't work -- you must always send all fields, making it effectively a PUT.
**Suggested fix**: Create a separate `UpdateAgentRequest` model where all fields are optional: `name: str | None = None`, `role: str | None = None`, etc.

### P1 -- Incomplete

#### D-005: Discord voice only handles single user -- multi-user audio is mixed
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_voice.py` lines 57-68, 142-163
**Description**: The streaming sink receives `(user_id, pcm_data)` pairs, and the feed loop receives individual user chunks. However, the STT session receives all audio indiscriminately -- if multiple users talk, their audio is interleaved into the same STT stream without speaker diarization. The user_id is logged but not used for routing.
**Impact**: With multiple users in a voice channel, transcripts will be garbled or attributed to "the user" as a single speaker. The bot posts transcriptions with a generic microphone emoji rather than attributing to specific Discord users.
**Suggested fix**: For v1, document as a single-user-at-a-time limitation. For v2, consider per-user STT sessions or speaker diarization.

#### D-006: Discord bot doesn't handle `topic_set` events from oracle
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_bot.py` lines 443-467
**Description**: The `_run_group` method only handles `"message"` and `"summary"` event types from `oracle.run_group_turn_streaming()`. The `"topic_set"` event is silently dropped, so `conv.topic` is never updated for Discord channels (the oracle itself may set it internally, but the bot never reflects it).
**Impact**: `/topic` slash command works for manual topic setting, but oracle-inferred topics are lost. The channel state topic stays `None`.
**Suggested fix**: Add handling for `"topic_set"` event to update `state.conv.topic` and optionally post to channel.

#### D-007: No message length splitting for Discord's 2000-char limit
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_bot.py` lines 73-92
**Description**: `WebhookManager.send_as_agent()` sends the full `content` string in a single webhook message. Discord has a 2000-character limit per message. Agent responses (especially from code_interpreter or detailed analysis) can easily exceed this.
**Impact**: Long agent responses will fail with a Discord API 400 error. The error is caught by the outer try/except but the response is lost entirely.
**Suggested fix**: Split content into chunks of <= 2000 chars at sentence/paragraph boundaries before sending.

#### D-008: `audioop` is deprecated and removed in Python 3.13+
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_voice.py` line 12; `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/pyproject.toml` line 21
**Description**: The `audioop` module was deprecated in Python 3.11 and removed in Python 3.13. The `pyproject.toml` specifies `requires-python = ">=3.13"`, so `import audioop` will fail. However, the dependency `audioop-lts>=0.2.0` is included, which provides a backport. The import statement `import audioop` should work because `audioop-lts` installs itself as the `audioop` module. This needs verification that `audioop-lts` works correctly on the target Python version.
**Impact**: Potentially fails at import time if `audioop-lts` doesn't properly shim the module.
**Suggested fix**: Verify the import works on Python 3.14 (the version mentioned in MEMORY.md). If not, import directly from the `audioop-lts` package.

#### D-009: `_respond` uses `asyncio.create_task` without awaiting -- unhandled exceptions
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_voice.py` line 193
**Description**: `asyncio.create_task(self._respond(text))` is fire-and-forget. If `_respond` raises an exception, it becomes an unhandled task exception (only logged as a warning, not an error). The task reference is not stored, so it can be garbage collected.
**Impact**: Exceptions in agent responses may be silently swallowed. Multiple responses could run concurrently if the user commits multiple transcripts quickly, leading to interleaved oracle rounds.
**Suggested fix**: Store the task reference and cancel any previous response task before starting a new one (similar to how ws.py handles `group_task`).

#### D-010: Delete endpoint uses `_mistral_client.agents.delete_async` instead of `_mistral_client.beta.agents.delete_async`
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/routes.py` line 100
**Description**: The delete endpoint calls `_mistral_client.agents.delete_async(...)` but everywhere else in the codebase (registry.py line 127), the beta API is used: `_client.beta.agents.delete_async(...)`. Agents are created via `beta.agents.create_async`, so they should be deleted via `beta.agents.delete_async`.
**Impact**: Mistral agent cleanup fails silently (caught by `except Exception: pass`), leaving orphaned agents on the Mistral platform.
**Suggested fix**: Change to `await _mistral_client.beta.agents.delete_async(agent_id=agent.mistral_agent_id)`.

### P2 -- Inconsistent

#### D-011: Discord bot and web frontend maintain separate, unsynchronized state
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_bot.py` line 120; `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_main.py` lines 53-58
**Description**: The Discord bot creates its own `AgentRegistry`, `OracleEngine`, and `Mistral` client instances in `discord_main.py`. The web frontend has separate instances created in `main.py`'s lifespan. The docstring in `discord_main.py` line 9 says "Both frontends can run simultaneously -- they share no mutable state" and treats this as intentional. However, agents created via the web API won't appear in Discord, and vice versa. Conversation history is completely separate.
**Impact**: Not a bug per se (documented as intentional), but creates confusion if users expect unified state. Agents created dynamically via the control plane API are invisible to Discord.
**Suggested fix**: Document clearly that these are independent instances. For unification, either run both in the same process or use a shared state store.

#### D-012: `_get_state` creates new ChannelState with all agents by default
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_bot.py` lines 123-126
**Description**: Every channel gets all registered agents by default. The `_default_agents` list is set once at bot init time (line 158). If agents are added later (e.g., via a hypothetical API in the Discord process), they won't be in `_default_agents`.
**Impact**: Minor -- new channels always start with the initial agent set. `/invite` can add others. But it means all agents participate in every channel by default, which may be noisy.
**Suggested fix**: Consider starting channels with no agents (require `/init` or `/invite`) or making the default configurable.

#### D-013: PATCH endpoint can't clear optional fields back to empty
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/routes.py` lines 108-123
**Description**: The update logic uses `req.voice_id or agent.voice_id` -- this means you can never clear `voice_id` back to empty string, because `""` is falsy and the old value is preserved. Same for `bio`, `personality`, `avatar_url`.
**Impact**: Once set, optional fields can't be unset through the API.
**Suggested fix**: Use `None` as sentinel for "not provided" vs `""` for "explicitly empty". Or use a proper `UpdateAgentRequest` model where all fields are `Optional[str] = None`.

#### D-014: Frontend `CreateAgentModal` doesn't send `instructions` field
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/roster/CreateAgentModal.tsx` lines 67-78
**Description**: The `handleCreate` function constructs an agent object without an `instructions` field. Even if the backend is fixed to accept empty instructions, the modal provides no way to set system prompt instructions for the agent.
**Impact**: Dynamically created agents have no system prompt, making them generic and persona-less (only bio/personality is set via the registry sync, but the instructions field is the main behavior driver).
**Suggested fix**: Add a "System Instructions" textarea to the customize step, or auto-generate instructions from the other fields.

#### D-015: Agent `model` field not exposed in API response
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/routes.py` lines 126-138
**Description**: `_agent_to_dict()` doesn't include the `model` field in the response. Frontend can't display or select which Mistral model an agent uses.
**Impact**: No visibility into agent model configuration from the frontend.
**Suggested fix**: Add `"model": a.model` to the dict.

#### D-016: `sync_single_to_mistral` duplicates `sync_to_mistral` logic
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/agents/registry.py` lines 58-118
**Description**: `sync_single_to_mistral` (lines 92-118) is a near-exact copy of the per-agent logic in `sync_to_mistral` (lines 58-90). The only difference is it operates on a single agent. This is a DRY violation.
**Impact**: If the sync logic changes (e.g., adding new fields to the Mistral agent), it must be updated in two places.
**Suggested fix**: Extract the per-agent sync logic into a private method `_sync_agent(agent_id, profile)` and call it from both methods.

### P3 -- Cleanup

#### D-017: `struct` imported but unused in `discord_voice.py`
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_voice.py` line 15
**Description**: `import struct` is present but never used.
**Impact**: No functional impact, but ruff should catch this (`F401`).
**Suggested fix**: Remove the import.

#### D-018: `io` imported but unused in `discord_voice.py`
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_voice.py` line 14
**Description**: `import io` is present but never used.
**Impact**: No functional impact.
**Suggested fix**: Remove the import.

#### D-019: `struct` and `base64` imported but unused in `test_voice_e2e.py`
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/test_voice_e2e.py` lines 15-16
**Description**: Both `struct` and `base64` are imported at module level but only `base64` is used inside `test_stt` (which also has a local import of `subprocess`). `struct` is never used.
**Impact**: No functional impact.
**Suggested fix**: Remove unused `struct` import.

#### D-020: Hardcoded DiceBear avatar URLs in `discord_bot.py`
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_bot.py` lines 37-43
**Description**: `AGENT_AVATARS` hardcodes avatar URLs for 5 specific agents. This duplicates information that could come from `AgentProfile.avatar_url` or be generated dynamically.
**Impact**: Adding a new agent requires manually adding their avatar here. The `send_as_agent` method already falls back to `agent.avatar_url`, so this dict is only needed for agents without `avatar_url` set.
**Suggested fix**: Generate the DiceBear URL dynamically: `f"https://api.dicebear.com/9.x/personas/png?seed={agent.id}&size=256"` as a fallback when `avatar_url` is empty.

#### D-021: Test file location outside test directory
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/test_voice_e2e.py`
**Description**: The E2E test file is in `backend/` root rather than `backend/tests/`. It's also an integration test that requires live API keys and external services, not a unit test.
**Impact**: Won't be discovered by pytest with default test discovery (which looks in `tests/`). Though it's meant to be run manually.
**Suggested fix**: Move to `backend/tests/test_voice_e2e.py` or `backend/scripts/test_voice_e2e.py`.

#### D-022: Temp file cleanup not guaranteed in `_play_agent_tts`
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_voice.py` lines 242-262
**Description**: If `self._vc.play(source, after=after_play)` raises an exception before the callback runs, the temp file is never cleaned up. The `after_play` callback handles cleanup, but only if playback starts successfully.
**Impact**: Temp file leak on playback errors. Minor since this is mp3 files that are small.
**Suggested fix**: Wrap in try/except and ensure `Path(tmp.name).unlink(missing_ok=True)` in the exception handler.

---

## 5. Integration Concerns

### 5.1 State Sharing Between Discord and Web

**They don't share state.** Each frontend creates its own `AgentRegistry`, `Mistral` client, and `OracleEngine`. This means:
- Agents created via the web control plane API don't appear in Discord
- Conversations are completely separate
- Mistral agents are created twice (once per process), doubling API usage
- If both processes load the same JSON profiles, they create duplicate Mistral agents

This is documented as intentional in `discord_main.py`, but the control plane feature (dynamic agent CRUD) makes this a more pressing issue -- creating an agent via the web API and expecting it in Discord won't work.

### 5.2 Race Conditions

Within the Discord bot, the per-channel `asyncio.Lock` (line 372-376) prevents concurrent group rounds in the same channel. This is correct.

However, `_handle_thread_message` (1:1 conversations) has no such lock. If a user sends messages rapidly in an agent thread, multiple Mistral streaming calls could race on the same conversation, potentially hitting 409 Conflicts. The retry logic handles this, but it's wasteful.

The `DiscordVoiceHandler` has a `_playing_lock` for TTS playback serialization, which is correct.

### 5.3 Oracle Engine Compatibility

The Discord bot uses the same `oracle.run_group_turn_streaming()` method as the web frontend. The oracle works identically. The difference is that Discord only processes complete messages (not streaming chunks), which is fine for Discord's message model.

One notable difference: the Discord bot passes `voice_mode=True` to the oracle for voice responses (line 210 in `discord_voice.py`), which adds the voice-mode brevity prefix. The text channel group round does not use voice_mode (line 443 in `discord_bot.py`), which is correct.

### 5.4 Missing Features

Compared to the web frontend, the Discord bot lacks:

| Feature | Web | Discord |
|---|---|---|
| Streaming text (typing indicator) | Yes | Shows "typing..." but posts complete message |
| Oracle reasoning visibility | OracleMonitor sidebar | Not shown |
| Image attachments | Full support | Extracts image URLs from Discord attachments |
| Function calls / tool results | Handled by `_handle_function_calls` | Not handled -- `_stream_agent` in discord_bot doesn't check for function calls |
| Reply threading (in-reply-to) | `reply_to_id` tracked | Not implemented |
| Interruption / cancel | User can send new message to cancel | No interruption mechanism |
| Agent `[PASS]` transparency | Shown as verdict | Not shown |

The function call omission (D-023 below) is particularly notable for agents with `code_interpreter` or `create_slides` tools.

### 5.5 Missing Function Call Handling

#### D-023: Discord bot `_stream_agent` doesn't handle function calls
**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_bot.py` lines 471-514
**Description**: The `_stream_agent` method streams text from Mistral but never checks for `FunctionCallEvent`. The web WS handler (`ws.py` line 976) detects function calls and falls back to non-streaming `_handle_function_calls`. The Discord bot will receive the function call event, ignore it, and return partial or empty text.
**Impact**: Agents with tools (code_interpreter, web_search, slides) will produce incomplete or empty responses when they want to use tools.
**Suggested fix**: Add function call detection and handling similar to `_stream_agent_response` in ws.py.

---

## 6. Dependencies & Configuration

### 6.1 New Dependencies

| Package | Version | Purpose |
|---|---|---|
| `py-cord[voice]` | `>=2.6.0` | Discord bot framework with voice support |
| `PyNaCl` | `>=1.5.0` | Required by py-cord for voice encryption |
| `audioop-lts` | `>=0.2.0` | Backport of deprecated `audioop` module for Python 3.13+ |

py-cord is a fork of discord.py with continued voice/Sink support. The `[voice]` extra installs `PyNaCl`, `ffmpeg` (system dependency), and voice-related deps.

**Note**: py-cord and discord.py conflict -- they both install as the `discord` package. If anyone has `discord.py` installed in their environment, it will break. This should be documented.

### 6.2 New Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `DISCORD_BOT_TOKEN` | For Discord bot | Discord bot token from Developer Portal |
| `DISCORD_GUILD_ID` | For Discord bot | Target guild/server ID |
| `MISTRAL_API_KEY` | Already required | Used by both frontends |
| `ELEVENLABS_API_KEY` | For voice | Used by both frontends |

These are not added to `config.py` `Settings` -- they're read directly via `os.environ.get()` in `discord_main.py`. This is inconsistent with the rest of the app's configuration pattern.

### 6.3 Security Concerns

- **Discord bot token**: Read from environment, not logged. Good.
- **ElevenLabs API key**: Sent over WebSocket in TTS init message (line 100 in tts.py, existing code). This is the documented ElevenLabs approach but worth noting.
- **Webhook creation**: The bot creates webhooks in Discord channels. These webhooks have URLs that could be used by anyone to post messages. The webhook names are predictable (`circles-{agent_id}`). This is standard Discord bot behavior but the webhooks persist even after the bot leaves.
- **No authentication on REST API**: The agent CRUD endpoints have no auth. Anyone can create/delete agents. This was true before this branch too, but the new endpoints make it more impactful.

---

## 7. Merge Readiness

### Must Fix Before Merge (P0)

1. **D-001**: `CreateAgentRequest` missing `instructions` -- agent creation crashes
2. **D-003**: Registry `.agents` property returns copy -- CRUD mutations are no-ops
3. **D-004**: PATCH endpoint reuses create request model -- partial updates fail
4. **D-010**: Wrong Mistral API path for delete (`agents` vs `beta.agents`)

### Should Fix Before Merge (P1)

5. **D-007**: Discord message length splitting (2000-char limit)
6. **D-009**: Fire-and-forget response task in voice handler
7. **D-023**: Missing function call handling in Discord bot

### Can Defer

- **D-005**: Multi-user voice (document as limitation)
- **D-006**: Oracle `topic_set` handling in Discord
- **D-008**: `audioop-lts` verification (likely works, just verify)
- **D-011**: State sharing between frontends (intentional design)
- **D-012**: Default agents per channel (minor UX)
- **D-013**: PATCH field clearing semantics
- **D-014**: Missing instructions textarea in frontend modal
- **D-015-D-022**: All P2/P3 items

### Conflict Risk with Main

The branch modifies several files that also have changes on main (per git status):
- `backend/src/ensemble/agents/registry.py` -- new `sync_single_to_mistral` method added
- `backend/src/ensemble/api/routes.py` -- new CRUD endpoints added
- `backend/src/ensemble/voice/stt.py` -- `RealtimeSTTSession.__init__` signature changed (`auto_commit` parameter added)
- `backend/pyproject.toml` -- new dependencies added
- `frontend/src/api/client.ts` -- new API functions added
- `frontend/src/components/group/GroupPage.tsx` -- OracleMonitor sidebar added
- `frontend/src/components/roster/RosterPage.tsx` -- Create agent button added
- `frontend/src/components/roster/AgentCard.tsx` -- Delete button added (new file on this branch)

The `stt.py` change is the most conflict-prone since the constructor signature has been modified. The rest are additive changes that should merge cleanly.

### Summary

The Discord frontend is a solid proof-of-concept with a clean architecture -- the channel/thread mapping is well thought out, webhooks for agent identity are the right Discord-native approach, and the mute-to-commit voice model is creative. The control plane CRUD has critical implementation bugs (P0s) that make it non-functional, but they're straightforward fixes. The OracleMonitor component is clean and integrates well.

**Recommendation**: Fix the four P0 issues and the three critical P1 issues, then merge. The remaining items can be tracked as follow-up work.
