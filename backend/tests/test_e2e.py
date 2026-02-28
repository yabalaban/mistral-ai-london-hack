"""End-to-end tests against Mistral API.

Run: cd backend && PYTHONPATH=src uv run python tests/test_e2e.py
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from mistralai import Mistral  # noqa: E402
from mistralai.models import CodeInterpreterTool, WebSearchTool  # noqa: E402

from ensemble.config import settings  # noqa: E402

PASSED = 0
FAILED = 0


def report(name: str, ok: bool, detail: str = ""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        print(f"  ❌ {name}: {detail}")


async def test_agent_lifecycle(client: Mistral):
    """Test create → get → update → delete agent."""
    print("\n=== Test: Agent Lifecycle ===")

    agent = await client.beta.agents.create_async(
        model="mistral-small-latest",
        name="Lifecycle Test",
        instructions="You are a test bot.",
        description="Testing lifecycle.",
    )
    report("create agent", agent.id is not None, str(agent))

    fetched = await client.beta.agents.get_async(agent_id=agent.id)
    report("get agent", fetched.name == "Lifecycle Test", fetched.name)

    updated = await client.beta.agents.update_async(
        agent_id=agent.id,
        name="Lifecycle Test Updated",
    )
    report("update agent", updated.name == "Lifecycle Test Updated", updated.name)

    await client.beta.agents.delete_async(agent_id=agent.id)
    try:
        await client.beta.agents.get_async(agent_id=agent.id)
        report("delete agent", False, "agent still exists")
    except Exception:
        report("delete agent", True)


async def test_conversation_persistence(client: Mistral):
    """Test that conversation maintains context across appends."""
    print("\n=== Test: Conversation Persistence ===")

    agent = await client.beta.agents.create_async(
        model="mistral-small-latest",
        name="Memory Bot",
        instructions="You are a helpful bot. Remember everything the user tells you. Be concise.",
    )

    try:
        conv = await client.beta.conversations.start_async(
            agent_id=agent.id,
            inputs="My favorite color is turquoise. Just acknowledge this.",
        )
        report("start conversation", conv.conversation_id is not None)

        reply1 = _extract_text(conv)
        report("first reply not empty", len(reply1) > 0, f"got: '{reply1}'")

        conv2 = await client.beta.conversations.append_async(
            conversation_id=conv.conversation_id,
            inputs="What is my favorite color?",
        )
        reply2 = _extract_text(conv2)
        report(
            "remembers context",
            "turquoise" in reply2.lower(),
            f"got: '{reply2}'",
        )

        # Same conversation ID should persist
        report(
            "conversation ID stable",
            conv2.conversation_id == conv.conversation_id,
            f"{conv2.conversation_id} != {conv.conversation_id}",
        )

        await client.beta.conversations.delete_async(
            conversation_id=conv.conversation_id
        )
        report("delete conversation", True)
    finally:
        await client.beta.agents.delete_async(agent_id=agent.id)


async def test_agent_with_tools(client: Mistral):
    """Test agent creation with built-in tools."""
    print("\n=== Test: Agent with Tools ===")

    agent = await client.beta.agents.create_async(
        model="mistral-small-latest",
        name="Tool Bot",
        instructions="You can run code and search the web.",
        tools=[
            CodeInterpreterTool(type="code_interpreter"),
            WebSearchTool(type="web_search"),
        ],
    )
    report("create agent with tools", agent.id is not None)

    fetched = await client.beta.agents.get_async(agent_id=agent.id)
    report("agent has tools", fetched.tools is not None and len(fetched.tools) > 0)

    await client.beta.agents.delete_async(agent_id=agent.id)
    report("cleanup", True)


async def test_code_interpreter(client: Mistral):
    """Test that code interpreter actually executes code."""
    print("\n=== Test: Code Interpreter Execution ===")

    agent = await client.beta.agents.create_async(
        model="mistral-small-latest",
        name="Code Runner",
        instructions="When asked to compute something, always use the code interpreter. Be concise.",
        tools=[CodeInterpreterTool(type="code_interpreter")],
    )

    try:
        conv = await client.beta.conversations.start_async(
            agent_id=agent.id,
            inputs="Calculate 17 * 31 using code. Just give me the number.",
        )
        reply = _extract_text(conv)
        report("code interpreter runs", "527" in reply, f"got: '{reply}'")

        # Check if there was a tool execution output
        has_tool = any(
            hasattr(o, "type") and getattr(o, "type", None) == "tool.execution"
            for o in conv.outputs
        )
        report("tool execution entry present", has_tool)

        await client.beta.conversations.delete_async(
            conversation_id=conv.conversation_id
        )
    finally:
        await client.beta.agents.delete_async(agent_id=agent.id)


async def test_vision_multimodal(client: Mistral):
    """Test vision capability with a base64 image."""
    print("\n=== Test: Vision / Multimodal ===")

    import base64
    import httpx

    # Download a chess image and base64 encode it
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            "https://images.unsplash.com/photo-1528819622765-d6bcf132f793?w=320"
        )
        img_b64 = base64.b64encode(resp.content).decode()

    agent = await client.beta.agents.create_async(
        model="mistral-medium-latest",
        name="Vision Bot",
        instructions="Describe images concisely.",
    )

    try:
        conv = await client.beta.conversations.start_async(
            agent_id=agent.id,
            inputs=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What do you see in this image? One sentence."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_b64}"
                            },
                        },
                    ],
                }
            ],
        )
        reply = _extract_text(conv)
        report("vision reply not empty", len(reply) > 0, f"got: '{reply}'")
        report(
            "recognizes chess",
            any(w in reply.lower() for w in ["chess", "king", "piece", "board", "game"]),
            f"got: '{reply}'",
        )

        await client.beta.conversations.delete_async(
            conversation_id=conv.conversation_id
        )
    finally:
        await client.beta.agents.delete_async(agent_id=agent.id)


async def test_multiple_agents_conversation(client: Mistral):
    """Test oracle pattern: multiple agents with separate conversations."""
    print("\n=== Test: Multi-Agent Oracle Pattern ===")

    agent1 = await client.beta.agents.create_async(
        model="mistral-small-latest",
        name="Agent Alpha",
        instructions="You are Alpha, a cheerful optimist. Keep responses to one sentence.",
    )
    agent2 = await client.beta.agents.create_async(
        model="mistral-small-latest",
        name="Agent Beta",
        instructions="You are Beta, a cautious realist. Keep responses to one sentence.",
    )

    try:
        topic = "Should we build a startup?"

        # Agent 1 responds
        conv1 = await client.beta.conversations.start_async(
            agent_id=agent1.id,
            inputs=f"[Group discussion] User asks: {topic}\nIt's your turn. Respond as Alpha.",
        )
        reply1 = _extract_text(conv1)
        report("agent1 responds", len(reply1) > 0, f"got: '{reply1}'")

        # Agent 2 responds with context of Agent 1's reply
        conv2 = await client.beta.conversations.start_async(
            agent_id=agent2.id,
            inputs=f"[Group discussion] User asks: {topic}\nAlpha said: {reply1}\nIt's your turn. Respond as Beta.",
        )
        reply2 = _extract_text(conv2)
        report("agent2 responds", len(reply2) > 0, f"got: '{reply2}'")

        # Verify they have different personalities
        report(
            "different responses",
            reply1.strip() != reply2.strip(),
            "identical replies",
        )

        # Continue — Agent 1 reacts to Agent 2
        conv1b = await client.beta.conversations.append_async(
            conversation_id=conv1.conversation_id,
            inputs=f"Beta responded: {reply2}\nReact to Beta's point.",
        )
        reply1b = _extract_text(conv1b)
        report("agent1 continues with context", len(reply1b) > 0, f"got: '{reply1b}'")

        await client.beta.conversations.delete_async(conversation_id=conv1.conversation_id)
        await client.beta.conversations.delete_async(conversation_id=conv2.conversation_id)
        report("cleanup conversations", True)
    finally:
        await client.beta.agents.delete_async(agent_id=agent1.id)
        await client.beta.agents.delete_async(agent_id=agent2.id)
        report("cleanup agents", True)


async def test_oracle_json_routing(client: Mistral):
    """Test oracle-style JSON routing decision."""
    print("\n=== Test: Oracle JSON Routing ===")

    try:
        response = await client.chat.complete_async(
            model="mistral-small-latest",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a conversation orchestrator. Given participants and context, "
                        "decide who speaks next. Respond ONLY with JSON: "
                        '{"next_speaker": "<id>", "hint": "<optional>"}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Participants:\n"
                        "- emma: Software Engineer\n"
                        "- sofia: Business Strategist\n\n"
                        "User asked: 'What's the market size for AI tutoring?'\n"
                        "Who should answer first?"
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        import json

        text = response.choices[0].message.content.strip()
        data = json.loads(text)
        report("oracle returns valid JSON", "next_speaker" in data, f"got: {data}")
        report(
            "oracle picks reasonable speaker",
            data["next_speaker"] in ("emma", "sofia"),
            f"got: {data['next_speaker']}",
        )
    except Exception as e:
        report("oracle routing", False, str(e))


async def test_agent_personality(client: Mistral):
    """Test that agent personality comes through."""
    print("\n=== Test: Agent Personality ===")

    agent = await client.beta.agents.create_async(
        model="mistral-small-latest",
        name="Pirate Pete",
        instructions=(
            "You are Pirate Pete. You ALWAYS speak like a pirate. "
            "Use words like 'arr', 'matey', 'ye', 'treasure'. "
            "Keep responses to one sentence."
        ),
    )

    try:
        conv = await client.beta.conversations.start_async(
            agent_id=agent.id,
            inputs="Tell me about your day.",
        )
        reply = _extract_text(conv)
        pirate_words = ["arr", "matey", "ye", "treasure", "sea", "ship", "sail", "ahoy"]
        has_pirate = any(w in reply.lower() for w in pirate_words)
        report("personality comes through", has_pirate, f"got: '{reply}'")

        await client.beta.conversations.delete_async(
            conversation_id=conv.conversation_id
        )
    finally:
        await client.beta.agents.delete_async(agent_id=agent.id)


async def test_full_server_flow(client: Mistral):
    """Test the full registry → conversation manager → oracle flow."""
    print("\n=== Test: Full Server Flow (Registry + Manager + Oracle) ===")

    from ensemble.agents.registry import AgentRegistry
    from ensemble.conversations.manager import ConversationManager
    from ensemble.conversations.models import ConversationType
    from ensemble.oracle.engine import OracleEngine

    registry = AgentRegistry(client)
    registry.load_profiles(Path(__file__).parent.parent / "agents")
    report("load profiles", len(registry.agents) >= 5, f"loaded {len(registry.agents)}")

    await registry.sync_to_mistral()
    synced = sum(1 for a in registry.agents.values() if a.mistral_agent_id)
    report("sync to mistral", synced == len(registry.agents), f"{synced}/{len(registry.agents)}")

    try:
        # Test direct conversation
        mgr = ConversationManager(client, registry)
        conv = mgr.create(ConversationType.DIRECT, ["emma"])
        report("create direct conversation", conv.id is not None)

        reply = await mgr.send_direct_message(conv.id, "What's the best programming language?")
        report("direct message reply", len(reply.content) > 0, f"got: '{reply.content[:80]}'")

        # Test group conversation with oracle
        oracle = OracleEngine(client, registry)
        group = mgr.create(ConversationType.GROUP, ["emma", "dan", "sofia"])
        report("create group conversation", group.id is not None)

        replies = await oracle.run_group_turn(
            group,
            "We need to build an MVP for a chess tutoring app. What should we focus on?",
            max_rounds=3,
        )
        report("oracle group turn", len(replies) == 3, f"got {len(replies)} replies")

        for r in replies:
            report(
                f"  {r.agent_id} responded",
                len(r.content) > 0,
                f"'{r.content[:60]}'",
            )

        # Verify messages are recorded
        report(
            "messages recorded",
            len(group.messages) == 4,  # 1 user + 3 agent
            f"got {len(group.messages)} messages",
        )

    finally:
        await registry.cleanup_mistral()
        report("cleanup all mistral agents", True)


def _extract_text(response) -> str:
    for output in response.outputs:
        if hasattr(output, "content") and hasattr(output, "role"):
            content = output.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = []
                for c in content:
                    if isinstance(c, dict):
                        texts.append(c.get("text", ""))
                    elif hasattr(c, "text"):
                        texts.append(getattr(c, "text", "") or "")
                return "".join(texts)
            # Could be a structured object with .text
            if hasattr(content, "text"):
                return content.text or ""
            return str(content)
    return ""


async def main():
    client = Mistral(api_key=settings.mistral_api_key)

    tests = [
        test_agent_lifecycle,
        test_conversation_persistence,
        test_agent_with_tools,
        test_code_interpreter,
        test_agent_personality,
        test_oracle_json_routing,
        test_vision_multimodal,
        test_multiple_agents_conversation,
        test_full_server_flow,
    ]

    for test in tests:
        try:
            await test(client)
        except Exception:
            global FAILED
            FAILED += 1
            print(f"  💥 {test.__name__} CRASHED:")
            traceback.print_exc()

    print(f"\n{'='*50}")
    print(f"Results: {PASSED} passed, {FAILED} failed")
    print(f"{'='*50}")
    return FAILED == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
