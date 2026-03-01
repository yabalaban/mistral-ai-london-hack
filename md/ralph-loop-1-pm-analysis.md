# Circles Platform -- PM Gap Analysis (Ralph Loop 1)

**Date:** 2026-03-01
**Scope:** End-to-end audit of both frontends (Discord bot + Preact web app), backend, and agent configuration against the six product requirements.

---

## 1. Product Scorecard

### Requirement 1: Users can add new agents with specified personalities and communicate with them through text and voice on Discord

**Rating: PARTIAL**

**What works:**
- **Agent creation via web frontend:** `CreateAgentModal` (`/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/roster/CreateAgentModal.tsx`) supports template selection and custom agent creation with name, role, bio, personality, and instructions fields. The `POST /api/agents` endpoint (`/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/routes.py`, lines 58-91) creates the agent and syncs it to Mistral.
- **Five agent profiles exist:** emma, dan, sofia, marcus, kim -- each with distinct personalities, roles, voice IDs, and tools. All in `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/agents/*.json`.
- **Discord text communication works:** `discord_bot.py` handles both channel-level group messages (line 368-425) and per-agent thread 1:1 messages (lines 427-473). Webhooks impersonate agents (correct name, avatar, role display).
- **Discord voice pipeline exists:** `discord_voice.py` implements ElevenLabs realtime STT with mute-to-commit, and TTS playback via FFmpeg. The bot auto-joins voice channels (lines 227-253 in `discord_bot.py`).
- **Slash commands implemented:** `/agents`, `/init`, `/invite`, `/dismiss`, `/reset`, `/topic`, `/hangup`, `/who` -- comprehensive channel management.

**What is missing or broken:**
- **No Discord command to create agents.** Users can only add agents via the web frontend or by dropping a JSON file in `backend/agents/`. There is no `/create_agent` slash command. Agents created via the web API are not persisted to disk -- they vanish on restart.
- **Voice reliability is uncertain.** The `audioop` module is used for resampling (line 36-41 in `discord_voice.py`) and requires `audioop-lts` on Python 3.13+ (listed in `pyproject.toml`). The ElevenLabs SDK's realtime STT depends on commit semantics tied to Discord mute/unmute events -- this is fragile (e.g., if the user never mutes, no transcript is committed).
- **Agent threads are channel-local.** If the bot restarts, `_channels` state is lost (line 166 in `discord_bot.py`) and thread mappings break. The bot would need to rediscover threads or reinitialize with `/init`.

### Requirement 2: Use Mistral API and ElevenLabs API, optimised for conversation

**Rating: WORKING**

**What works:**
- **Mistral Conversations API (beta):** Used correctly throughout. `start_stream_async` for first messages, `append_stream_async` for continuations (`/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/ws.py`, lines 954-965; `oracle/engine.py`, lines 940-957). Conversation IDs tracked per-agent in `conv.mistral_conversation_ids`.
- **Streaming everywhere:** Both direct and group responses use streaming for low-latency first-token delivery.
- **409 Conflict retry logic:** Implemented in all streaming paths (3 retries with backoff). This handles Mistral's conversation lock contention.
- **ElevenLabs TTS -- dual mode:** Batch synthesis via SDK (`tts.py`, `synthesize()`) for Discord; WebSocket streaming (`TTSWebSocket`) for web frontend with aggressive chunk scheduling (`chunk_length_schedule: [20, 50, 80, 120]`) and 1.15x speed.
- **ElevenLabs STT -- realtime:** `RealtimeSTTSession` (`stt.py`) uses `scribe_v2_realtime` with `CommitStrategy.MANUAL` for PTT and `CommitStrategy.VAD` option.
- **Voice mode brevity prefix:** `VOICE_MODE_PREFIX` applied to agent inputs during voice to keep responses short (1-2 sentences).
- **Oracle model choice:** `ministral-14b-2512` (`config.py`, line 42) used for oracle decisions -- a small, fast model appropriate for classification and routing tasks.
- **Agent models:** All agents use `mistral-large-2512` -- the latest large model.

**Minor issues:**
- The `message_complete` event adds an artificial delay based on content length (ws.py, lines 1051-1056: `delay = min(max(len(content) * 0.004, 0.5), 2.5)`). This is intentional UX but could feel slow for short messages.

### Requirement 3: Agents must do simple tool use and return images or slides (PDF) based on data

