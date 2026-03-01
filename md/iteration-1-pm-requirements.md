# Circles (Ensemble) -- Inferred Requirements Document

Generated from full codebase analysis. Intended audience: Staff Engineer reviewing for correctness.

---

## 1. Product Overview

Circles is a multi-agent chat platform providing a Discord-like experience where AI agents powered by Mistral are first-class participants. A single human user can:

- Browse a roster of AI agents with distinct personalities, roles, and capabilities
- Engage in 1:1 direct message conversations with any agent
- Create group conversations with 2+ agents, orchestrated by an invisible "oracle" that controls turn-taking
- Initiate voice calls (push-to-talk) in both 1:1 and group contexts, with real-time STT (ElevenLabs) and per-agent TTS (ElevenLabs)
- Attach images to messages for multimodal reasoning
- Trigger agent tool use (code interpreter, web search, image generation, slide creation)

All state is in-memory. There is no authentication; a single user is assumed.

---

## 2. User Journeys

### Journey 1: Browse Agents and Start 1:1 Chat
1. User opens the app at `/` (RosterPage)
2. `useAgents` hook fetches all agents from `GET /api/agents`
3. For each agent, a direct conversation is auto-created via `POST /api/conversations` with `type: "direct"` and `participants: [agent.id]`
4. Conversations appear in the Sidebar; agent cards appear on the RosterPage
5. User clicks an agent card or sidebar entry, navigating to `/chat/:convId`
6. `useConversation` hook sets `activeConversationId`, fetches conversation data if needed, connects WebSocket to `/ws/conversations/:id`
7. User types a message in ChatInput, presses Enter
8. Message is optimistically appended to local state (with client-generated ID)
9. Message is sent via WebSocket `{ type: "message", id, content, attachments }`
10. Backend records user message, streams agent response via Mistral `start_stream_async` / `append_stream_async`
11. Frontend receives `turn_change` (typing indicator), then `message_chunk` events (ignored in state; typing indicator suffices), then `message_complete` (final message committed to state)
12. Agent response appears in MessageList

### Journey 2: Create a Group Chat and Discuss
1. User clicks "New Group Chat" button on RosterPage or Sidebar
2. NewGroupModal opens; user selects 2+ agents
3. `POST /api/conversations` with `type: "group"` and `participants: [agent_ids]` creates the group
4. User navigates to `/group/:convId`
5. WebSocket connects; user sends a message
6. Backend WS handler spawns `_handle_group_streaming` as a background task
7. Oracle engine runs `run_group_turn_streaming`:
   a. Topic grading: if no topic set, oracle classifies user messages to extract one
   b. Directed message detection: checks if user addressed an agent by name
   c. If directed: single agent responds, skip ranking/grading
   d. If not directed: classify message as "parallel" or "sequential", infer goal
   e. Rank agents by relevance via LLM call
   f. Run agents (parallel: all at once; sequential: one-by-one seeing prior replies)
   g. Grade completion against inferred goal
   h. Loop rounds (up to 10) until grader says done
   i. Generate summary if 2+ agents spoke
8. Frontend receives and displays: `oracle_start`, `oracle_reasoning`, `turn_change`, `message_chunk`, `message_partial` (voice), `message_complete`, `agent_verdict`, `grader`, `summary`, `oracle_end`
9. Oracle panel (GroupMessages) shows round details, verdicts, grader reasoning

### Journey 3: Voice Call (1:1)
1. User clicks call button in ChatPage header
2. `POST /api/conversations/:id/call` creates a call record
3. Frontend sets `activeCall` signal, switches `callMode` to "voice"
4. CallControls appear with PTT (push-to-talk) button
5. User holds spacebar or pointer-down on PTT button
6. `useVoice.startPTT()` sends `{ type: "voice_state", active: true }` via WS
7. Backend creates `VoiceSession`, opens ElevenLabs Realtime STT session
8. Browser captures mic audio via `ScriptProcessorNode`, downsamples to 16kHz PCM, base64-encodes, sends `{ type: "audio_stream", data }` via WS
9. Backend feeds audio to STT session
10. Partial transcripts sent to frontend as `partial_transcript` events
11. User releases PTT: `{ type: "voice_state", active: false }`
12. Backend commits STT, gets final transcript, sends `transcription` event
13. Backend streams agent response through Mistral + TTS (ElevenLabs WebSocket streaming)
14. Audio chunks sent as `audio_chunk` events; frontend enqueues for sequential playback
15. `message_complete` and `agent_done` events finalize the turn

