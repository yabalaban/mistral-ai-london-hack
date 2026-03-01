# Code Review Findings — Circles (Ensemble)

Reviewed: all backend + frontend source files cross-referenced against `requirements.md`.

---

## P0 — Broken

### P0-1: XSS via Markdown rendering (dangerouslySetInnerHTML without sanitization)

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/chat/Markdown.tsx`, lines 16-27

**Description**: The `Markdown` component parses user and agent content through `marked.parse()` and renders the resulting HTML via `dangerouslySetInnerHTML` with zero sanitization. Any agent response (or user message echoed back) containing `<script>`, `<img onerror=...>`, or other XSS vectors will execute arbitrary JavaScript in the browser. Mistral agents could be prompt-injected to return malicious HTML.

**Impact**: Full XSS — session hijacking, data exfiltration, UI spoofing. Since there is no authentication, the attack surface is somewhat reduced, but in any deployment this is critical.

**Suggested fix**: Add `dompurify` (or equivalent) as a sanitization pass after `marked.parse()`:
```ts
import DOMPurify from 'dompurify'
const html = useMemo(() => {
  const raw = marked.parse(content, { async: false }) as string
  return DOMPurify.sanitize(raw)
}, [content])
```

---

### P0-2: `_handle_audio` creates duplicate user message in conversation history

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, lines 936-941

**Description**: The legacy `audio` message handler (`_handle_audio`) appends a user message to `conv.messages` at line 937, then calls `_handle_direct_streaming` or `_handle_group_streaming`. For the group path, `_handle_group_streaming` calls `oracle.run_group_turn_streaming`, but the user message was already appended by the WS handler in the `"message"` codepath. However, `_handle_audio` is a different codepath — it does NOT go through the normal `"message"` branch. The issue is that `_handle_direct_streaming` at line 790 also appends a message (`agent_msg`), but does NOT re-add the user message, so that path is fine. But for groups, the oracle's `_build_agent_prompt` relies on finding user messages in `conv.messages`. The `_handle_group_streaming` function calls `oracle.run_group_turn_streaming` which does NOT append the user message (it was appended by `_handle_audio` at line 937). So the group path is actually OK. BUT: looking more carefully, in the normal WS `"message"` flow for groups (lines 698-699), the user message is appended, then `_handle_group_streaming` is called, and inside that the oracle starts — the oracle does NOT add the user message again. However, for the voice pipeline's `_group_voice_response` (line 404), it ALSO appends a user message at line 404. So both `_handle_audio` AND `_group_voice_response` are creating messages. The bug is actually in `_handle_audio`: after appending the user message and calling `_handle_direct_streaming`, the function then proceeds (lines 943-962) to also perform TTS on the last agent message — but `_handle_direct_streaming` already sent `message_complete` to the WS. The TTS audio is sent as a separate `audio_chunk` AFTER the `message_complete`, which means the frontend doesn't know to play it (no `agent_speaking` event was sent). This is a dead/broken code path.

**Impact**: The `audio` message type is a legacy batch path. It will produce confusing state — messages complete before audio arrives, no speaking indicators, and potentially garbled behavior.

**Suggested fix**: Mark `_handle_audio` as deprecated, or properly integrate it with the voice pipeline by adding `agent_speaking`/`agent_done` events and removing the separate TTS call that duplicates the streaming path.

---

### P0-3: Artificial delay on `message_complete` blocks ALL messages including voice audio

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, lines 1076-1086

**Description**: The `_send` helper applies an artificial delay of 0.5-2.5 seconds to every `message_complete` event. This delay is intentional for text mode to simulate reading pace, but it also applies during voice calls. In the voice pipeline, `message_complete` is sent after all audio has been delivered (in `_direct_voice_response` line 379 and `_group_voice_response` line 559). The delay means there is an unnecessary 0.5-2.5s gap between the agent finishing speaking and the `message_complete` event. During this time, the frontend still shows the agent in `streamingAgents`, which means the typing indicator persists after audio playback ends. For group voice, this delay accumulates between agents — each agent has 0.5-2.5s of dead time before the oracle can move to the next speaker.

**Impact**: Voice calls feel sluggish. Group voice calls with many agents accumulate several seconds of artificial dead time.

**Suggested fix**: Skip the delay for voice mode calls. This could be done by adding a parameter to `_send`, e.g. `skip_delay=True`, or by checking for an `is_voice` context flag.

---

## P1 — Incomplete

### P1-1: AgentPicker `onSelect` handler only logs — adding agents to existing group not implemented

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/group/GroupPage.tsx`, lines 178-186