**Rating: PARTIAL**

**What works:**
- **Slides tool is fully implemented:** `create_slides` in `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/tools/slides.py` generates Reveal.js HTML presentations with proper styling, and renders PDF via Playwright/Chromium. API endpoints serve both HTML (`GET /api/slides/{id}`) and PDF (`GET /api/slides/{id}/pdf`).
- **Tool schema registered correctly:** `SLIDES_TOOL_SCHEMA` is a proper Mistral function tool. `BUILT_IN_TOOLS` in registry.py maps `code_interpreter`, `web_search`, `image_generation`, and `create_slides`.
- **Function call handling works for direct chats:** `_handle_function_calls` in `manager.py` (lines 139-198) correctly loops through function calls, executes handlers, and sends results back via `FunctionResultEntry`.
- **Kim agent configured with `create_slides` + `image_generation` tools.** Instructions explicitly say "use the create_slides tool" and "use image_generation."
- **Emma has `code_interpreter`; Sofia has `web_search`.**

**What is broken or missing:**
- **Tool use in group/oracle streaming path is NOT handled.** In `oracle/engine.py`, the sequential and parallel runners use `start_stream_async`/`append_stream_async` but never check for `FunctionCall` events in the stream. If an agent tries to use a tool during a group conversation, the function call will be silently ignored. Only the Discord bot's `_stream_agent` method (discord_bot.py, lines 556-592) attempts to handle function calls after streaming, but this is a hacky workaround ("Please proceed with the tool call.").
- **Image generation results are not surfaced to the user.** The `image_generation` tool is a Mistral built-in (not a local function tool), so there is no local handler in `TOOL_HANDLERS`. Mistral may handle it server-side, but there is no code to extract and display generated images from the response. The web frontend has no image rendering for tool-generated images in group chat.
- **No `code_interpreter` result rendering.** Code interpreter is a Mistral built-in, but execution results (stdout, images) are not extracted or displayed in any special way.
- **Slides are not embedded in Discord.** When Kim creates slides in a Discord channel, only the text response is posted. The slides URL is a relative path (`/api/slides/{id}`) -- not accessible from Discord since Discord users are not on the web frontend.

### Requirement 4: Oracle agent steers conversation between agents for clear group experience

**Rating: WORKING**

**What works:**
- **Complete oracle pipeline:** The `OracleEngine` (`/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/oracle/engine.py`) implements a full orchestration loop:
  1. Topic grading -- extracts discussion topic from user messages (lines 309-335)
  2. Message classification -- parallel (casual) vs sequential (substantive) (lines 249-273)
  3. Goal inference -- concise evaluable goal from user message
  4. Agent ranking -- LLM-ranked relevance with hints, filtering non-relevant agents (lines 337-404)
  5. Directed message detection -- "Hey Emma, ..." bypasses oracle, routes to single agent (lines 453-469)
  6. Sequential/parallel execution with streaming (lines 831-1264)
  7. [PASS] detection -- agents can opt out if nothing to add (line 80-83)
  8. Grader loop -- evaluates goal completion, loops up to 10 rounds (lines 275-307)
  9. Summary generation -- 2-3 bullet points after multi-agent rounds (lines 1399-1430)
  10. Voice interruption -- checks every 2 sentences if current speaker should be cut off (lines 406-449)
- **Reply threading:** Agents respond with `[N]` prefix to reference specific messages, parsed by `_parse_reply_target` (lines 86-99).
- **Discord and web frontend both use the same oracle:** `run_group_turn_streaming` is used in both `discord_bot.py` (line 492) and `ws.py` (line 830).
- **Oracle events streamed to frontend:** `oracle_start`, `oracle_reasoning`, `grader`, `agent_verdict`, `summary`, `oracle_end` -- all forwarded via WebSocket.

**Minor issues:**
- Oracle makes multiple LLM calls per user message (classifier + ranker + per-agent streaming + grader + optional topic grader + optional summary). This can be slow for casual messages. Parallel mode helps but still requires classifier + ranker overhead.

### Requirement 5: Topic identified by user; casual or specific. Specific topics conclude to meaningful milestones

**Rating: WORKING**