### Journey 4: Voice Call (Group)
1. Same call initiation as Journey 3
2. On committed transcript, `_group_voice_response` runs oracle orchestration with `voice_mode=True`
3. For each agent turn: TTS WebSocket opens per-agent, text chunks feed directly to TTS as they stream from Mistral
4. Audio streams to client concurrently with text generation (low-latency pipeline)
5. Sentence-level interruption checks: after every 2 sentences, oracle decides if speaker should be interrupted
6. If interrupted: TTS cancelled, `agent_interrupted` event sent, text trimmed to last sentence boundary
7. TTS drain moved to background task so oracle can decide next speaker concurrently

### Journey 5: Custom Agent Creation
1. User clicks "Add Agent" on RosterPage
2. CreateAgentModal opens with form fields (name, role, bio, personality, instructions, model, tools)
3. On submit, new agent is added to the frontend `agents` signal
4. Note: No backend endpoint exists for runtime agent creation; the agent is client-side only unless manually added as a JSON file and backend restarted

### Journey 6: Image Attachment
1. User clicks image upload button in ChatInput
2. ImageUpload component handles file selection, converts to base64 data URL
3. Attachment appears as thumbnail preview with remove button
4. On send, message includes `attachments: [{ type: "image", url: "data:..." }]`
5. Backend builds multimodal Mistral input with `image_url` content blocks
6. Agent processes image via Mistral vision capabilities

### Journey 7: Slide Generation
1. User sends a message to Kim (PA agent) requesting slides
2. Kim's Mistral agent calls the `create_slides` function tool
3. Backend detects `FunctionCallEvent`, executes `create_slides` handler
4. Handler renders Reveal.js HTML, generates PDF via Playwright
5. Returns `{ presentation_id, url, pdf_url, message }` to Mistral
6. Kim responds with the presentation URL
7. User can view slides at `/api/slides/:id` or download PDF at `/api/slides/:id/pdf`

---

## 3. Business Invariants

### Agent Integrity
1. Every agent message (`role: "agent"`) MUST have a non-null `agent_id` that corresponds to a registered agent in the AgentRegistry.
2. An agent MUST have a non-null `mistral_agent_id` (synced to Mistral) before it can respond to messages. The `ready` flag in the API response reflects this.
3. Agent profiles are immutable after loading -- the registry does not support runtime updates to agent JSON profiles.
4. Agent IDs are unique. Duplicate IDs in JSON files are handled by last-write-wins during `load_profiles` (sorted glob order).

### Conversation Constraints
5. A `direct` conversation MUST have exactly 1 participant agent ID. Enforced by `ConversationManager.create()`.
6. A `group` conversation MUST have at least 2 participant agent IDs. Enforced by `ConversationManager.create()`.
7. All participant agent IDs MUST refer to agents that exist in the registry. Validated at creation time.
8. Every conversation has a unique auto-generated UUID hex ID.
9. Group messages MUST be sent via WebSocket, not via REST `POST /conversations/:id/messages`. REST raises 400 for group conversations.

### Oracle Invariants
10. The oracle MUST select agents only from the conversation's `participant_agent_ids` list.
11. At least one agent MUST respond per oracle round. If the ranker returns no responders, all agents are included as fallback.
12. The oracle MUST cap rounds at `MAX_ROUNDS = 10` to prevent infinite loops.
13. A directed message (user addresses an agent by name) bypasses classification, ranking, and grading -- the addressed agent responds directly.
14. In voice mode, classification is forced to "sequential" regardless of the classifier's output.
15. Agents can `[PASS]` to decline responding. A pass is NOT recorded as a message in the conversation; it only emits an `agent_verdict` with verdict "passed".

### Message Integrity
16. User messages use client-provided IDs when sent via WebSocket (for optimistic UI consistency). The backend respects `msg.get("id")` from the client payload.
17. The `reply_to_id` field on agent messages references the `id` of the message being replied to. This forms a threading chain.
18. Message roles in the backend are `user` or `agent`. The REST API serializes `agent` as `assistant` for frontend compatibility.

### Voice Invariants
19. PTT (push-to-talk) is the only voice input mode. There is no always-on voice activity detection.
20. STT uses `CommitStrategy.MANUAL` -- the transcript is committed only when PTT is released.
21. If the STT commit times out (< 0.3s audio, ElevenLabs throttle), the system falls back to the last partial transcript if it has more than 2 characters.
22. TTS streams audio concurrently with text generation. Text chunks are fed to ElevenLabs as they arrive from Mistral.