**Description**: The "Add agents" button in GroupPage opens an AgentPicker modal, but when agents are selected and the user clicks "Add", the handler just calls `console.log('Add agents:', ids)` and closes the picker. No backend API exists to add agents to an existing conversation. The backend `Conversation` model has no mutation endpoint for `participant_agent_ids`.

**Impact**: Users see a functional-looking "add agents" button that does nothing. Misleading UX.

**Suggested fix**: Either (a) implement `PUT /api/conversations/:id/participants` to support dynamic participant changes, or (b) remove the "Add agents" button from GroupPage to avoid confusion.

---

### P1-2: `discardStream()` is never called — abandoned streaming indicators accumulate

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/state/conversations.ts`, lines 77-81; `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/api/ws.ts`

**Description**: The `discardStream()` function exists in the conversations state module but is never called anywhere. If an agent streaming session fails or is interrupted on the backend (e.g., network error, agent crash), the `streamingAgents` map entry for that agent is never cleaned up because `message_complete` is never sent. The only cleanup path is when `message_complete` arrives (via `commitMessage`) or when `interrupt`/`agent_done` events clear the map.

**Impact**: If the backend fails to send `message_complete` for an agent, the typing indicator for that agent persists indefinitely until the next page navigation or conversation switch.

**Suggested fix**: Call `discardStream()` on WS `error` events, on WS disconnect/reconnect, and potentially on a timeout (e.g., if an agent has been "typing" for more than 60 seconds).

---

### P1-3: No WS `error` event display to users — errors are silently logged

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/api/ws.ts`, lines 211-213

**Description**: The WS dispatch `default` case is a no-op. The `error` event type from the backend is not handled by the dispatch switch — it falls through to `default: break`. The backend sends `error` events for agent failures, empty messages, unknown types, etc., but the frontend silently discards them.

**Impact**: Users get no feedback when operations fail. A message to an unready agent, a group conversation failure, or a voice transcription error are all invisible.

**Suggested fix**: Add a case for `'error'` in the dispatch switch that surfaces the error to the user, e.g., via a toast notification signal or an inline error message in the chat.

---

### P1-4: WS reconnect does not re-sync conversation state

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/api/ws.ts`, lines 51-56

**Description**: When the WebSocket auto-reconnects (2s delay on unexpected close), it just opens a new connection to the same conversation. Any messages sent by agents during the disconnection window are lost — the frontend never receives the `message_complete` events for those messages. The frontend does not re-fetch the conversation from the REST API after reconnecting, so it will be out of sync with the backend.

**Impact**: Messages lost during brief disconnections. State divergence between frontend and backend.

**Suggested fix**: On reconnect, fetch the full conversation via `GET /api/conversations/:id` and update local state with `upsertConversation()` to catch up on any missed messages.

---

### P1-5: Attachments are not passed through the group voice pipeline

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, line 441

**Description**: In `_group_voice_response`, the oracle is called with `voice_mode=True` and attachments set to `None` (line 441: `self._oracle.run_group_turn_streaming(self._conv, text, None, voice_mode=True)`). For the text group path via `_handle_group_streaming`, attachments are passed: `oracle.run_group_turn_streaming(conv, content, attachments or None)` (line 811-812). But the oracle's `run_group_turn_streaming` never uses the `attachments` parameter — it builds prompts from `conversation.messages` which already contain the user message with attachments. So this is actually a non-issue for attachments on user messages already in the conversation. However, the image attachments in the user message recorded by voice response (line 404: `Message(role=MessageRole.USER, content=text)`) have no attachments since voice input is pure text. This is by design.

Actually, re-examining: the real issue is in the text path. When `_handle_group_streaming` is called, the user message (with attachments) was already appended to `conv.messages` (line 699). But the oracle's `_build_agent_prompt` does not include attachment URLs in the prompt text. The context line format is just `[{idx}] **User**: {msg.content}` — no mention of attachments. So multimodal image attachments are lost in group conversations. The agent prompts are plain text, not multimodal Mistral inputs.

**Impact**: Images attached to group messages are never seen by agents. Only the text content is included in the oracle-built prompt.

**Suggested fix**: Include image attachment references in the agent prompt context, or pass multimodal inputs to the Mistral conversation API for the relevant agent.

---

### P1-6: `create_slides` is called synchronously — blocks the event loop

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/tools/slides.py`, lines 137-138; `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/conversations/manager.py`, line 174

