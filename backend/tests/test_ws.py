"""WebSocket + streaming integration test.

Starts the actual server, runs tests against it, then shuts it down.

Run: cd backend && PYTHONPATH=src uv run python tests/test_ws.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import httpx
import websockets

PASSED = 0
FAILED = 0
BASE = "http://localhost:8765"
WS_BASE = "ws://localhost:8765"


def report(name: str, ok: bool, detail: str = ""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        print(f"  ❌ {name}: {detail}")


async def wait_for_server(timeout: float = 30):
    """Wait until server is healthy."""
    async with httpx.AsyncClient() as client:
        for _ in range(int(timeout * 10)):
            try:
                resp = await client.get(f"{BASE}/health")
                if resp.status_code == 200:
                    return
            except httpx.ConnectError:
                pass
            await asyncio.sleep(0.1)
    raise TimeoutError("Server didn't start")


async def test_ws_direct_streaming():
    """Test WebSocket direct conversation with streaming."""
    print("\n=== Test: WebSocket Direct Streaming ===")

    async with httpx.AsyncClient() as client:
        # Create conversation
        resp = await client.post(
            f"{BASE}/api/conversations",
            json={"type": "direct", "participant_agent_ids": ["emma"]},
        )
        assert resp.status_code == 200, f"Create failed: {resp.text}"
        conv_id = resp.json()["id"]
        report("create conversation", True)

    # Connect WebSocket
    async with websockets.connect(f"{WS_BASE}/ws/conversations/{conv_id}") as ws:
        await ws.send(json.dumps({
            "type": "message",
            "content": "Say hello in exactly 3 words.",
        }))

        chunks = []
        done_msg = None
        while True:
            raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if raw.get("type") == "agent_message":
                if raw.get("done"):
                    done_msg = raw
                    break
                else:
                    chunks.append(raw)
            elif raw.get("type") == "error":
                report("no errors", False, raw.get("detail"))
                return

        report("received streaming chunks", len(chunks) > 0, f"got {len(chunks)} chunks")
        report("received done message", done_msg is not None)
        report("done has full text", len(done_msg["content"]) > 0, done_msg["content"][:80])
        report("agent_id is emma", done_msg["agent_id"] == "emma")


async def test_ws_group_streaming():
    """Test WebSocket group conversation with oracle + streaming."""
    print("\n=== Test: WebSocket Group Streaming ===")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE}/api/conversations",
            json={"type": "group", "participant_agent_ids": ["emma", "dan"]},
        )
        assert resp.status_code == 200
        conv_id = resp.json()["id"]
        report("create group conversation", True)

    async with websockets.connect(f"{WS_BASE}/ws/conversations/{conv_id}") as ws:
        await ws.send(json.dumps({
            "type": "message",
            "content": "What's more important: UX or performance? One sentence each.",
        }))

        turn_changes = []
        agent_dones = []

        while len(agent_dones) < 2:
            raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            if raw.get("type") == "turn_change":
                turn_changes.append(raw)
            elif raw.get("type") == "agent_message" and raw.get("done"):
                agent_dones.append(raw)
            elif raw.get("type") == "error":
                report("no errors", False, raw.get("detail"))
                return

        report("got 2 turn changes", len(turn_changes) == 2, f"got {len(turn_changes)}")
        report("got 2 done messages", len(agent_dones) == 2, f"got {len(agent_dones)}")

        agents = {d["agent_id"] for d in agent_dones}
        report("both agents spoke", agents == {"emma", "dan"}, str(agents))


async def test_ws_conversation_persistence():
    """Test that messages persist in conversation across WS messages."""
    print("\n=== Test: WebSocket Conversation Persistence ===")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE}/api/conversations",
            json={"type": "direct", "participant_agent_ids": ["emma"]},
        )
        conv_id = resp.json()["id"]

    async with websockets.connect(f"{WS_BASE}/ws/conversations/{conv_id}") as ws:
        # First message
        await ws.send(json.dumps({
            "type": "message",
            "content": "My favorite number is 42. Just acknowledge.",
        }))
        while True:
            raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if raw.get("type") == "agent_message" and raw.get("done"):
                break

        # Second message — should remember
        await ws.send(json.dumps({
            "type": "message",
            "content": "What is my favorite number?",
        }))
        while True:
            raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if raw.get("type") == "agent_message" and raw.get("done"):
                report("remembers context", "42" in raw["content"], raw["content"][:80])
                break

    # Verify via REST
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE}/api/conversations/{conv_id}")
        messages = resp.json()["messages"]
        report("messages persisted", len(messages) == 4, f"got {len(messages)}")  # 2 user + 2 agent


async def main():
    import subprocess
    import signal

    # Start server
    print("Starting server on :8765...")
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "ensemble.main:app", "--host", "0.0.0.0", "--port", "8765"],
        cwd=Path(__file__).parent.parent,
        env={
            **__import__("os").environ,
            "PYTHONPATH": str(Path(__file__).parent.parent / "src"),
        },
    )

    try:
        await wait_for_server()
        print("Server ready.\n")

        tests = [
            test_ws_direct_streaming,
            test_ws_group_streaming,
            test_ws_conversation_persistence,
        ]

        for test in tests:
            try:
                await test()
            except Exception as e:
                global FAILED
                FAILED += 1
                print(f"  💥 {test.__name__} CRASHED: {e}")
                import traceback
                traceback.print_exc()

    finally:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=15)
        print("\nServer stopped.")

    print(f"\n{'='*50}")
    print(f"Results: {PASSED} passed, {FAILED} failed")
    print(f"{'='*50}")
    return FAILED == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
