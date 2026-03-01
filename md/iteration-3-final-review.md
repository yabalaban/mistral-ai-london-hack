# Iteration 3 — Final Review

## Fix Verification

### P1-A: Error toast in Shell.tsx — VERIFIED

**File**: `frontend/src/components/layout/Shell.tsx`

The fix is correctly implemented:

1. **Signal import**: `errorMessage` is imported from `../../state/ui.ts`, which exports `signal<string | null>(null)` — correct Preact signal usage.
2. **Reactive read**: `const error = errorMessage.value` reads the signal value inside the component body, which ensures Preact re-renders when it changes. This is the standard Preact Signals pattern for component-level reactivity.
3. **Auto-dismiss**: `useEffect` with `[error]` dependency sets a 5-second `setTimeout` that clears `errorMessage.value = null`. The cleanup function calls `clearTimeout`, preventing stale timers on rapid error succession.
4. **Close button**: The dismiss button sets `errorMessage.value = null` on click with an accessible `aria-label`.
5. **Conditional render**: `{error && (...)}` correctly hides the toast when null.
6. **Styling**: Fixed-position red banner at bottom-center with proper z-index, max-width constraint, and responsive width.

**Signal reactivity concern**: Reading `.value` inside the component body (not inside a `computed()` or `effect()`) is the correct pattern for Preact components with `@preact/signals`. The signal integration auto-subscribes the component to re-render when the signal changes. No issue here.

### P1-B: 409 retry in `_stream_agent_response` — VERIFIED

**File**: `backend/src/ensemble/api/ws.py` (lines 950-1002)

The fix is correctly implemented:

1. **Retry loop**: `for attempt in range(max_retries)` with `max_retries = 3` wraps the entire Mistral API call block (both `start_stream_async` and `append_stream_async` paths).
2. **Success break**: `break` on line 990 correctly exits the retry loop after successful stream consumption. This is placed after the `async for event in stream:` loop completes, meaning the entire stream was consumed successfully before breaking.
3. **409 detection**: `"409" in str(exc)` matches the same pattern used in all other retry sites (oracle engine's `_run_sequential`, `_stream_to_queue`, `_stream_single_agent`, and the voice session's `_direct_voice_response`).
4. **Backoff**: `1.0 * (attempt + 1)` gives 1s, 2s, 3s delays — consistent with all other retry sites.
5. **Final attempt re-raises**: `attempt < max_retries - 1` guard ensures the last attempt re-raises the exception rather than silently swallowing it.
6. **Non-409 errors re-raise immediately**: The `else: raise` clause ensures non-409 exceptions propagate without retry.

**No new issues**: The retry loop correctly wraps the stream open AND consumption. State variables (`full_text`, `has_function_call`, `msg_id`) are initialized before the loop and accumulate correctly across retries (though in practice a retry only happens when the first call fails, so no partial state carries over).

### P1-C: Attachments in `_format_history` — VERIFIED

**File**: `backend/src/ensemble/oracle/engine.py` (lines 471-501)

The fix is correctly implemented:

1. **Attachment counting**: `sum(1 for a in msg.attachments if a.type == "image")` correctly counts only image attachments.
2. **Singular/plural**: `"[Image attached]"` for 1 image, `"[N images attached]"` for N > 1.
3. **Zero attachments — no regression**: When `msg.attachments` is an empty list (the default per the `Message` model), `img_count` is 0, neither `if` branch triggers, and `attachment_suffix` stays `""`. The formatted line is identical to pre-fix behavior.
4. **Suffix placement**: Appended after `msg.content` (user messages) or `msg.content[:400]` (agent messages), which is the natural reading position.
5. **Both roles handled**: The suffix is applied to both USER and AGENT messages, which is correct — if a user attached images, agents should know; if an agent's tool generated images in a prior turn, subsequent agents should also be aware.

## P0 Issues

**None found.** All P0 issues from iteration 1 (XSS, dead code removal, voice delay bypass) remain correctly fixed:

- `Markdown.tsx` still uses `DOMPurify.sanitize()` around `marked.parse()` output.
- The legacy `_handle_audio` method is gone; unknown message types hit the `else` error clause.
- `_send()` has `skip_delay` parameter, and voice paths use it.

## P1 Issues

**None found.** All P1 issues across both iterations are verified:

| ID | Issue | Status |
|---|---|---|
| P1-1 | AgentPicker onSelect does nothing | Fixed — removed misleading UI |
| P1-2 | discardStream() never called | Fixed — `clearStreamingAgents()` on close/error |
| P1-3 | No WS error event display | Fixed — `errorMessage` signal + Shell toast (P1-A) |
| P1-4 | WS reconnect state re-sync | Fixed — fetches conversation on reconnect |
| P1-6 | create_slides blocks event loop | Fixed — `asyncio.to_thread()` wrapper |
| P1-7 | No 409 retry in group text | Fixed — retry in oracle engine (3 sites) |
| P1-8 | AgentVerdict missing 'interrupted' | Fixed — added to union type |
| P1-9 | Direct chat blocks WS read loop | Fixed — background task with cancellation |
| P1-A | Error toast not rendered | Fixed — Shell.tsx inline toast |
| P1-B | No 409 retry in direct text | Fixed — `_stream_agent_response` retry loop |
| P1-C | Image attachments invisible in group prompts | Fixed — `_format_history` attachment suffix |

**No new issues introduced by iteration 2 fixes:**

- The Shell toast uses standard Preact patterns and does not introduce memory leaks (timer is cleaned up).
- The retry loop in `_stream_agent_response` has no state corruption risk — on retry, the stream open simply happens again from scratch.
- The `_format_history` change is additive (appending a suffix) and does not alter any existing behavior for messages without attachments.

## Remaining P2/P3 Issues (Acceptable)

The following were deliberately not fixed and remain at appropriate severity levels:

| ID | Issue | Severity | Rationale |
|---|---|---|---|
| P2-2 | Artificial delay inconsistency (text vs voice) | P2 | Partially addressed by P0-3's `skip_delay` for voice. The text delay in `_send()` is a UX choice, not a bug. |
| P2-4 | Mock data inconsistency | P2 | Cosmetic — no functional impact. |
| P2-5 | Oracle event type naming (`oracle_reasoning` vs `oracle`) | P2 | Internal naming convention, not user-facing. Both sides handle it consistently. |
| P2-7 | `message_partial` not handled in text group path | P2 | The text group path uses `message_complete` and `message_chunk` which are handled. `message_partial` is only emitted in voice group path and is handled in the WS dispatcher. No functional gap. |
| P2-8 | Tool use not implemented in group conversations | P2 | Known limitation — group tool calls would require significant architecture work (oracle would need to coordinate tool execution across agents). Acceptable for current scope. |
| P3 | Various cleanup items | P3 | Code style, naming, minor refactors — no functional impact. |

None of these have escalated in severity. They remain appropriate as future cleanup work.

## Conclusion

**The review loop should TERMINATE.**

All P0 and P1 issues identified across both review iterations have been fixed and verified. The iteration 2 fixes are correctly implemented, introduce no regressions, and follow established patterns in the codebase. The remaining P2/P3 items are appropriately triaged and do not warrant blocking.

The codebase is in a sound state for its scope: the XSS vulnerability is mitigated, error handling is consistent (409 retries in all Mistral API call sites, error display in the UI, streaming cleanup on disconnect), and the voice pipeline correctly bypasses artificial delays.
