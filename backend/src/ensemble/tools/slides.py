"""Slides generation tool — renders Reveal.js presentations.

The PA agent calls `create_slides` with structured slide data.
We render it as an HTML file using Reveal.js (CDN) and serve it.

Function tool schema (for Mistral):
{
    "type": "function",
    "function": {
        "name": "create_slides",
        "description": (
            "Create a presentation from structured slide data. "
            "Each slide has a title and bullet points. "
            "Returns a URL to view the presentation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Presentation title (shown on the title slide)"
                },
                "author": {
                    "type": "string",
                    "description": "Author name"
                },
                "slides": {
                    "type": "array",
                    "description": "List of slides, each with a title and content",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Slide title/heading"
                            },
                            "bullets": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Bullet points for this slide"
                            },
                            "notes": {
                                "type": "string",
                                "description": "Speaker notes (optional)"
                            }
                        },
                        "required": ["title", "bullets"]
                    }
                }
            },
            "required": ["title", "slides"]
        }
    }
}
"""

from __future__ import annotations

import html
import logging
import uuid

logger = logging.getLogger(__name__)

# In-memory store for generated presentations
_presentations: dict[str, str] = {}  # id -> HTML

SLIDES_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_slides",
        "description": (
            "Create a presentation from structured slide data. "
            "Each slide has a title and bullet points. "
            "Returns a URL to view the presentation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Presentation title (shown on the title slide)",
                },
                "author": {
                    "type": "string",
                    "description": "Author name",
                },
                "slides": {
                    "type": "array",
                    "description": "List of slides",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Slide title/heading",
                            },
                            "bullets": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Bullet points for this slide",
                            },
                            "notes": {
                                "type": "string",
                                "description": "Speaker notes (optional)",
                            },
                            "image_url": {
                                "type": "string",
                                "description": "URL of an image to display on the slide (optional)",
                            },
                        },
                        "required": ["title", "bullets"],
                    },
                },
            },
            "required": ["title", "slides"],
        },
    },
}


def create_slides(
    title: str,
    slides: list[dict],
    author: str = "",
) -> dict[str, str]:
    """Generate a Reveal.js presentation and store it.

    Returns presentation_id and view URL.
    """
    pres_id = uuid.uuid4().hex[:12]
    html_content = _render_revealjs(title, slides, author)
    _presentations[pres_id] = html_content
    logger.info("Created presentation %s: %s (%d slides)", pres_id, title, len(slides))

    from ensemble.config import settings

    base = settings.base_url.rstrip("/")
    return {
        "presentation_id": pres_id,
        "url": f"{base}/api/slides/{pres_id}",
        "message": f"Presentation '{title}' created with {len(slides)} slides.",
    }


def get_presentation(pres_id: str) -> str | None:
    """Retrieve a generated presentation HTML."""
    return _presentations.get(pres_id)


def list_presentations() -> list[str]:
    """List all presentation IDs."""
    return list(_presentations.keys())


def _render_revealjs(title: str, slides: list[dict], author: str = "") -> str:
    """Render slides as a Reveal.js HTML document."""
    e = html.escape

    # Build slide sections
    sections = []

    # Title slide
    title_html = f"""
    <section>
      <h1>{e(title)}</h1>
      {f'<p>{e(author)}</p>' if author else ''}
    </section>"""
    sections.append(title_html)

    # Content slides
    for slide in slides:
        slide_title = e(slide.get("title", ""))
        bullets = slide.get("bullets", [])
        notes = slide.get("notes", "")
        image_url = slide.get("image_url", "")

        bullets_html = "\n".join(f"        <li>{e(b)}</li>" for b in bullets)
        notes_html = f'\n      <aside class="notes">{e(notes)}</aside>' if notes else ""

        if image_url:
            # Two-column layout: image left, bullets right
            section = f"""
    <section>
      <h2>{slide_title}</h2>
      <div style="display:flex; align-items:flex-start; gap:2em;">
        <img src="{e(image_url)}" style="max-width:45%; max-height:60vh; border-radius:8px;" />
        <ul style="flex:1;">
{bullets_html}
        </ul>
      </div>{notes_html}
    </section>"""
        else:
            section = f"""
    <section>
      <h2>{slide_title}</h2>
      <ul>
{bullets_html}
      </ul>{notes_html}
    </section>"""
        sections.append(section)

    # Thank you slide
    sections.append("""
    <section>
      <h1>Thank You</h1>
      <p>Questions?</p>
    </section>""")

    slides_html = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{e(title)}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/reveal.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/theme/black.css">
  <style>
    .reveal h1, .reveal h2 {{ text-transform: none; }}
    .reveal ul {{ text-align: left; }}
    .reveal li {{ margin-bottom: 0.5em; font-size: 0.9em; }}
  </style>
</head>
<body>
  <div class="reveal">
    <div class="slides">
{slides_html}
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/reveal.js"></script>
  <script>
    Reveal.initialize({{
      hash: true,
      transition: 'slide',
      slideNumber: true,
    }});
  </script>
</body>
</html>"""