**What works:**
- **Automatic topic detection:** `grade_topic()` (engine.py, lines 309-335) uses LLM to identify when user messages contain a substantive topic vs casual chat. Topic is stored on the conversation object.
- **Casual vs specific classification:** The classifier prompt (lines 104-117) distinguishes "parallel" (casual/social) from "sequential" (substantive). Casual messages get a simple goal ("greet the user") and typically finish in one round. Substantive messages get evaluable goals.
- **Goal-driven grading:** The grader (lines 119-135) evaluates whether the conversation has achieved the user's goal. For parallel mode, it finishes after one round. For sequential mode, it checks if critical aspects are addressed and only continues if clearly unfinished.
- **Round loop with MAX_ROUNDS = 10:** Conversations can go up to 10 rounds for complex topics, with the grader deciding when to stop.
- **Summary as milestone:** After multi-agent rounds, a summary is generated (lines 1399-1430) capturing key decisions, disagreements, and action items. This is stored as `conversation.last_summary` and used as context for subsequent rounds.
- **Discord /topic command:** Users can explicitly set topics via slash command (discord_bot.py, lines 717-726).

**Minor issues:**
- There is no explicit "conclusion" or "milestone reached" notification. The summary serves this purpose but it is not framed as a conclusion. The grader just says "done" -- there is no "here is what we decided" moment.
- Topic persists across messages. Once set, it only updates if a new topic is detected. There is no way to clear a topic on the web frontend (Discord has `/topic`).

### Requirement 6: Frontend for agent management and multiturn observability (oracle logs/monitors)

**Rating: WORKING**

**What works:**
- **Agent management UI:** `RosterPage` (`/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/roster/RosterPage.tsx`) shows all agents in a grid with cards. `CreateAgentModal` supports template-based and blank agent creation. `AgentCard` allows starting 1:1 chats (clicking) and deleting agents (X button). Backend supports full CRUD: `POST /api/agents`, `PATCH /api/agents/{id}`, `DELETE /api/agents/{id}`.
- **Oracle Monitor:** `OracleMonitor` (`/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/components/oracle/OracleMonitor.tsx`) is a real-time dashboard showing:
  - Active/idle status with animated indicator
  - Current goal and topic
  - Directed message detection
  - Per-round: speaker rankings (who responds, who is silent), hints, reasoning
  - Verdict badges per agent: responded, passed, skipped, filtered, interrupted
  - Grader results: complete/continue with reasoning
  - Summary display
- **Oracle state management:** `oracle.ts` (`/Users/blbn/Documents/projects/mistral-ai-london-hack/frontend/src/state/oracle.ts`) provides signal-based state with full lifecycle: `startOracle`, `addRound`, `addVerdictToCurrentRound`, `setGraderResult`, `setOracleSummary`, `endOracle`.
- **WebSocket event dispatch:** All oracle events (`oracle_start`, `oracle_reasoning`, `grader`, `agent_verdict`, `summary`, `oracle_end`) are wired from the WS handler to the oracle state.

**Minor issues:**
- No persistent logs. Oracle state resets on each new user message (`startOracle` clears rounds). There is no history of past oracle decisions -- you can only see the current/most recent round.
- The turn logger (`turn_logger.py`) writes logs to disk but the web frontend has no way to browse them.

---

## 2. Critical Path to "Working"

For a demonstrable end-to-end product at a hackathon demo, these items are in priority order:

### P0: Must work for the demo

1. **Tool use in group conversations (oracle path).** Currently, if Kim is asked to create slides in a group chat, the function call is silently dropped. This is the most visible gap because slides/images are a key demo feature. Fix: Add function call detection and handling in `_run_sequential` and `_stream_to_queue` in `oracle/engine.py`, similar to how `ws.py`'s `_stream_agent_response` handles it (lines 1004-1023).

2. **Discord bot starts and connects successfully.** Verify the bot token and guild ID in `.env` are valid, and that `py-cord` with voice dependencies (`PyNaCl`, `audioop-lts`) installs cleanly on the demo machine. The bot needs working permissions (manage webhooks, create threads, join voice).

3. **Slides URL accessible from Discord.** Currently returns `/api/slides/{id}` which is a relative URL only accessible on the web frontend. For Discord, this needs to be an absolute URL (e.g., `http://host:8000/api/slides/{id}`).

### P1: Should work for the demo

4. **Agent creation persists to disk.** Agents created via the web frontend or a Discord command should be written to `backend/agents/*.json` so they survive restarts. Currently they only live in memory.