### State
23. All state is in-memory. A server restart clears all conversations, messages, and Mistral conversation contexts.
24. Mistral agents are deleted from the Mistral platform on server shutdown via `cleanup_mistral()`.

---

## 4. Feature Behavioral Contracts

### 4.1 Agent Roster and Profiles

**What it promises**: Users can view all registered agents with their name, role, bio, personality, avatar, voice ID, and tool capabilities.

**Trigger conditions**: Navigating to `/` (RosterPage) or app startup (Shell loads `useAgents`).

**Success criteria**: `GET /api/agents` returns an array of agent objects. Each agent has `ready: true` if synced to Mistral. Frontend renders agent cards in a responsive grid.

**Error handling**: If `fetchAgents()` fails, frontend falls back to mock agents. Agent profiles that fail to load from JSON are logged and skipped. Agents that fail Mistral sync have `mistral_agent_id = None` and `ready = false`.

### 4.2 1:1 Direct Conversations

**What it promises**: User sends a text message; the agent responds with a streamed reply. Each agent maintains persistent Mistral conversation context across messages.

**Trigger conditions**: User sends a message via WebSocket `{ type: "message" }` in a direct conversation.

**Success criteria**:
- User message recorded in `conv.messages`
- `turn_change` event sent (typing indicator)
- Agent response streamed via `message_chunk` events
- `message_complete` event sent with final content
- Agent message recorded in `conv.messages`
- Mistral conversation ID stored in `conv.mistral_conversation_ids[agent_id]`

**Error handling**:
- If agent not ready (no `mistral_agent_id`): sends `error` event "Agent {id} not ready"
- If streaming fails: logs exception, sends `error` event "Agent response failed"
- Function call detection: if `FunctionCallEvent` detected during streaming, falls back to non-streaming `append_async`, handles tool execution, returns tool result

### 4.3 Group Conversations with Oracle

**What it promises**: Multiple agents respond to user messages with intelligent turn-taking. The oracle classifies messages, ranks agents by relevance, orchestrates response order, and grades completion.

**Trigger conditions**: User sends a message via WebSocket in a group conversation.

**Success criteria**:
- Topic extracted and set if not already present
- Message classified as parallel or sequential
- Agents ranked and filtered by relevance
- Responses streamed with proper threading (`reply_to_id`)
- Completion graded against inferred goal
- Summary generated if 2+ agents spoke
- All oracle state communicated to frontend via events

**Error handling**:
- Classifier failure: defaults to "sequential" mode
- Ranker failure: includes all agents as fallback
- Grader failure: defaults to done=true, ending the round
- Summary failure: logged, no summary emitted
- Individual agent streaming failure: logged, skipped, continues with remaining agents
- Active group round interrupted by new user message: `group_task.cancel()`, `interrupt` event sent

### 4.4 Oracle Turn-Taking Pipeline

**Classify**: `classify_message(content)` -> `(mode, goal)`
- Uses `oracle_model` (ministral-14b-2512) with JSON response format
- Returns "parallel" for casual/social messages, "sequential" for substantive
- Infers a concise, evaluable goal from the user message
- Fallback: "sequential" mode, generic goal

**Rank**: `rank_agents(content, conversation, agent_ids, last_speaker)`
- Classifies message as "generic" (all respond) or "specialised" (filtered)
- Returns ordered list with `should_respond` boolean and `hint` per agent
- Validates: only known agent IDs kept; ensures at least one responder
- Hints are short (3-5 words) guiding each agent's angle

**Execute (Parallel)**: `_run_parallel()`
- All ranked agents run concurrently via `asyncio.create_task`
- Each agent streams to a shared queue
- Results yielded as they complete (non-deterministic order)
- Agents can [PASS]

**Execute (Sequential)**: `_run_sequential()`
- Agents respond one-by-one in ranked order
- Each agent's prompt is rebuilt to include prior agents' responses
- Sentence-level interruption checks in voice mode (every 2 sentences after reaching 2+)
- Interrupted agent's text trimmed to last sentence boundary

**Grade**: `grade_completion(conversation, user_message, goal, mode)`
- Evaluates all messages against the inferred goal
- Parallel mode: typically done after one round
- Sequential mode: checks if goal substantially met
- Skipped on the final allowed round (MAX_ROUNDS - 1)
- After parallel round, mode switches to sequential for follow-ups

**Summary**: `_generate_summary(conversation, speakers)`
- Generated when 2+ agents spoke
- 2-3 bullet points: key decisions, disagreements, action items
- Stored in `conversation.last_summary` for use in subsequent rounds