**Description**: The `create_slides` function calls `_render_pdf` which uses `sync_playwright` (line 191) — a synchronous blocking call that launches a headless Chromium browser, navigates, waits 2 seconds, and renders a PDF. This is called from `_handle_function_calls` which is `async` but calls `handler(**args)` synchronously (line 174). Since Playwright's `sync_playwright` runs a blocking event loop, this blocks the asyncio event loop for the entire duration (potentially 5-10+ seconds).

**Impact**: All WebSocket connections and HTTP requests are frozen while a PDF is being generated. Other users' messages, voice audio, etc. are all blocked.

**Suggested fix**: Use `async_playwright` instead of `sync_playwright`, or run the synchronous code in a thread executor: `await asyncio.to_thread(handler, **args)`.

---

### P1-7: Group text path does not retry on Mistral 409 Conflict

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/oracle/engine.py` (sequential agent streaming, lines 927-943); `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py` (direct streaming, lines 992-1003)

**Description**: The requirements document (section 6.1) states "Voice pipeline retries up to 3 times with exponential backoff (1s, 2s, 3s). Text pipeline does NOT retry." The direct voice path in `_direct_voice_response` (ws.py lines 270-315) has retry logic for 409. However, neither the direct text streaming path (`_stream_agent_response`) nor any oracle engine streaming path has retry logic. In parallel mode, if multiple agents hit the same Mistral conversation concurrently, 409s could occur.

**Impact**: Transient 409 errors in group text mode cause agent responses to fail silently. The oracle logs the exception and continues, but that agent's response is lost.

**Suggested fix**: Add 409 retry logic to the oracle engine's `_run_sequential` and `_stream_to_queue` methods, similar to the voice path.

---

### P1-8: `AgentVerdict` type in oracle state is missing 'interrupted' variant

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/state/oracle.ts`, line 6

**Description**: The `AgentVerdict` interface defines `verdict: 'responded' | 'passed' | 'skipped' | 'filtered'` but the backend can also send `verdict: 'interrupted'` (engine.py line 1089). The frontend `WSEvent` type at `types/index.ts` line 57 includes `'interrupted'` in the union, but the `AgentVerdict` interface used in oracle state does not. This means TypeScript won't flag attempts to use the `interrupted` verdict in oracle state, but the `VerdictPill` component in `GroupMessages.tsx` does have a color mapping for `interrupted` (line 14). The mismatch is cosmetic but violates the stated contract.

**Impact**: Minor type inconsistency. The `interrupted` color mapping works at runtime because JS doesn't enforce TS types, but the TypeScript type is wrong.

**Suggested fix**: Add `'interrupted'` to the `AgentVerdict.verdict` union type.

---

### P1-9: Direct chat response blocks the WS read loop

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, lines 708-713

**Description**: For direct conversations, the WS handler calls `await _handle_direct_streaming(...)` inline. This means the WS read loop is blocked for the entire duration of the agent's streaming response (which can be several seconds). During this time, the server cannot process any other client messages on this WS connection — including `voice_state`, `audio_stream`, `end_call`, or additional text messages.

Requirements section 4.14 states: "Direct chat responses run inline (blocking the WS loop until complete)" — so this is by design. However, it means PTT release cannot be processed during an ongoing response, and a user typing a new message while the agent is responding will queue up and only be processed after the response completes.

**Impact**: User interactions are delayed during direct chat streaming. Less critical than for group chats (which use background tasks).

**Suggested fix**: Move direct chat to background task similar to group chat, so the WS loop stays responsive. Or document this as a known trade-off.

---

## P2 — Inconsistent

