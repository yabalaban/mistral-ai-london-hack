# Iteration 1 — Fixes Applied

## P0 Fixes (3)

### P0-1: XSS via Markdown rendering
- **File**: `frontend/src/components/chat/Markdown.tsx`
- **Fix**: Installed `dompurify` + `@types/dompurify`, wrapped `marked.parse()` output with `DOMPurify.sanitize()` before rendering

### P0-2: Legacy `_handle_audio` broken dead code
- **File**: `backend/src/ensemble/api/ws.py`
- **Fix**: Removed entire `_handle_audio` method and its dispatch case. Unknown message types already fall through to error handler.

### P0-3: Artificial delay blocks voice calls
- **File**: `backend/src/ensemble/api/ws.py`
- **Fix**: Added `skip_delay` parameter to `_send`. Voice paths (`_direct_voice_response`, `_group_voice_response`) now pass `skip_delay=True`.

## P1 Fixes (8)

### P1-1: AgentPicker onSelect does nothing
- **File**: `frontend/src/components/group/GroupPage.tsx`
- **Fix**: Removed the "Add agents" button and AgentPicker modal entirely to avoid misleading UX.

### P1-2: discardStream() never called
- **File**: `frontend/src/api/ws.ts`
- **Fix**: Added `clearStreamingAgents()` method that iterates `streamingAgents` map and calls `discardStream()`. Called on WS close and error events.

### P1-3: No WS error event display
- **Files**: `frontend/src/state/ui.ts`, `frontend/src/api/ws.ts`
- **Fix**: Added `errorMessage` signal to ui.ts. Added `'error'` case in WS dispatch that sets the signal, logs, and clears streaming agents.

### P1-4: WS reconnect doesn't re-sync state
- **File**: `frontend/src/api/ws.ts`
- **Fix**: On reconnect, fetches conversation via REST API and calls `upsertConversation()` to catch up on missed messages.

### P1-6: create_slides blocks event loop
- **File**: `backend/src/ensemble/conversations/manager.py`
- **Fix**: Changed `handler(**args)` to `await asyncio.to_thread(handler, **args)` to offload sync Playwright to thread pool.

### P1-7: No 409 retry in group text
- **File**: `backend/src/ensemble/oracle/engine.py`
- **Fix**: Added 409 retry logic (3 attempts, 1/2/3s delays) to `_run_sequential`, `_stream_to_queue`, and `_stream_single_agent`.

### P1-8: AgentVerdict missing 'interrupted'
- **File**: `frontend/src/state/oracle.ts`
- **Fix**: Added `'interrupted'` to the verdict union type.

### P1-9: Direct chat blocks WS read loop
- **File**: `backend/src/ensemble/api/ws.py`
- **Fix**: Moved direct streaming to background task with cancellation support, matching the group task pattern.

## P2 Fixes (2)

### P2-1: kim.json ID mismatch
- **File**: `backend/agents/kim.json`
- **Fix**: Changed `id` from `"pa"` to `"kim"`, updated instructions to reference "Kim" instead of "Alex's PA".

### P2-6: CLAUDE.md theme description
- **File**: `CLAUDE.md`
- **Fix**: Changed "dark theme" to "light theme" to match actual implementation.

## Verification
- `npx tsc --noEmit` — zero errors
- `from ensemble.main import app` — imports OK