### 4.5 Directed Messages in Groups

**What it promises**: When a user addresses an agent by name ("Sofia, can you..."), only that agent responds, bypassing the full oracle pipeline.

**Trigger conditions**: `_detect_directed_message()` checks if the message starts with or contains an agent's name (case-insensitive) in patterns:
- `"{name}..."` (starts with name)
- `"hey {name}..."` (starts with "hey" + name)
- `"{name},"` or `"{name}:"` (name followed by comma or colon anywhere)

**Success criteria**: Single agent responds. Oracle emits `oracle_start` with `directed: true`, followed by `turn_change`, streaming, `message_complete`, `oracle_end`. No ranking, no grading, no summary.

**Error handling**: If the directed agent is not ready (no `mistral_agent_id`), the directed shortcut is skipped and falls through to the normal oracle pipeline.

### 4.6 Reply Threading in Groups

**What it promises**: Agents can reply to specific messages using `[N]` prefix notation. The numeric index maps to a message in the current round's history.

**Trigger conditions**: Agent output starts with `[N]` (e.g., `[1]`, `[3]`).

**Success criteria**:
- `_parse_reply_target()` extracts the numeric index and maps it to a real message ID via `index_map`
- The `[N]` prefix is stripped from the displayed content
- `reply_to_id` is set on the resulting Message and communicated to the frontend
- Frontend MessageBubble renders the reply context (quoted snippet of the referenced message)

**Error handling**: If the index doesn't map to a known message ID, `reply_to_id` remains the default (user message ID or previous agent's message ID). The prefix is still stripped.

### 4.7 Voice Calls (PTT, STT, TTS)

**What it promises**: Push-to-talk voice input with real-time transcription and per-agent voice synthesis.

**Trigger conditions**:
- Call started via `POST /api/conversations/:id/call` or `{ type: "start_call" }` WS event
- PTT activated via spacebar (not in input field) or pointer events on PTT button
- PTT sends `{ type: "voice_state", active: true/false }` via WS

**Success criteria**:
- Mic captured at browser sample rate, downsampled to 16kHz mono PCM
- Audio chunks streamed as base64 via `{ type: "audio_stream", data }`
- Backend opens ElevenLabs Realtime STT session per PTT press
- Partial transcripts displayed in real-time
- On PTT release: STT committed, final transcript triggers agent response
- Agent text streamed through Mistral, fed chunk-by-chunk to ElevenLabs TTS WebSocket (Flash v2.5)
- Audio chunks (MP3 22050Hz 32kbps) sent to frontend as base64
- Frontend enqueues audio buffers for gapless sequential playback via Web Audio API
- `agent_speaking` / `agent_done` events control visual indicators

**Error handling**:
- Mic access denied: logged, PTT silently fails
- STT commit timeout (3s): falls back to `last_partial_text` if > 2 chars
- TTS connection closed: logged, warning level
- Mistral 409 Conflict (conversation lock): retries up to 3 times with exponential delay (1s, 2s, 3s)
- On call end: `teardownMic()` stops all tracks, `VoiceSession.stop()` closes STT/TTS

### 4.8 Voice in Group Calls

**What it promises**: Oracle-orchestrated group voice with concurrent text generation and TTS streaming per agent.

**Trigger conditions**: Committed transcript in a group voice session.

**Success criteria**:
- Oracle runs with `voice_mode=True` (forces sequential mode)
- Per-agent TTS WebSocket opened at `turn_change`
- Text chunks fed to TTS during streaming (audio starts before text completes)
- TTS drain moved to background after agent finishes (non-blocking for next speaker decision)
- Drain awaited before opening next agent's TTS (prevents audio overlap)

**Error handling**:
- Interruption: TTS cancelled, audio task cancelled, `agent_interrupted` event sent
- Remaining TTS connections cleaned up in finally block
- Previous drain tasks awaited before cleanup

### 4.9 Tool Execution

**What it promises**: Agents can invoke tools during conversations. Tool results are fed back to Mistral for the agent to incorporate in its response.

**Trigger conditions**: Mistral response contains a `FunctionCallEvent`.

**Tools available**:
- `code_interpreter`: Mistral-native CodeInterpreterTool (executed server-side by Mistral)
- `web_search`: Mistral-native WebSearchTool
- `image_generation`: Mistral-native ImageGenerationTool
- `create_slides`: Custom FunctionTool with local handler