### P2-1: kim.json has `id: "pa"` but filename is `kim.json` — agent rename incomplete

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/agents/kim.json`, line 2

**Description**: The file `kim.json` has `"id": "pa"` and `"name": "Kim"`. The old `pa.json` is deleted (shown in git status as ` D backend/agents/pa.json`). The agent ID is "pa" but the display name is "Kim". This creates confusion: directed message detection checks agent names (case-insensitive), so saying "Kim, can you..." will match because the name is "Kim". But the agent_id in all API responses is "pa", not "kim". The instructions also say "You're Alex's PA" — referencing a different name entirely.

**Impact**: (1) URL paths use agent_id "pa" which is confusing. (2) Instructions mention "Alex" which is a remnant of a previous name. (3) If someone says "pa, do X", directed detection won't match because it checks the name "Kim", not the id.

**Suggested fix**: Change the `id` field to `"kim"`, update instructions to reference "Kim" instead of "Alex's PA", and ensure the old `pa.json` deletion is committed.

---

### P2-2: Backend sends `message_complete` without artificial delay for group voice but WITH delay for group text

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, lines 1076-1081

**Description**: The `_send` function applies the artificial delay to ALL `message_complete` events regardless of context. This means group text messages (sent by `_handle_group_streaming` at line 862) get the delay, voice messages (sent by `_group_voice_response` at line 559) also get the delay, and direct messages (sent by `_stream_agent_response` at line 1051) also get the delay. The requirements say "delay proportional to content length to simulate natural reading/speaking pace" — but in voice mode, the audio playback already provides natural pacing, making the delay redundant and harmful.

**Impact**: Inconsistent timing behavior between text and voice modes. Voice mode should be snappier.

**Suggested fix**: See P0-3 — same root cause.

---

### P2-3: `CreateAgentModal` produces agents with empty `avatar` string

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/roster/CreateAgentModal.tsx`, line 74

**Description**: When creating a custom agent, the `avatar` field is hardcoded to `''`. The `Avatar` component handles this correctly — `showImg` is `false` when `src` is empty, so it falls back to the color-coded initial. However, the `AgentProfilePanel` and all other components pass `agent.avatar` as `src` to `Avatar`. Since `''` is falsy, this works fine with the current Avatar implementation. No actual bug here — the Avatar fallback handles it.

**Impact**: No visual bug. The created agent shows a colored initial instead of an image, which is acceptable UX.

**Suggested fix**: Consider adding an avatar upload option to `CreateAgentModal` for better UX, but this is not a bug.

---

### P2-4: Frontend conversation participants include 'user' in mock mode but backend never includes 'user'

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/utils/conversations.ts`, line 11; `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/roster/AgentCard.tsx`, line 19

**Description**: In mock mode, `createGroupConversation` sets `participants: ['user', ...agentIds]` and `AgentCard` sets `participants: ['user', agent.id]`. But the backend's `create_conversation` returns `participants: conv.participant_agent_ids` which never includes 'user'. The Sidebar and GroupPage filter participants with `.filter(p => p !== 'user')` defensively, but this creates an inconsistency: mock conversations have 'user' in participants, real ones don't.

**Impact**: Code that counts participants or checks membership may behave differently in mock vs real mode. The defensive filters prevent visible bugs, but the data model is inconsistent.

**Suggested fix**: Remove 'user' from mock conversation participants to match the backend contract, and remove the defensive `filter(p => p !== 'user')` calls.

---

### P2-5: Oracle engine yields `"oracle"` event type but WS handler maps it to `"oracle_reasoning"`

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/oracle/engine.py`, lines 641, 723; `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, lines 457, 831

**Description**: The oracle engine's `run_group_turn_streaming` yields events with type `"oracle"` (e.g., line 723: `yield ("oracle", {...})`), but the WS handler maps this to the `"oracle_reasoning"` event type sent to the frontend (line 832). This mapping is intentional but the naming is confusing. The event type string used internally in the generator does not match the WS protocol. Similarly, `"message"` events from the oracle (which carry Message objects) are re-serialized as `"message_complete"` in the WS handler.

**Impact**: No runtime bug, but the mismatch between oracle event types and WS event types makes the code harder to follow and increases the risk of mapping errors.

**Suggested fix**: Rename the oracle's yield types to match the WS protocol names (`"oracle_reasoning"`, `"message_complete"`) for consistency. Or add documentation mapping the translation.

---

### P2-6: Theme inconsistency — CLAUDE.md says "dark theme with glass morphism" but code implements light theme

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/chat/MessageBubble.tsx`, lines 30, 61-65

**Description**: CLAUDE.md states "dark theme with glass morphism (`glass`, `glass-strong`), cyan accent (`#06b6d4`)" but the actual UI uses light colors: `bg-zinc-100`, `text-zinc-900`, `bg-white/60`, `hover:bg-zinc-50`, etc. MessageBubble uses `text-zinc-700` for agent messages and `text-zinc-900` for names. The system message styling uses `bg-zinc-100 border-zinc-200 text-zinc-400`. All of this is a light theme, not a dark theme.

