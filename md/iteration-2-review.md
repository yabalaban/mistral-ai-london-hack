# Iteration 2 — Code Review

## Fix Verification (Iteration 1)

### P0-1: XSS via Markdown rendering — VERIFIED
- **File**: `frontend/src/components/chat/Markdown.tsx`
- **Status**: Correctly implemented. `DOMPurify.sanitize()` wraps `marked.parse()` output before `dangerouslySetInnerHTML`. Package `dompurify@^3.3.1` and `@types/dompurify@^3.0.5` are in `package.json` and installed in `node_modules`. The default import `import DOMPurify from 'dompurify'` works correctly with DOMPurify v3 in a browser (Preact/Vite) context since DOMPurify auto-detects the `window` object.

### P0-2: Legacy `_handle_audio` dead code — VERIFIED
- **File**: `backend/src/ensemble/api/ws.py`
- **Status**: Confirmed removed. No references to `_handle_audio` exist anywhere in the codebase. Unknown message types fall through to the `else` clause at line 757 which sends an error.

### P0-3: Artificial delay blocks voice calls — VERIFIED
- **File**: `backend/src/ensemble/api/ws.py`
- **Status**: Correctly implemented. `_send()` (line 1034) accepts `skip_delay: bool = False`. The delay logic at line 1036 only fires when `not skip_delay` and the type is `message_complete`. Voice paths `_direct_voice_response` (line 387) and `_group_voice_response` (line 568) pass `skip_delay=True` on their `message_complete` sends. The text path `_stream_agent_response` (line 1009) does NOT pass `skip_delay` — this is correct since the delay is intentional for text-only chat.

### P1-1: AgentPicker onSelect does nothing — VERIFIED
- **File**: `frontend/src/components/group/GroupPage.tsx`
- **Status**: Correctly removed. No import of `AgentPicker` and no reference to `showAgentPicker` state exists in `GroupPage.tsx`. The `AgentPicker.tsx` component file still exists on disk but is not imported anywhere — this is dead code but harmless.

### P1-2: discardStream() never called — VERIFIED
- **File**: `frontend/src/api/ws.ts`
- **Status**: Correctly implemented. `clearStreamingAgents()` (line 35-38) iterates the `streamingAgents` map and calls `discardStream()` for each. Called from `ws.onclose` (line 75) and from the `'error'` dispatch case (line 237).

### P1-3: No WS error event display — VERIFIED
- **Files**: `frontend/src/state/ui.ts`, `frontend/src/api/ws.ts`
- **Status**: Signal `errorMessage` exists in `ui.ts` (line 6) and is set in the `'error'` case of the WS dispatch (line 236). However, **the signal is never rendered in any component** — see P1 issue below.

### P1-4: WS reconnect doesn't re-sync state — VERIFIED
- **File**: `frontend/src/api/ws.ts`
- **Status**: Correctly implemented. The `isReconnect` flag (line 32) is set when reconnecting to the same conversation (line 43). On `ws.onopen`, if `isReconnect` is true, it calls `fetchConversation(convId).then(conv => upsertConversation(conv))` (lines 56-58). `fetchConversation` is properly imported from `./client.ts` and returns `Promise<Conversation>`. `upsertConversation` is imported from conversations state and replaces the entire conversation including messages.

### P1-6: create_slides blocks event loop — VERIFIED
- **File**: `backend/src/ensemble/conversations/manager.py`
- **Status**: Correctly implemented. Line 175: `result = await asyncio.to_thread(handler, **args)` offloads synchronous tool handlers to a thread pool.

### P1-7: No 409 retry in group text — VERIFIED
- **File**: `backend/src/ensemble/oracle/engine.py`
- **Status**: Correctly implemented. 409 retry logic (3 attempts, 1/2/3s backoff) added to:
  - `_run_sequential` (lines 928-959)
  - `_stream_to_queue` (lines 1149-1178)
  - `_stream_single_agent` (lines 1284-1315)
  - The pattern is consistent across all three: check `"409" in str(exc)`, back off with `1.0 * (attempt + 1)`, re-raise on final attempt.

### P1-8: AgentVerdict missing 'interrupted' — VERIFIED
- **File**: `frontend/src/state/oracle.ts`
- **Status**: Correctly added. Line 6: `verdict: 'responded' | 'passed' | 'skipped' | 'filtered' | 'interrupted'`. Also confirmed in `frontend/src/types/index.ts` line 57: the `agent_verdict` WSEvent type includes `'interrupted'`.

### P1-9: Direct chat blocks WS read loop — VERIFIED
- **File**: `backend/src/ensemble/api/ws.py`
- **Status**: Correctly implemented. Direct chat now runs as `direct_task = asyncio.create_task(...)` (line 721), matching the group task pattern. Cancellation on new message (lines 709-715) and cleanup in `finally` block (lines 762-767) are both correct. No race conditions — see analysis below.

### P2-1: kim.json ID mismatch — VERIFIED
- **File**: `backend/agents/kim.json`
- **Status**: ID is `"kim"`, instructions reference "Kim". Correct.

### P2-6: CLAUDE.md theme description — VERIFIED
- **File**: `CLAUDE.md`
- **Status**: Line 89 now reads "light theme". Correct.

