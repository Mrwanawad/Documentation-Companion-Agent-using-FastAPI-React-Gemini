"""Self-contained HTML export of a guide document.

Renders the Markdown guide to HTML and inlines every asset image as a base64
data URI, so the resulting file is a single portable document that opens in any
browser and prints straight to PDF.
"""

from __future__ import annotations

import base64
import html
import mimetypes
import re
from typing import Optional

import markdown as md

from .. import store
from . import annotator


# Matches the asset URLs our Markdown uses, e.g.
#   src="/api/chats/<id>/assets/annotated/<file>.png"
_IMG_SRC_RE = re.compile(r'src="(/api/chats/[^"]+/assets/(uploaded|annotated|files)/[^"/]+)"')


DOC_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #f4f5f7; }
.doc {
  max-width: 820px; margin: 32px auto; padding: 48px 56px;
  background: #fff; color: #1a1a1a; border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.6; font-size: 15px;
}
.doc h1 { font-size: 30px; margin: 0 0 8px; }
.doc h2 { font-size: 21px; margin: 32px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #e5e7eb; }
.doc h3 { font-size: 17px; margin: 22px 0 8px; }
.doc p, .doc li { color: #262626; }
.doc a { color: #0a7f5b; }
.doc code { background: #f0f1f3; padding: 1px 5px; border-radius: 4px; font-size: 13px; }
.doc pre { background: #f0f1f3; padding: 12px; border-radius: 6px; overflow: auto; }
.doc img { max-width: 100%; height: auto; border: 1px solid #e5e7eb; border-radius: 6px; margin: 8px 0; }
.doc table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0; }
.doc th, .doc td { border: 1px solid #e5e7eb; padding: 6px 10px; text-align: left; vertical-align: top; }
.doc th { background: #f7f8fa; }
.doc blockquote { border-left: 3px solid #d1d5db; margin: 8px 0; padding: 2px 14px; color: #4b5563; }
.doc[dir="rtl"] { text-align: right; }
.doc[dir="rtl"] th, .doc[dir="rtl"] td { text-align: right; }
.doc[dir="rtl"] blockquote { border-left: none; border-right: 3px solid #d1d5db; }
.doc[dir="rtl"] ul, .doc[dir="rtl"] ol { padding-left: 0; padding-right: 1.6em; }
@media print { body { background: #fff; } .doc { box-shadow: none; margin: 0; max-width: none; } }
"""

HTML_TEMPLATE = """<!doctype html>
<html lang="{lang}" dir="{dir}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body><article class="doc" dir="{dir}">{body}</article></body>
</html>"""


# Arabic + Arabic presentation forms vs. Latin letters — used to pick the export
# writing direction from the guide's content (no language flag needed here).
_RTL_CHARS = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LTR_CHARS = re.compile(r"[A-Za-zÀ-ɏ]")


def _detect_dir(text: str) -> tuple[str, str]:
    """Return (dir, lang) for the document based on its dominant script."""
    rtl = len(_RTL_CHARS.findall(text))
    if rtl == 0:
        return "ltr", "en"
    ltr = len(_LTR_CHARS.findall(text))
    return ("rtl", "ar") if rtl > ltr else ("ltr", "en")


def _inline_images(html_body: str, chat_id: str, version: str) -> str:
    assets_root = annotator.assets_root_for(chat_id, version)

    def repl(match: re.Match[str]) -> str:
        url, kind = match.group(1), match.group(2)
        filename = url.rsplit("/", 1)[-1]
        path = assets_root / kind / filename
        try:
            resolved = path.resolve()
            resolved.relative_to(assets_root.resolve())
        except (ValueError, OSError):
            return match.group(0)
        if not resolved.is_file():
            return match.group(0)
        mime = mimetypes.guess_type(str(resolved))[0] or "image/png"
        data = base64.b64encode(resolved.read_bytes()).decode("ascii")
        return f'src="data:{mime};base64,{data}"'

    return _IMG_SRC_RE.sub(repl, html_body)


def render_html(chat_id: str, version: str, title: str) -> Optional[str]:
    """Return a self-contained HTML string for the guide, or None if missing."""
    content = store.read_guide(chat_id, version)
    if content is None:
        return None
    direction, lang = _detect_dir(content)
    body = md.markdown(content, extensions=["tables", "fenced_code", "sane_lists"])
    body = _inline_images(body, chat_id, version)
    return HTML_TEMPLATE.format(
        title=html.escape(title), css=DOC_CSS, body=body, dir=direction, lang=lang
    )
