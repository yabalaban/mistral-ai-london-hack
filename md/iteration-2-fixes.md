# Iteration 2 — Fixes Applied

## P1 Fixes (3)

### P1-A: Error toast in Shell
- **File**: `frontend/src/components/layout/Shell.tsx`
- **Fix**: Added inline error toast that reads `errorMessage` signal, renders red banner at bottom of screen, auto-dismisses after 5s, has close button.

### P1-B: 409 retry in `_stream_agent_response`
- **File**: `backend/src/ensemble/api/ws.py`
- **Fix**: Wrapped Mistral API call in retry loop (3 attempts, 1/2/3s delays on 409 errors), matching pattern already used in voice and oracle paths.

### P1-C: Attachments surfaced in group chat prompts
- **File**: `backend/src/ensemble/oracle/engine.py`
- **Fix**: In `_format_history`, added `[Image attached]` / `[N images attached]` suffix to messages with image attachments so agents know images were shared.

## Verification
- `npx tsc --noEmit` — zero errors
- `from ensemble.main import app` — imports OK
