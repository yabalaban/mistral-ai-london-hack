"""Unit tests for the Ensemble backend — NO Mistral API calls.

All external dependencies (Mistral client, ElevenLabs, Playwright) are mocked.

Run: cd backend && PYTHONPATH=src uv run python -m pytest tests/test_unit.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to build mock Mistral objects
# ---------------------------------------------------------------------------


def _make_output(content: str = "hello", role: str = "assistant", type_: str | None = None):
    """Build a fake Mistral output object with content + role."""
    o = SimpleNamespace(content=content, role=role)
    if type_ is not None:
        o.type = type_
    return o


def _make_response(outputs: list | None = None, conversation_id: str = "conv-1"):
    return SimpleNamespace(
        outputs=outputs if outputs is not None else [_make_output()],
        conversation_id=conversation_id,
    )


def _make_func_call(name: str = "create_slides", arguments: str = '{"title": "T", "slides": []}', tool_call_id: str = "tc-1"):
    return SimpleNamespace(type="function.call", name=name, arguments=arguments, tool_call_id=tool_call_id)


# ===========================================================================
# utils.py
# ===========================================================================


class TestExtractTextFromContent:
    def test_string(self):
        from ensemble.utils import extract_text_from_content
        assert extract_text_from_content("hello") == "hello"

    def test_list_of_dicts(self):
        from ensemble.utils import extract_text_from_content
        content = [{"text": "a"}, {"text": "b"}]
        assert extract_text_from_content(content) == "ab"

    def test_list_of_objects(self):
        from ensemble.utils import extract_text_from_content
        content = [SimpleNamespace(text="x"), SimpleNamespace(text="y")]
        assert extract_text_from_content(content) == "xy"

    def test_object_with_text(self):
        from ensemble.utils import extract_text_from_content
        assert extract_text_from_content(SimpleNamespace(text="z")) == "z"

    def test_none_text(self):
        from ensemble.utils import extract_text_from_content
        assert extract_text_from_content(SimpleNamespace(text=None)) == ""

    def test_empty_list(self):
        from ensemble.utils import extract_text_from_content
        assert extract_text_from_content([]) == ""

    def test_fallback_str(self):
        from ensemble.utils import extract_text_from_content
        assert extract_text_from_content(42) == "42"

    def test_none_returns_empty(self):
        from ensemble.utils import extract_text_from_content
        assert extract_text_from_content(None) == ""


class TestExtractReply:
    def test_simple_string_content(self):
        from ensemble.utils import extract_reply
        resp = _make_response([_make_output("hi")])
        assert extract_reply(resp) == "hi"

    def test_list_content(self):
        from ensemble.utils import extract_reply
        output = SimpleNamespace(content=[{"text": "foo"}, {"text": "bar"}], role="assistant")
        assert extract_reply(_make_response([output])) == "foobar"

    def test_no_matching_output(self):
        from ensemble.utils import extract_reply
        # output without role
        output = SimpleNamespace(content="x")
        assert extract_reply(_make_response([output])) == ""

    def test_empty_outputs(self):
        from ensemble.utils import extract_reply
        assert extract_reply(_make_response([])) == ""

    def test_first_matching_output_wins(self):
        from ensemble.utils import extract_reply
        o1 = _make_output("first")
        o2 = _make_output("second")
        assert extract_reply(_make_response([o1, o2])) == "first"


class TestBuildInputs:
    def test_no_attachments(self):
        from ensemble.utils import build_inputs
        assert build_inputs("hello") == "hello"

    def test_none_attachments(self):
        from ensemble.utils import build_inputs
        assert build_inputs("hello", None) == "hello"

    def test_empty_attachments(self):
        from ensemble.utils import build_inputs
        assert build_inputs("hello", []) == "hello"

    def test_image_attachment(self):
        from ensemble.utils import build_inputs
        att = SimpleNamespace(type="image", url="data:image/png;base64,abc")
        result = build_inputs("describe", [att])
        assert isinstance(result, list)
        assert result[0]["role"] == "user"
        parts = result[0]["content"]
        assert parts[0] == {"type": "text", "text": "describe"}
        assert parts[1]["type"] == "image_url"
        assert parts[1]["image_url"]["url"] == "data:image/png;base64,abc"

    def test_non_image_attachment_ignored(self):
        from ensemble.utils import build_inputs
        att = SimpleNamespace(type="file", url="/path")
        result = build_inputs("hi", [att])
        assert isinstance(result, list)
        # Only text part, no image_url
        assert len(result[0]["content"]) == 1


# ===========================================================================
# config.py
# ===========================================================================


class TestSettings:
    def test_defaults(self):
        from ensemble.config import Settings
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}, clear=False):
            s = Settings()
            assert s.mistral_api_key == "test-key" or s.mistral_api_key  # may come from .env
            assert s.host == "0.0.0.0"
            assert s.port == 8000
            assert s.default_model == "mistral-medium-latest"
            assert s.oracle_model == "mistral-small-latest"

    def test_missing_key_does_not_crash(self):
        """Config should not crash if MISTRAL_API_KEY is missing (returns empty)."""
        from ensemble.config import Settings
        with patch.dict(os.environ, {}, clear=True):
            # clear=True wipes env but dotenv load may have happened already;
            # just verify Settings() doesn't raise
            s = Settings(mistral_api_key="")
            assert s.mistral_api_key == ""

    def test_frozen(self):
        from ensemble.config import Settings
        s = Settings(mistral_api_key="x")
        with pytest.raises(AttributeError):
            s.host = "localhost"


# ===========================================================================
# models.py (conversations)
# ===========================================================================


class TestConversationModels:
    def test_message_defaults(self):
        from ensemble.conversations.models import Message, MessageRole
        m = Message(role=MessageRole.USER, content="hi")
        assert len(m.id) == 12
        assert m.agent_id is None
        assert m.attachments == []
        assert isinstance(m.timestamp, datetime)

    def test_conversation_defaults(self):
        from ensemble.conversations.models import Conversation, ConversationType
        c = Conversation(type=ConversationType.DIRECT, participant_agent_ids=["emma"])
        assert len(c.id) == 32  # uuid hex
        assert c.messages == []
        assert c.mistral_conversation_ids == {}
        assert isinstance(c.created_at, datetime)

    def test_attachment(self):
        from ensemble.conversations.models import Attachment
        a = Attachment(type="image", url="data:image/png;base64,abc")
        assert a.type == "image"
        assert a.url.startswith("data:")

    def test_conversation_type_enum(self):
        from ensemble.conversations.models import ConversationType
        assert ConversationType.DIRECT == "direct"
        assert ConversationType.GROUP == "group"

    def test_message_role_enum(self):
        from ensemble.conversations.models import MessageRole
        assert MessageRole.USER == "user"
        assert MessageRole.AGENT == "agent"

    def test_group_call(self):
        from ensemble.conversations.models import CallStatus, GroupCall
        gc = GroupCall(conversation_id="c1")
        assert gc.status == CallStatus.ACTIVE
        assert gc.mode == "text"

    def test_message_with_attachments(self):
        from ensemble.conversations.models import Attachment, Message, MessageRole
        m = Message(
            role=MessageRole.USER,
            content="look",
            attachments=[Attachment(type="image", url="http://example.com/img.png")],
        )
        assert len(m.attachments) == 1
        assert m.attachments[0].type == "image"


# ===========================================================================
# models.py (agents)
# ===========================================================================


class TestAgentProfile:
    def test_minimal(self):
        from ensemble.agents.models import AgentProfile
        p = AgentProfile(
            id="test", name="Test", role="r", bio="b",
            personality="p", instructions="i",
        )
        assert p.id == "test"
        assert p.tools == []
        assert p.voice_id == ""
        assert p.mistral_agent_id is None
        assert p.model == "mistral-medium-latest"

    def test_with_tools(self):
        from ensemble.agents.models import AgentProfile
        p = AgentProfile(
            id="a", name="A", role="r", bio="b",
            personality="p", instructions="i",
            tools=["code_interpreter", "web_search"],
        )
        assert len(p.tools) == 2

    def test_mistral_agent_id_mutable(self):
        from ensemble.agents.models import AgentProfile
        p = AgentProfile(id="a", name="A", role="r", bio="b", personality="p", instructions="i")
        p.mistral_agent_id = "mid-123"
        assert p.mistral_agent_id == "mid-123"


# ===========================================================================
# registry.py
# ===========================================================================


class TestAgentRegistry:
    def _make_registry(self):
        from ensemble.agents.registry import AgentRegistry
        client = MagicMock()
        return AgentRegistry(client)

    def test_load_profiles_good(self, tmp_path):
        reg = self._make_registry()
        profile = {
            "id": "emma", "name": "Emma", "role": "Engineer",
            "bio": "b", "personality": "p", "instructions": "i",
        }
        (tmp_path / "emma.json").write_text(json.dumps(profile))
        reg.load_profiles(tmp_path)
        assert "emma" in reg.agents
        assert reg.get("emma").name == "Emma"

    def test_load_profiles_missing_dir(self, tmp_path):
        reg = self._make_registry()
        reg.load_profiles(tmp_path / "nonexistent")
        assert len(reg.agents) == 0

    def test_load_profiles_bad_json(self, tmp_path):
        reg = self._make_registry()
        (tmp_path / "bad.json").write_text("not json")
        reg.load_profiles(tmp_path)
        assert len(reg.agents) == 0

    def test_load_profiles_missing_fields(self, tmp_path):
        reg = self._make_registry()
        (tmp_path / "incomplete.json").write_text('{"id": "x"}')
        reg.load_profiles(tmp_path)
        assert len(reg.agents) == 0  # pydantic validation error

    def test_load_profiles_sorted(self, tmp_path):
        reg = self._make_registry()
        for name in ["charlie", "alice", "bob"]:
            (tmp_path / f"{name}.json").write_text(json.dumps({
                "id": name, "name": name.title(), "role": "r",
                "bio": "b", "personality": "p", "instructions": "i",
            }))
        reg.load_profiles(tmp_path)
        assert list(reg.agents.keys()) == ["alice", "bob", "charlie"]

    def test_get_nonexistent(self):
        reg = self._make_registry()
        assert reg.get("nobody") is None

    def test_tool_mapping(self, tmp_path):
        """Verify BUILT_IN_TOOLS keys match expected tool names."""
        from ensemble.agents.registry import BUILT_IN_TOOLS
        expected = {"code_interpreter", "web_search", "image_generation", "create_slides"}
        assert set(BUILT_IN_TOOLS.keys()) == expected

    @pytest.mark.asyncio
    async def test_sync_to_mistral(self, tmp_path):
        from ensemble.agents.registry import AgentRegistry
        client = MagicMock()
        result = SimpleNamespace(id="mistral-123")
        client.beta.agents.create_async = AsyncMock(return_value=result)
        reg = AgentRegistry(client)
        (tmp_path / "a.json").write_text(json.dumps({
            "id": "a", "name": "A", "role": "r",
            "bio": "b", "personality": "p", "instructions": "i",
            "tools": ["code_interpreter"],
        }))
        reg.load_profiles(tmp_path)
        await reg.sync_to_mistral()
        assert reg.get("a").mistral_agent_id == "mistral-123"
        client.beta.agents.create_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_skips_already_synced(self, tmp_path):
        from ensemble.agents.registry import AgentRegistry
        client = MagicMock()
        client.beta.agents.create_async = AsyncMock()
        reg = AgentRegistry(client)
        (tmp_path / "a.json").write_text(json.dumps({
            "id": "a", "name": "A", "role": "r",
            "bio": "b", "personality": "p", "instructions": "i",
        }))
        reg.load_profiles(tmp_path)
        reg.get("a").mistral_agent_id = "already-set"
        await reg.sync_to_mistral()
        client.beta.agents.create_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_mistral(self, tmp_path):
        from ensemble.agents.registry import AgentRegistry
        client = MagicMock()
        client.beta.agents.delete_async = AsyncMock()
        reg = AgentRegistry(client)
        (tmp_path / "a.json").write_text(json.dumps({
            "id": "a", "name": "A", "role": "r",
            "bio": "b", "personality": "p", "instructions": "i",
        }))
        reg.load_profiles(tmp_path)
        reg.get("a").mistral_agent_id = "mid-1"
        await reg.cleanup_mistral()
        client.beta.agents.delete_async.assert_called_once_with(agent_id="mid-1")

    @pytest.mark.asyncio
    async def test_cleanup_skips_unsynced(self, tmp_path):
        from ensemble.agents.registry import AgentRegistry
        client = MagicMock()
        client.beta.agents.delete_async = AsyncMock()
        reg = AgentRegistry(client)
        (tmp_path / "a.json").write_text(json.dumps({
            "id": "a", "name": "A", "role": "r",
            "bio": "b", "personality": "p", "instructions": "i",
        }))
        reg.load_profiles(tmp_path)
        await reg.cleanup_mistral()
        client.beta.agents.delete_async.assert_not_called()


# ===========================================================================
# manager.py
# ===========================================================================


class TestConversationManager:
    def _make_manager(self, agents: dict | None = None):
        from ensemble.agents.models import AgentProfile
        from ensemble.agents.registry import AgentRegistry
        from ensemble.conversations.manager import ConversationManager
        client = MagicMock()
        registry = AgentRegistry(client)
        if agents:
            for aid, profile in agents.items():
                registry._agents[aid] = profile
        return ConversationManager(client, registry), client

    def _agent(self, id_="emma", mistral_id="mid-1"):
        from ensemble.agents.models import AgentProfile
        return AgentProfile(
            id=id_, name=id_.title(), role="r", bio="b",
            personality="p", instructions="i",
            mistral_agent_id=mistral_id,
        )

    def test_create_direct(self):
        mgr, _ = self._make_manager({"emma": self._agent()})
        conv = mgr.create("direct", ["emma"])
        assert conv.type == "direct"
        assert conv.participant_agent_ids == ["emma"]

    def test_create_direct_multiple_agents_fails(self):
        mgr, _ = self._make_manager({"emma": self._agent(), "dan": self._agent("dan", "mid-2")})
        with pytest.raises(ValueError, match="exactly 1"):
            mgr.create("direct", ["emma", "dan"])

    def test_create_group(self):
        mgr, _ = self._make_manager({"emma": self._agent(), "dan": self._agent("dan", "mid-2")})
        conv = mgr.create("group", ["emma", "dan"])
        assert conv.type == "group"

    def test_create_group_single_agent_fails(self):
        mgr, _ = self._make_manager({"emma": self._agent()})
        with pytest.raises(ValueError, match="at least 2"):
            mgr.create("group", ["emma"])

    def test_create_unknown_agent(self):
        mgr, _ = self._make_manager({})
        with pytest.raises(ValueError, match="Unknown agent"):
            mgr.create("direct", ["nobody"])

    def test_get_and_list(self):
        mgr, _ = self._make_manager({"emma": self._agent()})
        conv = mgr.create("direct", ["emma"])
        assert mgr.get(conv.id) is conv
        assert mgr.get("nonexistent") is None
        assert len(mgr.list_all()) == 1

    @pytest.mark.asyncio
    async def test_send_direct_message(self):
        agent = self._agent()
        mgr, client = self._make_manager({"emma": agent})
        conv = mgr.create("direct", ["emma"])

        response = _make_response([_make_output("reply text")])
        client.beta.conversations.start_async = AsyncMock(return_value=response)

        reply = await mgr.send_direct_message(conv.id, "hello")
        assert reply.content == "reply text"
        assert reply.agent_id == "emma"
        assert len(conv.messages) == 2  # user + agent

    @pytest.mark.asyncio
    async def test_send_direct_message_continues_conversation(self):
        agent = self._agent()
        mgr, client = self._make_manager({"emma": agent})
        conv = mgr.create("direct", ["emma"])

        resp1 = _make_response([_make_output("first")])
        client.beta.conversations.start_async = AsyncMock(return_value=resp1)
        await mgr.send_direct_message(conv.id, "hi")

        resp2 = _make_response([_make_output("second")])
        client.beta.conversations.append_async = AsyncMock(return_value=resp2)
        reply = await mgr.send_direct_message(conv.id, "again")
        assert reply.content == "second"
        client.beta.conversations.append_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_direct_not_found(self):
        mgr, _ = self._make_manager({})
        with pytest.raises(ValueError, match="not found"):
            await mgr.send_direct_message("nonexistent", "hello")

    @pytest.mark.asyncio
    async def test_send_direct_wrong_type(self):
        mgr, _ = self._make_manager({"emma": self._agent(), "dan": self._agent("dan", "mid-2")})
        conv = mgr.create("group", ["emma", "dan"])
        with pytest.raises(ValueError, match="group"):
            await mgr.send_direct_message(conv.id, "hello")

    @pytest.mark.asyncio
    async def test_send_direct_agent_not_ready(self):
        from ensemble.agents.models import AgentProfile
        agent = AgentProfile(
            id="emma", name="Emma", role="r", bio="b",
            personality="p", instructions="i",
            mistral_agent_id=None,  # not synced
        )
        mgr, _ = self._make_manager({"emma": agent})
        conv = mgr.create("direct", ["emma"])
        with pytest.raises(ValueError, match="not ready"):
            await mgr.send_direct_message(conv.id, "hello")


class TestHandleFunctionCalls:
    @pytest.mark.asyncio
    async def test_no_function_calls(self):
        from ensemble.conversations.manager import _handle_function_calls
        from ensemble.conversations.models import Conversation, ConversationType
        client = MagicMock()
        response = _make_response([_make_output("text")])
        conv = Conversation(type=ConversationType.DIRECT, participant_agent_ids=["a"])
        result = await _handle_function_calls(client, response, conv, "a")
        assert result is response

    @pytest.mark.asyncio
    async def test_function_call_executes(self):
        from ensemble.conversations.manager import _handle_function_calls
        from ensemble.conversations.models import Conversation, ConversationType

        client = MagicMock()
        fc = _make_func_call()
        # First response has a function call, second has text
        resp_with_call = _make_response([fc])
        resp_after_tool = _make_response([_make_output("done")])
        client.beta.conversations.append_async = AsyncMock(return_value=resp_after_tool)

        conv = Conversation(type=ConversationType.DIRECT, participant_agent_ids=["a"])
        result = await _handle_function_calls(client, resp_with_call, conv, "a")
        assert result is resp_after_tool
        client.beta.conversations.append_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_function_call_unknown_tool(self):
        from ensemble.conversations.manager import _handle_function_calls
        from ensemble.conversations.models import Conversation, ConversationType

        client = MagicMock()
        fc = _make_func_call(name="unknown_tool", arguments='{}')
        resp_with_call = _make_response([fc])
        resp_after = _make_response([_make_output("ok")])
        client.beta.conversations.append_async = AsyncMock(return_value=resp_after)

        conv = Conversation(type=ConversationType.DIRECT, participant_agent_ids=["a"])
        result = await _handle_function_calls(client, resp_with_call, conv, "a")
        # Should still succeed, just with an error result
        call_args = client.beta.conversations.append_async.call_args
        inputs = call_args.kwargs.get("inputs") or call_args[1].get("inputs")
        # Verify error was reported
        assert any("Unknown tool" in str(i) for i in inputs if hasattr(i, "result"))

    @pytest.mark.asyncio
    async def test_function_call_dict_arguments(self):
        from ensemble.conversations.manager import _handle_function_calls
        from ensemble.conversations.models import Conversation, ConversationType

        client = MagicMock()
        fc = SimpleNamespace(
            type="function.call",
            name="create_slides",
            arguments={"title": "T", "slides": []},
            tool_call_id="tc-1",
        )
        resp_with_call = _make_response([fc])
        resp_after = _make_response([_make_output("done")])
        client.beta.conversations.append_async = AsyncMock(return_value=resp_after)

        conv = Conversation(type=ConversationType.DIRECT, participant_agent_ids=["a"])
        result = await _handle_function_calls(client, resp_with_call, conv, "a")
        assert result is resp_after

    @pytest.mark.asyncio
    async def test_function_call_max_rounds(self):
        """Verify that chained function calls stop after max_rounds."""
        from ensemble.conversations.manager import _handle_function_calls
        from ensemble.conversations.models import Conversation, ConversationType

        client = MagicMock()
        fc = _make_func_call()
        # Always returns another function call
        resp_with_call = _make_response([fc])
        client.beta.conversations.append_async = AsyncMock(return_value=resp_with_call)

        conv = Conversation(type=ConversationType.DIRECT, participant_agent_ids=["a"])
        result = await _handle_function_calls(client, resp_with_call, conv, "a", max_rounds=2)
        assert client.beta.conversations.append_async.call_count == 2


# ===========================================================================
# slides.py
# ===========================================================================


class TestSlides:
    def test_render_revealjs_basic(self):
        from ensemble.tools.slides import _render_revealjs
        html_content = _render_revealjs("My Talk", [
            {"title": "Intro", "bullets": ["Point 1", "Point 2"]},
        ])
        assert "My Talk" in html_content
        assert "Intro" in html_content
        assert "Point 1" in html_content
        assert "reveal.js" in html_content
        assert "Thank You" in html_content

    def test_render_revealjs_with_author(self):
        from ensemble.tools.slides import _render_revealjs
        html_content = _render_revealjs("Talk", [], author="Alice")
        assert "Alice" in html_content

    def test_render_revealjs_with_notes(self):
        from ensemble.tools.slides import _render_revealjs
        html_content = _render_revealjs("T", [
            {"title": "S1", "bullets": ["B"], "notes": "Speaker note here"},
        ])
        assert "Speaker note here" in html_content
        assert 'class="notes"' in html_content

    def test_render_revealjs_with_image(self):
        from ensemble.tools.slides import _render_revealjs
        html_content = _render_revealjs("T", [
            {"title": "S1", "bullets": ["B"], "image_url": "https://example.com/img.png"},
        ])
        assert "https://example.com/img.png" in html_content
        assert "<img" in html_content

    def test_render_revealjs_html_escaping(self):
        from ensemble.tools.slides import _render_revealjs
        html_content = _render_revealjs(
            "<script>alert('xss')</script>",
            [{"title": "A&B", "bullets": ["<b>bold</b>"]}],
        )
        # Title should be escaped (the page has its own <script> for Reveal.js)
        assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html_content
        assert "A&amp;B" in html_content
        assert "&lt;b&gt;bold&lt;/b&gt;" in html_content

    def test_render_revealjs_empty_slides(self):
        from ensemble.tools.slides import _render_revealjs
        html_content = _render_revealjs("Empty", [])
        assert "Empty" in html_content
        assert "Thank You" in html_content

    def test_create_slides(self):
        from ensemble.tools.slides import (
            _pdfs,
            _presentations,
            create_slides,
            get_pdf,
            get_presentation,
            list_presentations,
        )

        # Mock _render_pdf to avoid Playwright dependency
        with patch("ensemble.tools.slides._render_pdf", return_value=b"fake-pdf"):
            result = create_slides("Test Talk", [
                {"title": "S1", "bullets": ["B1"]},
            ], author="Bob")

        pres_id = result["presentation_id"]
        assert result["url"] == f"/api/slides/{pres_id}"
        assert result["pdf_url"] == f"/api/slides/{pres_id}/pdf"
        assert "Test Talk" in result["message"]

        # Verify storage
        assert get_presentation(pres_id) is not None
        assert "Test Talk" in get_presentation(pres_id)
        assert get_pdf(pres_id) == b"fake-pdf"
        assert pres_id in list_presentations()

        # Cleanup
        _presentations.pop(pres_id, None)
        _pdfs.pop(pres_id, None)

    def test_create_slides_pdf_failure(self):
        from ensemble.tools.slides import _pdfs, _presentations, create_slides, get_presentation

        with patch("ensemble.tools.slides._render_pdf", side_effect=RuntimeError("no chromium")):
            result = create_slides("Fail", [{"title": "S", "bullets": []}])

        pres_id = result["presentation_id"]
        assert get_presentation(pres_id) is not None  # HTML still created
        assert _pdfs.get(pres_id) is None  # PDF not created

        _presentations.pop(pres_id, None)

    def test_get_presentation_missing(self):
        from ensemble.tools.slides import get_presentation
        assert get_presentation("nonexistent") is None

    def test_get_pdf_missing(self):
        from ensemble.tools.slides import get_pdf
        assert get_pdf("nonexistent") is None


# ===========================================================================
# oracle/engine.py
# ===========================================================================


class TestOracleEngine:
    def _make_oracle(self):
        from ensemble.agents.models import AgentProfile
        from ensemble.agents.registry import AgentRegistry
        from ensemble.oracle.engine import OracleEngine
        client = MagicMock()
        registry = AgentRegistry(client)
        for aid in ["emma", "dan"]:
            registry._agents[aid] = AgentProfile(
                id=aid, name=aid.title(), role="Engineer",
                bio="b", personality=f"{aid} personality",
                instructions="i", mistral_agent_id=f"mid-{aid}",
            )
        return OracleEngine(client, registry), client, registry

    @pytest.mark.asyncio
    async def test_decide_next_speaker(self):
        oracle, client, _ = self._make_oracle()
        from ensemble.conversations.models import Conversation, ConversationType

        conv = Conversation(type=ConversationType.GROUP, participant_agent_ids=["emma", "dan"])

        # Mock oracle response
        choice = SimpleNamespace(
            message=SimpleNamespace(content='{"next_speaker": "emma", "hint": "tech stuff"}')
        )
        client.chat.complete_async = AsyncMock(
            return_value=SimpleNamespace(choices=[choice])
        )

        next_id, hint = await oracle.decide_next_speaker(conv)
        assert next_id == "emma"
        assert hint == "tech stuff"

    @pytest.mark.asyncio
    async def test_decide_next_speaker_invalid_response(self):
        oracle, client, _ = self._make_oracle()
        from ensemble.conversations.models import Conversation, ConversationType

        conv = Conversation(type=ConversationType.GROUP, participant_agent_ids=["emma", "dan"])

        # Mock invalid JSON response
        client.chat.complete_async = AsyncMock(side_effect=Exception("API error"))

        next_id, hint = await oracle.decide_next_speaker(conv)
        assert next_id == "emma"  # falls back to first agent
        assert hint == ""

    @pytest.mark.asyncio
    async def test_decide_next_speaker_unknown_agent(self):
        oracle, client, _ = self._make_oracle()
        from ensemble.conversations.models import Conversation, ConversationType

        conv = Conversation(type=ConversationType.GROUP, participant_agent_ids=["emma", "dan"])

        choice = SimpleNamespace(
            message=SimpleNamespace(content='{"next_speaker": "nobody", "hint": ""}')
        )
        client.chat.complete_async = AsyncMock(
            return_value=SimpleNamespace(choices=[choice])
        )

        next_id, hint = await oracle.decide_next_speaker(conv)
        assert next_id == "emma"  # falls back to first agent

    @pytest.mark.asyncio
    async def test_decide_with_last_speaker(self):
        oracle, client, _ = self._make_oracle()
        from ensemble.conversations.models import Conversation, ConversationType

        conv = Conversation(type=ConversationType.GROUP, participant_agent_ids=["emma", "dan"])

        choice = SimpleNamespace(
            message=SimpleNamespace(content='{"next_speaker": "dan", "hint": ""}')
        )
        client.chat.complete_async = AsyncMock(
            return_value=SimpleNamespace(choices=[choice])
        )

        next_id, _ = await oracle.decide_next_speaker(conv, last_speaker="emma")
        assert next_id == "dan"

        # Verify the system message includes "emma just spoke"
        call_args = client.chat.complete_async.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        last_msg = messages[-1]["content"]
        assert "emma" in last_msg.lower()

    def test_build_agent_prompt(self):
        oracle, _, _ = self._make_oracle()
        from ensemble.conversations.models import (
            Conversation,
            ConversationType,
            Message,
            MessageRole,
        )

        conv = Conversation(type=ConversationType.GROUP, participant_agent_ids=["emma", "dan"])
        conv.messages.append(Message(role=MessageRole.USER, content="Build an app"))
        conv.messages.append(Message(role=MessageRole.AGENT, agent_id="emma", content="Sure"))

        prompt = oracle._build_agent_prompt(conv, "dan", "focus on design")
        assert "Build an app" in prompt
        assert "Emma" in prompt  # name from profile
        assert "focus on design" in prompt
        assert "your turn" in prompt.lower()

    def test_build_agent_prompt_no_hint(self):
        oracle, _, _ = self._make_oracle()
        from ensemble.conversations.models import Conversation, ConversationType

        conv = Conversation(type=ConversationType.GROUP, participant_agent_ids=["emma", "dan"])
        prompt = oracle._build_agent_prompt(conv, "dan", "")
        assert "Moderator" not in prompt

    @pytest.mark.asyncio
    async def test_run_group_turn(self):
        oracle, client, _ = self._make_oracle()
        from ensemble.conversations.models import Conversation, ConversationType

        conv = Conversation(type=ConversationType.GROUP, participant_agent_ids=["emma", "dan"])

        # Oracle picks emma, then dan
        oracle_responses = iter([
            SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"next_speaker": "emma", "hint": ""}')
            )]),
            SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"next_speaker": "dan", "hint": ""}')
            )]),
        ])
        client.chat.complete_async = AsyncMock(side_effect=lambda **kw: next(oracle_responses))

        agent_resp = _make_response([_make_output("agent reply")])
        client.beta.conversations.start_async = AsyncMock(return_value=agent_resp)

        replies = await oracle.run_group_turn(conv, "Hello", max_rounds=2)
        assert len(replies) == 2
        assert replies[0].agent_id == "emma"
        assert replies[1].agent_id == "dan"
        # user message + 2 agent messages = 3
        assert len(conv.messages) == 3


# ===========================================================================
# ws.py — connection manager + helpers
# ===========================================================================


class TestConnectionManager:
    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        from ensemble.api.ws import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect("conv-1", ws)
        ws.accept.assert_called_once()
        assert len(mgr._connections["conv-1"]) == 1

        mgr.disconnect("conv-1", ws)
        assert len(mgr._connections["conv-1"]) == 0

    @pytest.mark.asyncio
    async def test_disconnect_unknown(self):
        from ensemble.api.ws import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        mgr.disconnect("conv-1", ws)  # should not raise

    @pytest.mark.asyncio
    async def test_broadcast(self):
        from starlette.websockets import WebSocketState

        from ensemble.api.ws import ConnectionManager
        mgr = ConnectionManager()

        ws1 = AsyncMock()
        ws1.client_state = WebSocketState.CONNECTED
        ws2 = AsyncMock()
        ws2.client_state = WebSocketState.CONNECTED

        await mgr.connect("c", ws1)
        await mgr.connect("c", ws2)

        await mgr.broadcast("c", {"type": "test"})
        ws1.send_json.assert_called_once_with({"type": "test"})
        ws2.send_json.assert_called_once_with({"type": "test"})


class TestWsHelpers:
    def test_extract_chunk_text_string(self):
        from ensemble.api.ws import _extract_chunk_text
        o = SimpleNamespace(content="hello")
        assert _extract_chunk_text(o) == "hello"

    def test_extract_chunk_text_list(self):
        from ensemble.api.ws import _extract_chunk_text
        o = SimpleNamespace(content=[{"text": "a"}, {"text": "b"}])
        assert _extract_chunk_text(o) == "ab"

    def test_extract_chunk_text_no_content(self):
        from ensemble.api.ws import _extract_chunk_text
        o = SimpleNamespace(role="assistant")
        assert _extract_chunk_text(o) == ""

    def test_extract_chunk_text_from_response(self):
        from ensemble.api.ws import _extract_chunk_text_from_response
        resp = _make_response([_make_output("text")])
        assert _extract_chunk_text_from_response(resp) == "text"


# ===========================================================================
# routes.py — using FastAPI TestClient
# ===========================================================================


class TestRoutes:
    """Test REST API routes using FastAPI TestClient with mocked dependencies."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked dependencies.

        Uses a standalone FastAPI app (no lifespan) to avoid Mistral API calls.
        """
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ensemble.agents.models import AgentProfile
        from ensemble.api import routes

        # Create mock registry
        mock_registry = MagicMock()
        emma = AgentProfile(
            id="emma", name="Emma", role="Engineer",
            bio="b", personality="p", instructions="i",
            mistral_agent_id="mid-1",
        )
        mock_registry.agents = {"emma": emma}
        mock_registry.get.side_effect = lambda aid: emma if aid == "emma" else None

        # Create mock conversation manager
        mock_conv_mgr = MagicMock()

        # Create mock oracle
        mock_oracle = MagicMock()

        routes.init(mock_registry, mock_conv_mgr, mock_oracle, MagicMock())

        # Standalone app with just the router — no lifespan, no real Mistral
        test_app = FastAPI()
        test_app.include_router(routes.router)

        @test_app.get("/health")
        async def health():
            return {"status": "ok"}

        with TestClient(test_app, raise_server_exceptions=False) as tc:
            yield tc, mock_registry, mock_conv_mgr, mock_oracle

    def test_health(self, client):
        tc, *_ = client
        resp = tc.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_list_agents(self, client):
        tc, *_ = client
        resp = tc.get("/api/agents")
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) == 1
        assert agents[0]["id"] == "emma"
        assert agents[0]["ready"] is True

    def test_get_agent(self, client):
        tc, *_ = client
        resp = tc.get("/api/agents/emma")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Emma"

    def test_get_agent_not_found(self, client):
        tc, *_ = client
        resp = tc.get("/api/agents/nobody")
        assert resp.status_code == 404

    def test_create_conversation(self, client):
        tc, _, mock_conv_mgr, _ = client
        from ensemble.conversations.models import Conversation, ConversationType
        conv = Conversation(type=ConversationType.DIRECT, participant_agent_ids=["emma"])
        mock_conv_mgr.create.return_value = conv

        resp = tc.post("/api/conversations", json={
            "type": "direct",
            "participant_agent_ids": ["emma"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "direct"
        assert data["participants"] == ["emma"]

    def test_create_conversation_error(self, client):
        tc, _, mock_conv_mgr, _ = client
        mock_conv_mgr.create.side_effect = ValueError("Unknown agent: nobody")

        resp = tc.post("/api/conversations", json={
            "type": "direct",
            "participant_agent_ids": ["nobody"],
        })
        assert resp.status_code == 400

    def test_list_conversations(self, client):
        tc, _, mock_conv_mgr, _ = client
        from ensemble.conversations.models import Conversation, ConversationType
        c = Conversation(type=ConversationType.DIRECT, participant_agent_ids=["emma"])
        mock_conv_mgr.list_all.return_value = [c]

        resp = tc.get("/api/conversations")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_conversation(self, client):
        tc, _, mock_conv_mgr, _ = client
        from ensemble.conversations.models import Conversation, ConversationType, Message, MessageRole
        c = Conversation(type=ConversationType.DIRECT, participant_agent_ids=["emma"])
        c.messages.append(Message(role=MessageRole.USER, content="hi"))
        mock_conv_mgr.get.return_value = c

        resp = tc.get(f"/api/conversations/{c.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 1

    def test_get_conversation_not_found(self, client):
        tc, _, mock_conv_mgr, _ = client
        mock_conv_mgr.get.return_value = None

        resp = tc.get("/api/conversations/nonexistent")
        assert resp.status_code == 404

    def test_slides_list(self, client):
        tc, *_ = client
        with patch("ensemble.tools.slides.list_presentations", return_value=["abc"]):
            resp = tc.get("/api/slides")
        assert resp.status_code == 200
        assert resp.json()["presentations"] == ["abc"]

    def test_slides_get(self, client):
        tc, *_ = client
        with patch("ensemble.tools.slides.get_presentation", return_value="<html>slides</html>"):
            resp = tc.get("/api/slides/abc")
        assert resp.status_code == 200
        assert "slides" in resp.text

    def test_slides_get_not_found(self, client):
        tc, *_ = client
        with patch("ensemble.tools.slides.get_presentation", return_value=None):
            resp = tc.get("/api/slides/abc")
        assert resp.status_code == 404

    def test_slides_pdf(self, client):
        tc, *_ = client
        with patch("ensemble.tools.slides.get_pdf", return_value=b"pdf-bytes"):
            resp = tc.get("/api/slides/abc/pdf")
        assert resp.status_code == 200
        assert resp.content == b"pdf-bytes"

    def test_slides_pdf_not_found(self, client):
        tc, *_ = client
        with patch("ensemble.tools.slides.get_pdf", return_value=None):
            resp = tc.get("/api/slides/abc/pdf")
        assert resp.status_code == 404


# ===========================================================================
# Run with pytest
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