**Impact**: Documentation does not match the actual UI. CLAUDE.md misleads contributors about the design direction.

**Suggested fix**: Update CLAUDE.md to accurately describe the current theme as "light theme with glass morphism and cyan accent."

---

### P2-7: `message_partial` event from oracle engine uses different structure than what WS handler expects

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/oracle/engine.py`, lines 998-1003; `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, lines 507-519

**Description**: The oracle engine yields `("message_partial", {"agent_id": aid, "content": full_text, "message_id": msg_id, "reply_to_id": agent_reply_to})`. The WS handler for `_group_voice_response` receives this and constructs a WS message with `data.get("agent_id")`, `data.get("message_id")`, etc. But in the text group path `_handle_group_streaming`, the `message_partial` event type is not handled at all — there is no `elif event_type == "message_partial"` case. The oracle only emits `message_partial` when `voice_mode=True`, so the text path never encounters it. This is fine at runtime but fragile — if voice_mode logic changes, partials would be silently dropped in the text path.

**Impact**: No current bug, but a maintenance hazard.

**Suggested fix**: Add a passthrough handler for `message_partial` in `_handle_group_streaming` for completeness.

---

### P2-8: `ConversationManager.send_direct_message` does not use `handoff_execution="client"` consistently

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/conversations/manager.py`, lines 104-115 vs `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, lines 992-1003

**Description**: The REST `send_direct_message` path uses `handoff_execution="client"` on both `start_async` and `append_async`. The WS `_stream_agent_response` also uses `handoff_execution="client"`. However, the oracle engine's streaming calls (`_run_sequential`, `_stream_to_queue`, `_stream_single_agent`) do NOT pass `handoff_execution="client"`. This means tool calls (function calls) in group conversations are handled differently — the oracle streaming path does not detect or handle `FunctionCallEvent` during streaming. If an agent in a group tries to use a tool (e.g., Kim using `create_slides` in a group), the function call would be silently ignored.

**Impact**: Tool use (create_slides, code_interpreter, etc.) does not work in group conversations. Only direct 1:1 conversations properly handle function calls.

**Suggested fix**: Add `handoff_execution="client"` to the oracle engine's Mistral API calls, and add function call detection + handling similar to the direct path's `_stream_agent_response`.

---

## P3 — Cleanup

### P3-1: `pa.json` deleted but `kim.json` untracked — incomplete git state

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/agents/pa.json` (deleted), `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/agents/kim.json` (untracked)

**Description**: Git status shows `pa.json` is deleted and `kim.json` is untracked. This is a rename-in-progress that hasn't been committed. Combined with the `id: "pa"` mismatch in P2-1.

**Impact**: Confusing git history. Other developers may not understand the rename.

**Suggested fix**: Stage both changes (`git rm pa.json`, `git add kim.json`), fix the `id` field (see P2-1), and commit.

---

### P3-2: CreateAgentModal template includes non-existent tool names

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/roster/CreateAgentModal.tsx`, lines 26, 32, 39, 47

**Description**: Templates reference tools like `'analysis'`, `'vision'`, `'reasoning'`, and `'calendar'` which don't exist in the backend's `BUILT_IN_TOOLS` map (which has: `code_interpreter`, `web_search`, `image_generation`, `create_slides`). Created agents with these tools would have them silently ignored when synced to Mistral.

**Impact**: Misleading UI. Users think they're selecting real capabilities but the tools don't exist. Since custom agents are frontend-only anyway (P1-1 scope), this is cosmetic.

**Suggested fix**: Update template tool lists to use actual tool names from `BUILT_IN_TOOLS`.

---