5. **Image generation results displayed.** When an agent uses `image_generation`, the generated image URL should be surfaced in the response -- both in Discord (as an embed) and on the web frontend (inline in the message).

6. **Discord `/create_agent` slash command.** Users should be able to create agents from Discord, not just the web UI.

### P2: Nice to have for the demo

7. **Topic clear/reset on web frontend.** Currently only Discord has `/topic`.
8. **Oracle decision history.** Keep past rounds visible so the observer can scroll back.

---

## 3. Product Gaps

### Gap 1: Tool use broken in group conversations
- **Impact:** HIGH -- slides and images are a headline feature
- **Location:** `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/oracle/engine.py`, `_run_sequential()` (line 973 onwards) and `_stream_to_queue()` (line 1192 onwards)
- **Problem:** The streaming code only checks for `content` events and `conversation_id` events. It never checks for `FunctionCall` events. When an agent triggers a function call, the call is silently ignored, and the agent's text response (which may say "I'll create slides now") is delivered without any actual tool execution.
- **Fix:** After streaming completes, check if `full_text` is empty or if function calls were detected (track via `has_function_call` flag like in `ws.py`). If so, call `_handle_function_calls` from `manager.py` to execute the tools and get the final response.

### Gap 2: No agent persistence
- **Impact:** MEDIUM -- agents vanish on restart
- **Location:** `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/api/routes.py`, `create_agent()` (line 58)
- **Problem:** `_registry.add_agent()` only adds to the in-memory dict. No JSON file is written.
- **Fix:** After creating the agent, write the profile to `backend/agents/{agent_id}.json`.

### Gap 3: Slides URL not usable from Discord
- **Impact:** MEDIUM -- slides feature appears broken in Discord
- **Location:** `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/tools/slides.py`, line 147
- **Problem:** Returns relative URL `/api/slides/{id}` which only works on the web frontend.
- **Fix:** Include the full base URL from settings/config. Or have the Discord bot detect slide URLs in responses and post them as rich embeds with a link to the web frontend.

### Gap 4: Image generation output not rendered
- **Impact:** MEDIUM -- one of the two "return images or slides" requirements
- **Location:** `image_generation` is a Mistral built-in tool, not handled locally
- **Problem:** No code extracts image URLs from Mistral's response when `image_generation` is used. The response likely contains image data or URLs in a non-text content block, but `extract_text_from_content` only extracts text.
- **Fix:** Parse image content blocks from Mistral responses and surface them as attachments.

### Gap 5: No Discord agent creation command
- **Impact:** LOW-MEDIUM -- requirement says "Users can add new agents"
- **Location:** `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/discord_bot.py`, `register_commands()` (line 600)
- **Problem:** Only web frontend can create agents. Discord users must use the web UI.
- **Fix:** Add a `/create_agent` slash command with name, role, personality options.

### Gap 6: Code interpreter results not displayed
- **Impact:** LOW -- Emma has `code_interpreter` but results are not specially rendered
- **Problem:** Code interpreter execution happens on Mistral's side. Results (stdout, generated plots) are returned in the response but may not be properly extracted or displayed.

### Gap 7: Oracle logging not browsable from frontend
- **Impact:** LOW -- requirement says "oracle logs/monitors"
- **Location:** `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/src/ensemble/oracle/turn_logger.py` exists (imported by engine.py)
- **Problem:** `log_turn()` writes to disk but the web frontend has no API to browse past oracle decisions. The `OracleMonitor` only shows the current round.

### Gap 8: `.env` contains raw API keys committed to git
- **Impact:** SECURITY -- API keys are plaintext in tracked file
- **Location:** `/Users/blbn/Documents/projects/mistral-ai-london-hack/backend/.env`
- **Problem:** `MISTRAL_API_KEY`, `ELEVENLABS_API_KEY`, `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID` are all in the `.env` file. If this repo is public or shared, keys are exposed.
- **Fix:** Add `.env` to `.gitignore`. Rotate keys if repo was ever public.

---

## 4. E2E Test Plan

### Test 1: Agent Creation via Web Frontend
- **Steps:**
  1. Open web frontend at `http://localhost:3000`
  2. Click "Add Agent" button
  3. Select "Research Assistant" template
  4. Customize name to "Alex"
  5. Click "Create Agent"
