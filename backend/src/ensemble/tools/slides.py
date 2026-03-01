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
_pdfs: dict[str, bytes] = {}  # id -> PDF bytes

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
    """Generate a Reveal.js presentation, store it, and generate PDF.

    Returns presentation_id, view URL, and PDF URL.
    """
    pres_id = uuid.uuid4().hex[:12]
    html_content = _render_revealjs(title, slides, author)
    _presentations[pres_id] = html_content

    # Generate PDF in background
    try:
        pdf_bytes = _render_pdf(html_content)
        _pdfs[pres_id] = pdf_bytes
        logger.info("Created presentation + PDF %s: %s (%d slides)", pres_id, title, len(slides))
    except Exception:
        logger.exception("PDF generation failed for %s", pres_id)

    from ensemble.config import settings

    base = settings.base_url.rstrip("/")
    return {
        "presentation_id": pres_id,
        "url": f"{base}/api/slides/{pres_id}",
        "pdf_url": f"{base}/api/slides/{pres_id}/pdf",
        "message": f"Presentation '{title}' created with {len(slides)} slides.",
    }


def get_presentation(pres_id: str) -> str | None:
    """Retrieve a generated presentation HTML."""
    return _presentations.get(pres_id)


def get_pdf(pres_id: str) -> bytes | None:
    """Retrieve a generated presentation PDF."""
    return _pdfs.get(pres_id)


def list_presentations() -> list[str]:
    """List all presentation IDs."""
    return list(_presentations.keys())


def _render_pdf(html_content: str) -> bytes:
    """Render HTML slides to PDF using Playwright (headless Chromium).

    Uses Reveal.js print-pdf mode for proper slide layout.
    """
    import tempfile

    from playwright.sync_api import sync_playwright

    # Inject ?print-pdf to trigger Reveal.js print mode
    # We need to write the HTML to a temp file and add the print-pdf query

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        # Modify the HTML to auto-enable print-pdf mode
        modified = html_content.replace(
            "Reveal.initialize({",
            "Reveal.initialize({\n"
            "      pdfSeparateFragments: false,\n"
            "      pdfMaxPagesPerSlide: 1,",
        )
        f.write(modified)
        tmp_path = f.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            # Load with print-pdf flag for Reveal.js
            page.goto(f"file://{tmp_path}?print-pdf", wait_until="networkidle")
            # Wait for Reveal.js to initialize
            page.wait_for_timeout(2000)
            pdf_bytes = page.pdf(
                format="A4",
                landscape=True,
                print_background=True,
            )
            browser.close()
        return pdf_bytes
    finally:
        import os
        os.unlink(tmp_path)


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
