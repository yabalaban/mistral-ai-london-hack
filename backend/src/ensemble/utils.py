"""Shared utility functions for Ensemble backend.

This module consolidates helper functions used across multiple modules
to eliminate code duplication.
"""

from __future__ import annotations

from typing import Any


def extract_reply(response: Any) -> str:
    """Extract the text reply from a Mistral conversation response.

    Handles multiple content formats: plain string, list of content blocks,
    or structured objects with a ``text`` attribute.

    Args:
        response: A Mistral conversation response object with an ``outputs`` list.

    Returns:
        The extracted text content, or empty string if no text is found.
    """
    for output in response.outputs:
        if hasattr(output, "content") and hasattr(output, "role"):
            return extract_text_from_content(output.content)
    return ""


def extract_text_from_content(content: Any) -> str:
    """Extract text from a Mistral content object.

    Handles plain strings, lists of content blocks (dicts or objects),
    and objects with a ``text`` attribute.

    Args:
        content: The content field from a Mistral output.

    Returns:
        Extracted text string.
    """
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
    if hasattr(content, "text"):
        return content.text or ""
    return str(content) if content else ""


def build_inputs(
    content: str, attachments: list | None = None
) -> str | list[dict]:
    """Build Mistral conversation inputs from content and optional attachments.

    For plain text with no attachments, returns the string directly.
    For multimodal messages (with image attachments), builds a structured
    content block list suitable for Mistral's API.

    Args:
        content: The text content of the message.
        attachments: Optional list of Attachment objects with ``type`` and ``url``.

    Returns:
        Either a plain string or a list of message dicts with content blocks.
    """
    if not attachments:
        return content

    parts: list[dict] = [{"type": "text", "text": content}]
    for att in attachments:
        if att.type == "image":
            parts.append({"type": "image_url", "image_url": {"url": att.url}})
    return [{"role": "user", "content": parts}]