- **Expected result:** Agent card appears in roster. Agent has `web_search` tool badge.
- **Verify:** `GET /api/agents` returns the new agent with `ready: true` (Mistral agent synced).

### Test 2: 1:1 Text Chat (Web)
- **Steps:**
  1. Click on Emma's agent card
  2. Type "Hey, what do you think about microservices?"
  3. Wait for response
- **Expected result:** Response streams in character-by-character. Message appears with Emma's name and avatar. Response is concise (2-3 sentences per instructions).
- **Verify:** WebSocket sends `turn_change`, `message_chunk`(s), `message_complete` events.

### Test 3: Group Chat with Oracle (Web)
- **Steps:**
  1. Click "New Group Chat" on roster page
  2. Select Emma, Dan, and Sofia
  3. Type "Should we build a mobile app or a PWA for our startup?"
  4. Observe Oracle Monitor panel
- **Expected result:**
  - Oracle classifies as "sequential"
  - Ranker picks relevant agents (probably all three for this question)
  - Each agent responds in turn, building on previous responses
  - Grader evaluates if goal is met
  - Summary generated at the end
  - Oracle Monitor shows rounds, speakers, verdicts, grader reasoning
- **Verify:** `oracle_start`, `oracle_reasoning`, `turn_change`, `message_chunk`, `message_complete`, `grader`, `summary`, `oracle_end` events all fire.

### Test 4: Directed Message in Group
- **Steps:**
  1. In the same group chat, type "Emma, what's the technical risk?"
- **Expected result:** Only Emma responds. Oracle Monitor shows "Directed -> Emma".
- **Verify:** `oracle_start` event has `directed: true`, only one `message_complete` event.

### Test 5: Casual Message (Parallel Mode)
- **Steps:**
  1. In a group chat with Emma, Dan, Marcus, type "Hey everyone, what's up?"
- **Expected result:** All agents respond briefly (1 sentence each). Oracle classifies as "parallel". Grader finishes after one round.
- **Verify:** `oracle_reasoning` shows `mode: "parallel"`. All agents get `responded` or `passed` verdicts.

### Test 6: Slides Creation (1:1 Chat)
- **Steps:**
  1. Start 1:1 chat with Kim
  2. Type "Create a 5-slide presentation about AI trends in 2026"
  3. Wait for response
- **Expected result:** Kim's response includes a link to view the presentation and download PDF.
- **Verify:** `GET /api/slides/{id}` returns HTML with Reveal.js. `GET /api/slides/{id}/pdf` returns a valid PDF.

### Test 7: Slides Creation (Group Chat) -- EXPECTED TO FAIL
- **Steps:**
  1. Create group chat with Kim and Emma
  2. Type "Kim, can you make a presentation about distributed systems?"
- **Expected result (current):** Kim says she will create slides but no slides are actually generated (function call not handled in oracle path).
- **Expected result (fixed):** Kim creates slides and includes link in response.
- **Verify:** Check `GET /api/slides` to see if a presentation was created.

### Test 8: Discord Bot Text Chat
- **Steps:**
  1. Ensure Discord bot is running (`cd backend && PYTHONPATH=src uv run python -m ensemble.discord_main`)
  2. Type a message in a text channel the bot can see
  3. Wait for agent responses via webhooks
- **Expected result:** All default agents respond via webhook (each with their own name, avatar, role). Messages appear as separate "users" in Discord.
- **Verify:** Check bot logs for "Processing group message" and webhook sends.

### Test 9: Discord 1:1 via Thread
- **Steps:**
  1. Run `/init` in the text channel
  2. Agent threads are created (e.g., "Emma" thread)
  3. Send a message in Emma's thread
- **Expected result:** Emma responds in the thread via webhook. Other agents do not respond.
- **Verify:** Bot logs show `_handle_thread_message` for the correct agent.

### Test 10: Discord Voice
- **Steps:**
  1. Join a voice channel in the same guild
  2. Bot should auto-join and post confirmation in text channel
  3. Unmute, speak a sentence, then mute
  4. Wait for transcription and agent responses
- **Expected result:** Bot joins voice. Transcription appears in text channel. Agent responds with TTS audio in the voice channel and text in the text channel.
- **Verify:** Check for "Joined voice channel", "STT committed", "TTS audio chunk" in logs.

### Test 11: Agent Deletion
- **Steps:**
  1. Hover over an agent card on web frontend
  2. Click X button
  3. Confirm deletion