### P3-3: Mock agents use different IDs than real agents

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/mocks/agents.ts`

**Description**: Mock agent IDs (`engineer-emma`, `designer-dan`, `strategist-sofia`, `chess-marcus`, `pa-alex`) don't match real agent IDs (`emma`, `dan`, `sofia`, `marcus`, `pa`). Mock agent names also differ (`Alex` vs `Kim`). This means mock-mode conversations created during development would not work if the backend is later connected, because agent IDs won't match.

**Impact**: Development/testing inconsistency. Not a production issue since mocks are gated by `VITE_USE_MOCKS`.

**Suggested fix**: Update mock agent IDs and names to match the real agents.

---

### P3-4: `_handle_audio` is a legacy code path that is partially broken

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, lines 904-962

**Description**: The `audio` message type handler is a batch STT path that pre-dates the PTT voice pipeline. It transcribes audio, sends a response, then separately calls TTS without proper speaking indicators. With the modern PTT pipeline (`voice_state` + `audio_stream`), this path is unused.

**Impact**: Dead code that could cause confusion if triggered.

**Suggested fix**: Remove or explicitly deprecate with a warning log.

---

### P3-5: `LogsPanel` referenced in CLAUDE.md project structure but doesn't exist

**Location**: CLAUDE.md project structure lists `components/shared/LogsPanel`

**Description**: The CLAUDE.md file lists `LogsPanel` under `components/shared/`, but no such file exists. The shared components are: `Avatar.tsx`, `Button.tsx`, `Spinner.tsx`, `ImageUpload.tsx`.

**Impact**: Documentation drift.

**Suggested fix**: Remove `LogsPanel` from the CLAUDE.md project structure.

---

### P3-6: Unused import `AsyncIterator` in ws.py

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, line 36

**Description**: `AsyncIterator` is imported from `typing` but is only used inside a function-local type annotation context that doesn't need the import at module scope. Actually, it IS used at line 323 in `_text_iter`. This is fine — not an unused import. Disregard.

---

### P3-7: Multiple group message handlers with duplicated event dispatch logic

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, lines 439-606 (`_group_voice_response`) and lines 808-901 (`_handle_group_streaming`)

**Description**: Both `_group_voice_response` and `_handle_group_streaming` contain nearly identical event dispatch logic mapping oracle events to WS messages. The only difference is that the voice path also manages TTS connections. This duplication means any change to the oracle event protocol requires updates in two places.

**Impact**: Maintenance burden. Bug fixes applied to one path may be missed in the other.

**Suggested fix**: Extract the common event dispatch into a shared helper function. The voice-specific TTS logic can be handled via callbacks or a flag.

---

### P3-8: `conversation.participant_agent_ids` does not include `GroupCall.participants` field

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/conversations/models.py` (no `participants` on `GroupCall`); `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/routes.py`, line 169

**Description**: The `GroupCall` model has a `conversation_id`, `status`, and `mode`, but not `participants`. However, the REST endpoint `start_call` (routes.py line 169) adds `"participants": conv.participant_agent_ids` to the call dict manually. The `GroupCall` Pydantic model is never actually used for serialization — the endpoint builds a plain dict.

**Impact**: The `GroupCall` model is partially unused/stale.

**Suggested fix**: Either use the `GroupCall` model properly or remove it and document the call dict shape.

---

### P3-9: `ScriptProcessorNode` is deprecated in Web Audio API

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/hooks/useVoice.ts`, line 140

**Description**: `createScriptProcessor` is deprecated and may be removed from browsers in the future. The modern replacement is `AudioWorkletNode`.

**Impact**: Future browser compatibility risk. Works in all current browsers.

**Suggested fix**: Migrate to `AudioWorkletNode` when time permits. Low priority.

---

### P3-10: `callMode` is toggled client-side without notifying the backend

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/group/GroupPage.tsx`, line 93; `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/chat/ChatPage.tsx`, line 88

**Description**: When the user toggles between text and voice mode during a call, `callMode.value` is updated locally, but no WS event is sent to the backend. The backend doesn't know whether the client is in text or voice mode. The call's `mode` field in `_active_calls` is set at creation time and never updated.

**Impact**: The backend cannot adapt behavior based on the current mode. For example, if the user switches from voice to text mode mid-call, the backend still expects voice_state/audio_stream events.

**Suggested fix**: Send a WS event like `{ type: "mode_change", mode: "text" | "voice" }` when toggling, and update the backend's call state accordingly.

---

### P3-11: `CORS allow_origins=["*"]` is overly permissive

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/main.py`, lines 59-64

**Description**: The CORS middleware allows all origins, methods, and headers. While appropriate for local development, this would be a security concern in production.

**Impact**: No production deployment mentioned, so this is a low-priority note.

**Suggested fix**: Restrict CORS origins to the frontend's URL in production.

---

### P3-12: `conversation.participant_agent_ids` in Sidebar filters out 'user' but 'user' is never in the backend response

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/layout/Sidebar.tsx`, line 53

**Description**: `const agentIds = conv.participants.filter((p) => p !== 'user')` — this filter is unnecessary when using real backend data, since the backend never includes 'user' in participants. It is only needed for mock data (see P2-4).

**Impact**: Harmless extra filter, but indicates confusion about the data contract.

