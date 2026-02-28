"""Conversation management — routing messages to Mistral agents.

Handles direct (1:1) conversations with individual agents,
including function call (tool use) handling.
"""

from __future__ import annotations

import json
import logging

from mistralai import Mistral

from ensemble.agents.registry import AgentRegistry
from ensemble.conversations.models import (
    Attachment,
    Conversation,
    ConversationType,
    Message,
    MessageRole,
)
from ensemble.tools.slides import create_slides
from ensemble.utils import build_inputs, extract_reply

logger = logging.getLogger(__name__)

# Registry of callable tools
TOOL_HANDLERS = {
    "create_slides": create_slides,
}


class ConversationManager:
    """Manages conversations and routes messages to Mistral."""

    def __init__(self, client: Mistral, registry: AgentRegistry) -> None:
        self._client = client
        self._registry = registry
        self._conversations: dict[str, Conversation] = {}

    @property
    def conversations(self) -> dict[str, Conversation]:
        """Return a shallow copy of the conversations dict."""
        return dict(self._conversations)

    def get(self, conversation_id: str) -> Conversation | None:
        """Look up a conversation by ID, returning ``None`` if not found."""
        return self._conversations.get(conversation_id)

    def create(
        self,
        type: ConversationType,
        participant_agent_ids: list[str],
    ) -> Conversation:
        """Create a new conversation."""
        # Validate agents exist
        for aid in participant_agent_ids:
            if not self._registry.get(aid):
                raise ValueError(f"Unknown agent: {aid}")

        if type == ConversationType.DIRECT and len(participant_agent_ids) != 1:
            raise ValueError("Direct conversations must have exactly 1 participant agent")

        if type == ConversationType.GROUP and len(participant_agent_ids) < 2:
            raise ValueError("Group conversations must have at least 2 participant agents")

        conv = Conversation(type=type, participant_agent_ids=participant_agent_ids)
        self._conversations[conv.id] = conv
        logger.info("Created %s conversation %s with %s", type, conv.id, participant_agent_ids)
        return conv

    async def send_direct_message(
        self,
        conversation_id: str,
        content: str,
        attachments: list[Attachment] | None = None,
    ) -> Message:
        """Send a user message in a direct conversation, get agent reply."""
        conv = self._conversations.get(conversation_id)
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found")
        if conv.type != ConversationType.DIRECT:
            raise ValueError("Use send_group_message for group conversations")

        agent_id = conv.participant_agent_ids[0]
        agent = self._registry.get(agent_id)
        if not agent or not agent.mistral_agent_id:
            raise ValueError(f"Agent {agent_id} not ready")

        # Record user message
        user_msg = Message(
            role=MessageRole.USER,
            content=content,
            attachments=attachments or [],
        )
        conv.messages.append(user_msg)

        # Build inputs for Mistral
        inputs = build_inputs(content, attachments)

        # Start or continue Mistral conversation
        # Use client handoff so we handle function calls locally
        mistral_conv_id = conv.mistral_conversation_ids.get(agent_id)
        if mistral_conv_id:
            response = await self._client.beta.conversations.append_async(
                conversation_id=mistral_conv_id,
                inputs=inputs,
                handoff_execution="client",
            )
        else:
            response = await self._client.beta.conversations.start_async(
                agent_id=agent.mistral_agent_id,
                inputs=inputs,
                handoff_execution="client",
            )

        conv.mistral_conversation_ids[agent_id] = response.conversation_id

        # Handle function calls (tool use)
        response = await _handle_function_calls(
            self._client, response, conv, agent_id
        )

        # Extract assistant reply
        reply_text = extract_reply(response)
        agent_msg = Message(
            role=MessageRole.AGENT,
            agent_id=agent_id,
            content=reply_text,
        )
        conv.messages.append(agent_msg)
        return agent_msg

    def list_all(self) -> list[Conversation]:
        return list(self._conversations.values())


async def _handle_function_calls(client, response, conv, agent_id, max_rounds: int = 3):
    """If the response contains function calls, execute them and continue.

    Loops up to max_rounds in case the agent chains multiple tool calls.
    """
    from mistralai.models.functionresultentry import FunctionResultEntry

    for _ in range(max_rounds):
        func_calls = [
            o for o in response.outputs
            if hasattr(o, "type") and getattr(o, "type", None) == "function.call"
        ]
        if not func_calls:
            return response

        # Execute each function call
        results = []
        for fc in func_calls:
            fn_name = fc.name
            try:
                raw_args = fc.arguments
                # arguments can be: str (JSON), pydantic model, or dict
                if isinstance(raw_args, str):
                    args = json.loads(raw_args)
                elif hasattr(raw_args, "model_dump"):
                    args = raw_args.model_dump()
                    # model_dump may produce nested strings; re-parse if needed
                    if isinstance(args, str):
                        args = json.loads(args)
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = json.loads(str(raw_args))

                handler = TOOL_HANDLERS.get(fn_name)
                if handler:
                    result = handler(**args)
                    result_str = json.dumps(result)
                    logger.info("Tool %s returned: %s", fn_name, result_str[:200])
                else:
                    result_str = json.dumps({"error": f"Unknown tool: {fn_name}"})
                    logger.warning("Unknown tool called: %s", fn_name)
            except Exception:
                logger.exception("Tool %s execution failed", fn_name)
                result_str = json.dumps({"error": f"Tool {fn_name} failed"})

            results.append(FunctionResultEntry(
                tool_call_id=fc.tool_call_id,
                result=result_str,
            ))

        # Send results back to the conversation
        conv_id = response.conversation_id
        response = await client.beta.conversations.append_async(
            conversation_id=conv_id,
            inputs=results,
        )
        conv.mistral_conversation_ids[agent_id] = response.conversation_id

    return response