- **Expected result:** Agent disappears from roster. Cannot start new conversations with it.
- **Verify:** `GET /api/agents` no longer includes the deleted agent.

### Test 12: Topic Detection
- **Steps:**
  1. Start a group chat with Emma and Sofia
  2. Type "Hi everyone" (casual, no topic)
  3. Type "Let's discuss pricing strategy for a SaaS product"
- **Expected result:** First message: no topic set. Second message: topic detected and displayed (e.g., "Pricing strategy for a SaaS product"). Oracle Monitor shows topic.
- **Verify:** `topic_set` event fires after the second message.

---

## 5. Polish Ideas

### Demo Flow Improvements

1. **Pre-loaded conversation.** Start the demo with a pre-populated group chat showing a multi-round discussion. This immediately shows the product's value without waiting for LLM responses.

2. **Oracle Monitor as a presentation feature.** During demo, have the Oracle Monitor visible on a second screen or side panel. It tells the "story" of how the system decides who speaks and why -- this is the differentiator.

3. **Conversation export.** Add a "Copy Transcript" button that exports the conversation (with agent names, timestamps) as formatted text. Useful for the demo narrative: "here's what the agents discussed."

### UX Polish

4. **Agent typing indicators in Discord.** The bot uses `channel.typing()` during processing (line 424), which is good. But it stops as soon as the first agent responds. For group chat with multiple agents, show typing for the next agent while the current one is responding.

5. **Agent avatars in Discord.** Currently uses DiceBear fallback URLs. Pre-generating or assigning consistent avatars would make the Discord experience more polished. The current URLs (`api.dicebear.com/9.x/personas/png?seed={agent.id}`) do work but are generic.

6. **Slide embed in Discord.** When Kim creates slides, post a Discord embed with the presentation title, slide count, and a clickable link to the web frontend's slide viewer. Include a thumbnail if possible.

7. **"Who's thinking" indicator in web frontend.** During group chat, show a small avatar + typing animation for the agent currently generating a response. The `turn_change` event already provides this data -- just need a visual indicator in the message list.

8. **Round separator in message list.** Between oracle rounds, insert a subtle separator showing "Round 2 -- Oracle decided to continue" to make the multi-round flow visible without needing the Oracle Monitor.

### Technical Polish

9. **Remove `message_complete` artificial delay.** The 0.5-2.5 second delay in `ws.py` (line 1053-1056) makes the UI feel sluggish. The streaming chunks already provide a natural typing cadence. Remove or make it opt-in for voice mode only.

10. **Graceful Discord reconnect.** If the bot restarts, rediscover existing agent threads by matching thread names (`"💬 {agent.name}"`) instead of creating duplicates. The code partially handles this (lines 313-330 in `discord_bot.py`) but could be more robust.

11. **Error messages in Discord.** Currently shows "Something went wrong processing that message." Add more context: which agent failed, whether it was a Mistral API error or timeout.

12. **Concurrent agent responses in Discord.** Currently, Discord group messages are processed under a per-channel lock (line 421-425), so only one user message is processed at a time. This is correct for conversation coherence but means a second user message waits for the first to fully complete (all agents respond + summary). Consider queuing messages and processing them in order without blocking the channel.

13. **Health check endpoint.** Add `GET /api/health` that reports Mistral connection status, number of loaded agents, and ElevenLabs API key presence. Useful for quick "is the backend ready?" checks before demoing.

---

## Summary

The platform is substantially built. The core loop -- user sends message, oracle classifies, agents respond with streaming, grader evaluates, summary generated -- works end-to-end on both the web frontend and Discord. Voice (STT + TTS) is implemented for both frontends. Agent management, oracle monitoring, and multi-turn observability are all present in the web UI.

The single most critical gap is **tool use in group conversations** (Gap 1). This means the headline "slides and images" demo only works in 1:1 chats with Kim, not in the group context where the oracle orchestrates. Fixing this unlocks the full demo narrative: "Ask the team to create a presentation, and Kim generates slides while Emma reviews the technical content."

The second priority is making sure the Discord bot is operational on the demo machine (dependencies, permissions, valid tokens) and that slides/images are surfaced properly in Discord (absolute URLs, embeds).

Everything else is polish. The architecture is sound and well-structured for a hackathon project.