**Success criteria (create_slides)**:
- Agent calls `create_slides(title, slides, author?)
- Reveal.js HTML rendered with title slide, content slides, "Thank You" slide
- PDF generated via Playwright headless Chromium
- Both stored in memory; URLs returned to agent
- Agent includes URLs in response

**Error handling**:
- Unknown tool: returns `{ "error": "Unknown tool: {name}" }`
- Tool execution failure: returns `{ "error": "Tool {name} failed" }`, logged
- Max 3 rounds of chained tool calls to prevent infinite loops
- In streaming path: function calls cause fallback to non-streaming `append_async` with "Please proceed with the tool call."

### 4.10 Image Attachments

**What it promises**: Users can attach images to messages. Images are sent to Mistral as base64 data URLs for multimodal processing.

**Trigger conditions**: User selects an image via ImageUpload component or REST multipart endpoint.

**Success criteria**:
- Image converted to base64 data URL in browser
- Attachment included in WS message payload
- Backend constructs multimodal content blocks: `[{ type: "text", text }, { type: "image_url", image_url: { url } }]`
- Mistral processes image with vision capabilities
- Image displayed in MessageBubble

**Error handling**: Invalid base64 or missing data handled gracefully by Mistral API error responses.

### 4.11 Agent Creation (Custom Agents)

**What it promises**: Users can create custom agents via a modal form.

**Trigger conditions**: User clicks "Add Agent" on RosterPage.

**Success criteria**: New agent added to frontend `agents` signal. Agent card appears in roster.

**Error handling**: This is frontend-only. The agent is NOT synced to Mistral, NOT persisted, and CANNOT participate in conversations until manually added to `backend/agents/` and the server is restarted. This is a known limitation.

### 4.12 Group Creation

**What it promises**: Users can create group conversations with 2+ selected agents.

**Trigger conditions**: User clicks "New Group Chat" in RosterPage or Sidebar, selects agents, confirms.

**Success criteria**: `POST /api/conversations` with `type: "group"`, `participants: [agent_ids]` succeeds. New conversation appears in sidebar. User navigated to `/group/:id`.

**Error handling**: Backend validates participant count (min 2) and agent existence. Returns 400 with descriptive error on validation failure.

### 4.13 Streaming and Optimistic UI

**What it promises**: User messages appear immediately in the UI before server confirmation. Agent responses stream incrementally.

**Trigger conditions**: Any message send.

**Success criteria**:
- User message appended to local state with client-generated ID before WebSocket send
- `turn_change` event triggers typing indicator (agent avatar + "is typing" text with dot-pulse animation)
- `message_chunk` events arrive but are NOT individually rendered in the message list (typing indicator suffices)
- `message_complete` event commits the final message to conversation state and removes typing indicator
- In voice mode: `message_partial` events update visible message content at sentence boundaries

**Error handling**: If WS is not open, send is dropped with console warning. WS auto-reconnects on disconnect (2s delay) unless close code is 4004 (conversation not found).

### 4.14 WebSocket Protocol

**What it promises**: Bidirectional real-time communication between frontend and backend for all conversation interactions.

**Client -> Server events**:
| Type | Payload | Purpose |
|------|---------|---------|
| `message` | `content`, `id?`, `attachments?[]` | Send text/multimodal message |
| `audio` | `data` (base64 WAV) | Legacy batch audio input |
| `voice_state` | `active` (boolean) | PTT press/release |
| `audio_stream` | `data` (base64 PCM 16kHz) | Streaming audio chunks |
| `start_call` | `mode` (text/voice) | Start a call |
| `end_call` | -- | End a call |

**Server -> Client events**:
| Type | Payload | Purpose |
|------|---------|---------|
| `message_chunk` | `agent_id`, `content`, `message_id` | Streaming text chunk |
| `message_complete` | `message` object | Final message |
| `message_partial` | `message` object | Partial message (voice, sentence boundaries) |
| `turn_change` | `agent_id`, `reply_to_id?` | Next speaker indicator |
| `oracle_start` | `directed`, `directed_agent?`, `goal?` | Oracle round beginning |
| `oracle_end` | -- | Oracle round complete |
| `oracle_reasoning` | `reasoning`, `speakers[]`, `round`, `mode` | Agent ranking results |
| `topic_set` | `topic` | Thread topic extracted |
| `grader` | `reasoning`, `done`, `round` | Completion grading result |
| `agent_verdict` | `agent_id`, `agent_name`, `verdict` | Agent response outcome |
| `summary` | `content` | Round summary |
| `call_started` | `call` object | Call initiated |
| `call_ended` | `call_id` | Call terminated |
| `audio_chunk` | `agent_id`, `data` (base64 MP3) | TTS audio output |
| `transcription` | `text`, `final?` | STT committed transcript |
| `partial_transcript` | `text` | STT partial (real-time) |
| `agent_speaking` | `agent_id` | Agent voice turn started |
| `agent_done` | `agent_id` | Agent voice turn completed |
| `interrupt` | -- | User interrupted (new message) |
| `agent_interrupted` | `agent_id`, `by` | Agent interrupted by oracle |
| `error` | `message` | Error description |

**Connection lifecycle**:
- Frontend connects to `/ws/conversations/:id`
- If conversation not found: error event sent, WebSocket closed with code 4004
- Auto-reconnect on unexpected close (2s delay), except code 4004
- On disconnect: backend cancels any active group task, stops voice session, removes from connection manager

### 4.15 Mobile Responsiveness

**What it promises**: The app is usable on mobile devices with an adaptive layout.

**Trigger conditions**: Viewport width below `md` breakpoint (768px).

**Success criteria**:
- Sidebar hidden by default on mobile, toggleable via hamburger menu in Header
- Sidebar slides in as fixed overlay with backdrop on mobile
- Agent profile panel hidden on mobile (`hidden md:flex`)
- Oracle panel (GroupMessages) hidden on mobile (`hidden md:flex`)
- Grid layout responsive: 1 column on mobile, 2 on sm, 3 on lg
- Touch-friendly PTT button (pointer events)

**Error handling**: Sidebar backdrop click dismisses sidebar. Navigation links dismiss sidebar.

### 4.16 Artificial Response Delay

**What it promises**: `message_complete` events are delayed proportionally to content length to simulate natural reading/speaking pace.

**Trigger conditions**: Every `message_complete` WebSocket send from backend.

**Success criteria**: Delay = `min(max(len(content) * 0.004, 0.5), 2.5)` seconds. Range: 0.5s to 2.5s.

**Error handling**: None. This is a cosmetic feature.

---

## 5. Data Model Contracts

### AgentProfile (Backend, Pydantic)
- `id: str` -- Unique identifier, matches JSON filename (e.g., "emma")
- `name: str` -- Display name
- `role: str` -- Short role description
- `bio: str` -- Longer biography
- `personality: str` -- Personality traits
- `instructions: str` -- System prompt for Mistral
- `voice_id: str = ""` -- ElevenLabs voice ID (optional)
- `model: str = "mistral-medium-latest"` -- Mistral model
- `tools: list[str] = []` -- Tool names from BUILT_IN_TOOLS
- `avatar_url: str = ""` -- Avatar image URL (optional)
- `mistral_agent_id: str | None = None` -- Set after Mistral sync

**Contract**: Instructions sent to Mistral are augmented: `[Identity], [Bio], [Personality]` prepended to raw instructions.

### Agent (Frontend, TypeScript)
- `id, name, role, bio, avatar, personality: string`
- `voice_id?: string`
- `tools?: string[]`

**Contract**: Backend serializes `avatar_url` as both `avatar` and `avatar_url` for frontend compatibility. The `ready` field indicates Mistral sync status.

### Conversation (Backend, Pydantic)
- `id: str` -- Auto-generated UUID hex
- `type: ConversationType` -- "direct" or "group"
- `participant_agent_ids: list[str]` -- Agent IDs participating
- `messages: list[Message]` -- Full message history (grows unboundedly)
- `mistral_conversation_ids: dict[str, str]` -- Maps agent_id -> Mistral conversation ID
- `topic: str | None` -- Thread topic, set by oracle topic grading
- `last_summary: str | None` -- Summary of prior turns (used in agent prompts)
- `created_at: datetime` -- UTC creation timestamp

**Contract**: Each agent has its own independent Mistral conversation context within a group. The oracle builds context prompts that include other agents' messages so each agent "sees" the full thread despite having separate Mistral conversations.

### Conversation (Frontend, TypeScript)
- `id, type, created_at: string`
- `participants: string[]`
- `messages: Message[]`
- `topic?: string | null`

### Message (Backend, Pydantic)
- `id: str` -- Auto-generated 12-char UUID hex
- `role: MessageRole` -- "user" or "agent"
- `agent_id: str | None` -- Which agent sent it (None for user messages)
- `content: str` -- Text content
- `attachments: list[Attachment]` -- Image attachments
- `reply_to_id: str | None` -- Message being replied to
- `timestamp: datetime` -- UTC timestamp

**Contract**: Backend uses `agent` role; REST API serializes as `assistant` for frontend compatibility.

### Message (Frontend, TypeScript)
- `id, content, timestamp: string`
- `role: 'user' | 'assistant' | 'system'`
- `agent_id?: string`
- `attachments?: Attachment[]`
- `reply_to_id?: string`

**Contract**: `system` role messages are rendered as centered, italicized notes (e.g., interruption notices).

### Attachment
- `type: str` -- Currently only "image"
- `url: str` -- Base64 data URL or file URL

### GroupCall
- `id: str` -- 12-char UUID hex
- `conversation_id: str`
- `status: "active" | "ended"`
- `mode: "text" | "voice"`
- `participants: list[str]` -- Agent IDs

### StreamingEntry (Frontend)
- `agentId: string`
- `replyToId?: string`
- Tracked in `streamingAgents` signal as `Map<string, StreamingEntry>`

### OracleState (Frontend)
- `active: boolean` -- Whether oracle is currently running
- `directed: boolean`
- `directedAgent: string | null`
- `goal: string | null`
- `rounds: OracleRound[]` -- Per-round details
- `summary: string | null`
- `topic: string | null`

---

## 6. Edge Cases

### Mistral API Errors
1. **409 Conflict (conversation lock)**: Voice pipeline retries up to 3 times with exponential backoff (1s, 2s, 3s). Text pipeline does NOT retry. If the same agent's Mistral conversation is accessed concurrently (e.g., parallel mode + function calls), a 409 can occur.
2. **Agent not synced**: If `sync_to_mistral()` fails for an agent, `mistral_agent_id` remains None. The agent appears in the roster with `ready: false`. Any attempt to message it returns an error. In group chats, `_get_ready_agents()` filters it out, potentially reducing the participant list.
3. **Streaming interruption**: If the client disconnects mid-stream, the Mistral stream continues server-side until complete but results are lost (no persistence).

### Oracle Edge Cases
4. **All agents pass**: If every agent in a round outputs `[PASS]`, `responded_ids` is empty. The round loop breaks, no grading occurs, no summary generated.
5. **Max rounds reached**: After 10 rounds, the loop exits regardless of grader output. This could leave a user's request partially addressed.
6. **Directed message ambiguity**: If two agents share a name prefix (e.g., "Dan" and "Danielle"), the first match in participant order wins. The detection is case-insensitive substring matching, not exact match.
7. **Topic set to "General discussion"**: The code treats `topic == "General discussion"` as equivalent to `topic == None` for topic grading purposes (re-attempts extraction).

### WebSocket Edge Cases
8. **Concurrent messages in group**: If the user sends a new message while a group round is in progress, the active `group_task` is cancelled and an `interrupt` event is sent. The new message starts a fresh round.
9. **WebSocket close code 4004**: Indicates conversation not found. Frontend does NOT auto-reconnect for this code.
10. **Multiple WebSocket connections**: `ConnectionManager` supports multiple connections per conversation. `broadcast()` sends to all. However, the WS handler creates a separate `voice_session` per connection, so multiple browser tabs could create conflicting voice sessions.

### Voice Edge Cases
11. **STT commit timeout**: If ElevenLabs throttles the commit (audio < 0.3s), the backend waits 3 seconds then falls back to `last_partial_text`. If that's also empty or <= 2 chars, no response is triggered.
12. **Audio chunk decoding failure**: Frontend `decodeAudioData` failures are silently caught. Bad chunks are skipped without breaking the playback chain.
13. **Mic already set up**: `ensureMic()` is idempotent -- calling it multiple times reuses the existing stream.
14. **Spacebar PTT conflicts**: PTT via spacebar is disabled when an input/textarea/contentEditable element is focused, preventing interference with text input.

### Data Integrity Edge Cases
15. **Agent removed mid-conversation**: Not handled. If an agent JSON is deleted and the server restarted, existing conversations referencing that agent will fail when trying to look up the agent profile or Mistral agent ID.
16. **Message ID collision**: Client-provided message IDs (from `generateId()` in frontend) could theoretically collide with server-generated IDs, though both use UUID-like generation making collision negligible.
17. **Unbounded message history**: Conversations grow without limit. Agent prompts use `MAX_CONTEXT_MESSAGES = 15` for formatting, but the full message list in `conv.messages` is never trimmed.
18. **Kim's JSON has id "pa"**: The `kim.json` file has `"id": "pa"` but the instructions reference "Alex's PA". The `pa.json` agent file was deleted (shown in git status as ` D backend/agents/pa.json`). The id/name mismatch (`id: "pa"`, `name: "Kim"`) could cause confusion in directed message detection (user says "Kim" but agent ID is "pa").

### Frontend Edge Cases
19. **Mock fallback**: If the backend is unreachable, `useAgents` catches the error and falls back to mock agents. These mock agents cannot send real messages.
20. **Conversation not found on navigation**: If a user navigates to `/chat/:id` or `/group/:id` with an invalid ID, `useConversation` tries to fetch from backend, fails, and redirects to `/`.
21. **Agent Picker in groups**: The "Add agents" button in GroupPage opens an AgentPicker but the `onSelect` handler only logs the IDs -- adding agents to an existing group is NOT implemented.

### Tool Edge Cases
22. **PDF generation failure**: If Playwright is not installed or Chromium launch fails, PDF generation throws an exception. The slides HTML is still stored and accessible, but the PDF URL returns 404.
23. **Chained tool calls**: `_handle_function_calls` loops up to 3 rounds. If the agent chains more than 3 tool calls, the loop exits and returns whatever the last response was, potentially incomplete.

---

## 7. API Surface Contract

### REST Endpoints

#### GET /api/agents
- **Returns**: `Agent[]` -- all registered agents
- **Contract**: Always returns 200. Empty array if no agents loaded.

#### GET /api/agents/:agent_id
- **Returns**: `Agent` object
- **Error**: 404 if agent not found

#### POST /api/conversations
- **Body**: `{ type: "direct" | "group", participants: string[] }` (also accepts `participant_agent_ids`)
- **Returns**: Conversation object (without messages)
- **Errors**:
  - 400 "Unknown agent: {id}" if any participant not in registry
  - 400 "Direct conversations must have exactly 1 participant agent"
  - 400 "Group conversations must have at least 2 participant agents"

#### GET /api/conversations
- **Returns**: Array of conversation summaries (id, type, participants, message_count, topic, created_at)

#### GET /api/conversations/:id
- **Returns**: Full conversation with messages
- **Error**: 404 "Conversation not found"

#### POST /api/conversations/:id/messages
- **Body**: `{ content: string, attachments?: Attachment[] }`
- **Returns**: Agent's reply message (non-streaming)
- **Errors**:
  - 404 "Conversation not found"
  - 400 "Group messages must be sent via WebSocket"
  - 400 for agent not ready

#### POST /api/conversations/:id/messages/upload
- **Body**: Multipart form with `content` (string) and optional `image` (file)
- **Returns**: Agent's reply message
- **Errors**: Same as above

#### POST /api/conversations/:id/call
- **Returns**: Call object `{ id, conversation_id, participants, oracle_agent_id, status, mode }`
- **Error**: 404 "Conversation not found"
- **Note**: Call state stored in module-level `_active_calls` dict, separate from conversation model

#### DELETE /api/conversations/:id/call
- **Returns**: Call object with `status: "ended"`
- **Error**: 404 "No active call"

#### GET /api/slides
- **Returns**: `{ presentations: string[] }` -- list of presentation IDs

#### GET /api/slides/:id
- **Returns**: HTML content (media type: text/html)
- **Error**: 404 "Presentation not found"

#### GET /api/slides/:id/pdf
- **Returns**: PDF bytes (media type: application/pdf, with Content-Disposition attachment header)
- **Error**: 404 "PDF not found"

#### POST /api/voice/transcribe
- **Body**: Multipart form with audio file
- **Returns**: `{ text: string }`
- **Error**: 500 "Mistral client not initialized"

#### POST /api/voice/synthesize
- **Body**: `{ text: string, voice_id?: string }`
- **Returns**: Audio bytes (media type: audio/mpeg)
- **Error**: 500 if ElevenLabs key not set

#### GET /health
- **Returns**: `{ status: "ok" }`
- **Contract**: Always returns 200. No auth check.

### WebSocket /ws/conversations/:id

**Connection**:
- Accepts immediately
- If conversation not found: sends error event, closes with code 4004
- Registers in ConnectionManager for broadcast support

**Message handling**:
- Unknown message types: sends error "Unknown type: {type}"
- Invalid JSON: sends error "Invalid JSON"
- Empty message (no content and no attachments): sends error "Empty message"

**Lifecycle**:
- On disconnect: cancels active group task, stops voice session, unregisters from ConnectionManager
- Group tasks run in background (`asyncio.create_task`) so the WS read loop stays responsive
- Direct chat responses run inline (blocking the WS loop until complete)
