"""Shared utility functions for Ensemble backend.

This module consolidates helper functions used across multiple modules
to eliminate code duplication.
"""

from __future__ import annotations

from typing import Any


def extract_reply(response: Any, *, client: Any = None) -> str:
    """Extract the text reply from a Mistral conversation response.

    Handles multiple content formats: plain string, list of content blocks,
    or structured objects with a ``text`` attribute.

    Args:
        response: A Mistral conversation response object with an ``outputs`` list.
        client: Optional Mistral client for downloading tool files (images).

    Returns:
        The extracted text content, or empty string if no text is found.
    """
    for output in response.outputs:
        if hasattr(output, "content") and hasattr(output, "role"):
            return extract_text_from_content(output.content, client=client)
    return ""


def extract_text_from_content(content: Any, *, client: Any = None) -> str:
    """Extract text from a Mistral content object.

    Handles plain strings, lists of content blocks (dicts or objects),
    and objects with a ``text`` attribute.  When *client* is provided,
    ``tool_file`` blocks (e.g. from ``image_generation``) are downloaded,
    stored locally, and rendered as markdown image links.

    Args:
        content: The content field from a Mistral output.
        client: Optional Mistral client for downloading tool files.

    Returns:
        Extracted text string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for c in content:
            if isinstance(c, dict):
                ctype = c.get("type", "")
                if ctype == "tool_file" and c.get("file_id") and client:
                    url = _download_tool_file(client, c["file_id"])
                    if url:
                        texts.append(f"\n\n![Generated image]({url})")
                        continue
                texts.append(c.get("text", ""))
            elif hasattr(c, "type") and getattr(c, "type", "") == "tool_file":
                file_id = getattr(c, "file_id", None)
                if file_id and client:
                    url = _download_tool_file(client, file_id)
                    if url:
                        texts.append(f"\n\n![Generated image]({url})")
                        continue
            elif hasattr(c, "text"):
                texts.append(getattr(c, "text", "") or "")
        return "".join(texts)
    if hasattr(content, "text"):
        return content.text or ""
    return str(content) if content else ""


def _download_tool_file(client: Any, file_id: str) -> str | None:
    """Download a Mistral tool file and store it locally for serving."""
    import logging
    import uuid as _uuid

    from ensemble.config import settings

    logger = logging.getLogger(__name__)
    try:
        file_bytes = client.files.download(file_id=file_id).read()
        image_id = _uuid.uuid4().hex[:12]
        from ensemble.api.routes import store_generated_image
        store_generated_image(image_id, file_bytes, "image/png")
        url = f"{settings.base_url}/api/images/{image_id}"
        logger.info("Downloaded tool file %s → %s", file_id, url)
        return url
    except Exception:
        logger.exception("Failed to download tool file %s", file_id)
        return None


VOICE_MODE_PREFIX = (
    "[Voice conversation — reply in 1–2 short sentences. "
    "Be concise, conversational, and natural. No lists, no markdown, no long explanations.]\n\n"
)


def build_voice_inputs(content: str) -> str:
    """Wrap user content with voice-mode brevity instructions."""
    return VOICE_MODE_PREFIX + content


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