**Suggested fix**: Remove the filter after fixing mock data (P2-4).

---

### P3-13: Conversation REST API missing `lastActivity` sort — conversations appear in creation order only

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/routes.py`, lines 89-101

**Description**: `list_conversations` returns conversations in the order they were created (dict insertion order). There is no sorting by last message timestamp. The sidebar shows conversations in this same order. Active conversations (with recent messages) don't float to the top.

**Impact**: UX issue — users must scroll to find active conversations.

**Suggested fix**: Sort by the timestamp of the last message, or add a `last_activity` field to the conversation model.

---

### P3-14: `_extract_chunk_text` duplicates logic already in `extract_text_from_content`

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, lines 1065-1073

**Description**: `_extract_chunk_text` is a trivial wrapper that just calls `extract_text_from_content(output.content)`. It could be replaced with direct calls to the utility function.

**Impact**: Minor code duplication.

**Suggested fix**: Inline the call or keep as-is if the name adds clarity.

---

### P3-15: `build_inputs` returns different types depending on attachments

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/utils.py`, lines 68-91

**Description**: `build_inputs` returns `str` when there are no attachments, but `list[dict]` (a list containing a single message dict with role and content blocks) when there are attachments. The type annotation says `str | list[dict]`. This dual return type means callers must handle both shapes, and the Mistral API must accept both (which it does for `inputs` parameter). This is functional but fragile.

**Impact**: Type confusion for maintainers. Works at runtime.

**Suggested fix**: Always return the same type, or document the dual return clearly.

---

### P3-16: `useConversation` cleanup sets `activeConversationId` to null before `wsManager.disconnect()`

**Location**: `/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/hooks/useConversation.ts`, lines 33-36

**Description**: The cleanup function sets `activeConversationId.value = null` then calls `wsManager.disconnect()`. Setting the signal to null triggers a re-render of components that depend on `activeConversation` (computed), which immediately returns null. Any in-flight message processing (like `appendMessage`, `commitMessage`) that checks `activeConversationId.value` will find it null and silently discard the operation. If a `message_complete` event arrives during cleanup, it could be lost.

**Impact**: Edge case — messages arriving during navigation away from a conversation are discarded. Unlikely to cause visible issues since the user is navigating away.

**Suggested fix**: Call `wsManager.disconnect()` first, then set `activeConversationId.value = null`.

---

## Summary of New Issues Found (beyond seed list)

The following issues were discovered through systematic code review and were NOT in the original seed list:

- **P0-2**: Legacy `_handle_audio` sends broken TTS without speaking indicators
- **P0-3**: Artificial delay on `message_complete` blocks voice calls
- **P1-4**: WS reconnect does not re-sync conversation state
- **P1-5**: Image attachments lost in group conversation prompts
- **P1-6**: `create_slides` blocks event loop with synchronous Playwright
- **P1-7**: No 409 retry in group text path
- **P1-9**: Direct chat blocks WS read loop
- **P2-5**: Internal oracle event type names don't match WS protocol names
- **P2-7**: `message_partial` not handled in text group path
- **P2-8**: Tool use (function calls) not implemented in group conversations
- **P3-7**: Duplicated event dispatch between voice and text group handlers
- **P3-10**: Call mode toggle doesn't notify backend
- **P3-13**: Conversations not sorted by activity
- **P3-16**: Race condition in `useConversation` cleanup ordering

## Seed Issue Validation

| Seed | Status | Finding ID |
|------|--------|-----------|
| 1. pa.json/kim.json rename | Confirmed | P2-1, P3-1 |
| 2. AgentPicker onSelect logs only | Confirmed | P1-1 |
| 3. CreateAgentModal empty avatar | Confirmed but not a bug — Avatar handles it | P2-3 |
| 4. discardStream() never called | Confirmed | P1-2 |
| 5. No error event display | Confirmed | P1-3 |
| 6. Markdown XSS | Confirmed — critical | P0-1 |
| 7. Oracle grader context mismatch | Not confirmed — grader uses full message history, not limited context |
| 8. Attachments lost in group | Confirmed — at prompt level | P1-5 |
| 9. 409 retry only in direct voice | Confirmed | P1-7 |
| 10. Theme inconsistency | Confirmed — light not dark | P2-6 |
| 11. message_partial/message_complete timing | Partial — delay on message_complete is the issue | P0-3 |
| 12. CallMode toggle during speaking | Confirmed — no backend notification | P3-10 |