---

## Race Condition Analysis: Background Direct Task (P1-9 fix)

The `direct_task` background pattern does NOT introduce race conditions:
- Python asyncio is single-threaded — `conv.messages.append()` in the background task and `conv.messages.append()` in the main loop never run truly concurrently.
- Before creating a new `direct_task`, the previous one is cancelled and awaited (lines 709-715), ensuring no two direct tasks run simultaneously for the same connection.
- The `conv` object is shared by reference, which is correct — the background task needs to see/modify the same conversation state.

---

## NEW Issues Found

### P1-A: `errorMessage` signal is write-only — never displayed in UI

- **Severity**: P1 (Incomplete)
- **Files**: `frontend/src/state/ui.ts`, all component files
- **Description**: The `errorMessage` signal is set on WS errors (ws.ts line 236) but no component reads or renders it. The user never sees the error. The P1-3 fix created the signal and wired it in `ws.ts`, but never added a UI component (toast, banner, etc.) to display it.
- **Impact**: Users get no visible feedback when WebSocket errors occur. The fix is half-done.
- **Suggested fix**: Add an error toast/banner component that reads `errorMessage.value` and renders it, e.g. in `Shell.tsx`.

### P1-B: `_stream_agent_response` (direct text path) missing 409 retry

- **Severity**: P1 (Incomplete)
- **Files**: `backend/src/ensemble/api/ws.py` lines 923-1020
- **Description**: The 409 retry logic was added to the oracle engine paths (`_run_sequential`, `_stream_to_queue`, `_stream_single_agent`) and the voice direct path (`_direct_voice_response`), but `_stream_agent_response` — the main **text-mode direct chat** streaming function — has no 409 retry. Lines 950-961 call `append_stream_async` / `start_stream_async` without any retry loop. This is the primary function used for 1:1 text conversations.
- **Impact**: Direct text chats will crash on Mistral 409 Conflict errors while all other paths handle them gracefully.
- **Suggested fix**: Add the same 3-attempt retry loop pattern used in the oracle engine methods.

### P1-C: Attachments silently dropped in group chat (original P1-5, still unfixed)

- **Severity**: P1 (Incomplete)
- **Files**: `backend/src/ensemble/oracle/engine.py`, `backend/src/ensemble/api/ws.py`
- **Description**: `_handle_group_streaming` passes `attachments` to `oracle.run_group_turn_streaming()` (line 831), and the method signature accepts `attachments: list[Attachment] | None = None` (line 582), but the parameter is **never used** in the method body. Agents are prompted with text-only context via `_build_agent_prompt()`. Image attachments sent in group chats are silently dropped — agents never see them.
- **Impact**: Users who attach images in group conversations get no indication the images were ignored.
- **Suggested fix**: Either (a) pass attachments into `build_inputs` when constructing agent prompts, or (b) explicitly reject attachments in group chat with a user-facing error message.

---

## P2 Issues (Inconsistencies)

### P2-A: Dead `AgentPicker.tsx` file

- **Severity**: P2 (Inconsistent)
- **File**: `frontend/src/components/group/AgentPicker.tsx`
- **Description**: The component was removed from `GroupPage.tsx` (P1-1 fix) but the file itself still exists. It is not imported anywhere. Dead code.
- **Suggested fix**: Delete the file.

### P2-B: `clearStreamingAgents` not called on `ws.onerror`

- **Severity**: P2 (Inconsistent)
- **File**: `frontend/src/api/ws.ts` lines 82-84
- **Description**: `clearStreamingAgents()` is called on `ws.onclose` (line 75) and on server `'error'` events (line 237), but NOT on `ws.onerror` (line 82-84). While `onerror` is typically followed by `onclose` (so the close handler will clean up), there may be edge cases where cleanup timing matters. The `onerror` handler only logs.
- **Impact**: Minimal — `onclose` fires after `onerror` in practice. But for consistency, `clearStreamingAgents()` could be called in both.

### P2-C: Group text path `message_complete` delay is applied but unnecessary

- **Severity**: P2 (Inconsistent)
- **File**: `backend/src/ensemble/api/ws.py` lines 877-891
- **Description**: In `_handle_group_streaming`, `message_complete` events (line 881) are sent via `_send()` without `skip_delay=True`, so they incur the artificial typing delay. The voice group path (`_group_voice_response` line 568) correctly skips the delay. The text group path should arguably also skip the delay since messages are already streamed chunk-by-chunk — the delay on `message_complete` only delays the final "done" indicator, not the visible text.
- **Impact**: Minor UX issue — group text conversations have a small artificial delay after each agent finishes speaking before the next agent can start.

---

## Summary

| Category | Count | Details |
|----------|-------|---------|
| **Fix Verifications** | 13/13 pass | All iteration 1 fixes correctly applied |
| **P0 (Broken)** | 0 | None |
| **P1 (Incomplete)** | 3 | P1-A: errorMessage never displayed, P1-B: direct text 409 retry missing, P1-C: group attachments dropped |
| **P2 (Inconsistent)** | 3 | P2-A: dead AgentPicker file, P2-B: onerror cleanup, P2-C: group text delay |

**Loop continues**: 3 P1 issues require fixes before the review loop can terminate.
