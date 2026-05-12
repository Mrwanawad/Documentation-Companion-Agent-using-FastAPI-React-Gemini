"""Image annotation service.

Pipeline:
1. Accept an uploaded image (any format Pillow can decode).
2. Ask Gemini 3 vision with structured output to detect interactive elements
   (buttons, links, inputs, dropdowns, etc.) and infer what each does.
3. Use Pillow to draw numbered boxes onto a copy of the original image.
4. Return: original asset path, annotated asset path, the structured elements,
   and a Markdown block to append to the Screenshots And Assets section.
"""

from __future__ import annotations

import io
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types

from ..config import settings


# Normalized bounding box: each value in [0.0, 1.0] relative to image dimensions.
RESPONSE_SCHEMA = types.Schema(
    type="OBJECT",
    properties={
        "page_summary": types.Schema(
            type="STRING",
            description="A short one-sentence description of what this screen appears to be.",
        ),
        "elements": types.Schema(
            type="ARRAY",
            items=types.Schema(
                type="OBJECT",
                properties={
                    "label": types.Schema(
                        type="STRING",
                        description="Visible text label or aria/accessibility name of the element.",
                    ),
                    "element_type": types.Schema(
                        type="STRING",
                        description=(
                            "One of: button, link, text_input, textarea, dropdown, checkbox, "
                            "radio, toggle, tab, menu_item, icon_button, search, file_picker, other."
                        ),
                    ),
                    "inferred_action": types.Schema(
                        type="STRING",
                        description="What this element appears to do when used. Be specific and concrete.",
                    ),
                    "bbox": types.Schema(
                        type="OBJECT",
                        description="Normalized bounding box [0.0, 1.0] relative to image dimensions.",
                        properties={
                            "x": types.Schema(type="NUMBER", description="Left edge, 0.0-1.0."),
                            "y": types.Schema(type="NUMBER", description="Top edge, 0.0-1.0."),
                            "w": types.Schema(type="NUMBER", description="Width, 0.0-1.0."),
                            "h": types.Schema(type="NUMBER", description="Height, 0.0-1.0."),
                        },
                        required=["x", "y", "w", "h"],
                    ),
                },
                required=["label", "element_type", "inferred_action", "bbox"],
            ),
        ),
    },
    required=["page_summary", "elements"],
)


VISION_PROMPT = """Analyze this screenshot of a single page from a SaaS or ERP system.

Identify every INTERACTIVE element a user can click, type into, or operate. \
For each element, return:
- `label`: the visible label or accessible name
- `element_type`: one of the listed types
- `inferred_action`: a concrete sentence describing what happens when the user uses it
- `bbox`: a tight normalized bounding box (x, y, w, h all between 0.0 and 1.0)

Also return `page_summary`: one sentence describing what this page is.

Skip purely decorative or static text. Include form inputs, buttons, dropdowns, \
toggles, tabs, links, menu items, file pickers, search boxes, and icon-only \
buttons that perform actions. Order elements roughly top-to-bottom, left-to-right."""


@dataclass
class Element:
    label: str
    element_type: str
    inferred_action: str
    bbox_px: tuple[int, int, int, int]  # (x, y, w, h) in pixels


@dataclass
class AnnotationResult:
    page_summary: str
    elements: list[Element]
    original_filename: str  # relative to assets/uploaded/
    annotated_filename: str  # relative to assets/annotated/
    width: int
    height: int


def _client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)


def _safe_filename(original: str) -> str:
    suffix = Path(original).suffix.lower() or ".png"
    return f"{uuid.uuid4().hex[:10]}{suffix}"


def _load_image_normalized(raw: bytes) -> Image.Image:
    """Decode bytes and normalize to RGB so we can save consistently as PNG."""
    img = Image.open(io.BytesIO(raw))
    img.load()
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    return img


def _detect(image_bytes: bytes, mime_type: str) -> dict:
    client = _client()
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    types.Part(text=VISION_PROMPT),
                ],
            )
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )
    text = response.text or ""
    return json.loads(text)


def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_boxes(img: Image.Image, elements: list[Element]) -> Image.Image:
    """Draw numbered boxes onto a copy of `img`. Box index = element index + 1."""
    out = img.copy().convert("RGB")
    draw = ImageDraw.Draw(out, "RGBA")
    w, h = out.size

    box_color = (0, 229, 153, 255)  # Coject mint
    label_bg = (0, 0, 0, 220)
    label_fg = (255, 255, 255, 255)
    font_size = max(14, min(28, w // 60))
    font = _font(font_size)
    stroke = max(2, w // 600)

    for idx, el in enumerate(elements, start=1):
        x, y, bw, bh = el.bbox_px
        x2, y2 = x + bw, y + bh
        # Clamp to image bounds.
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))
        x2 = max(0, min(x2, w))
        y2 = max(0, min(y2, h))
        if x2 <= x or y2 <= y:
            continue

        draw.rectangle([x, y, x2, y2], outline=box_color, width=stroke)

        tag = str(idx)
        try:
            bbox_text = draw.textbbox((0, 0), tag, font=font)
            tw = bbox_text[2] - bbox_text[0]
            th = bbox_text[3] - bbox_text[1]
        except Exception:
            tw, th = font_size, font_size
        pad = max(3, font_size // 4)
        tx = x
        ty = max(0, y - th - 2 * pad)
        # If the label would go above the image, drop it inside the box.
        if ty < 0:
            ty = y
        draw.rectangle(
            [tx, ty, tx + tw + 2 * pad, ty + th + 2 * pad],
            fill=label_bg,
        )
        draw.text((tx + pad, ty + pad), tag, fill=label_fg, font=font)

    return out


def _markdown_block(
    result: AnnotationResult, asset_url_base: str
) -> str:
    """Produce the Markdown chunk to append to Screenshots And Assets."""
    annotated_url = f"{asset_url_base}/annotated/{result.annotated_filename}"
    original_url = f"{asset_url_base}/uploaded/{result.original_filename}"

    lines = [
        f"### {result.page_summary}",
        "",
        f"![Annotated screenshot]({annotated_url})",
        "",
        f"_Original: [{result.original_filename}]({original_url})_",
        "",
        "| # | Element | Type | What it does |",
        "|---|---------|------|--------------|",
    ]
    for idx, el in enumerate(result.elements, start=1):
        label = el.label.replace("|", "\\|").strip() or "—"
        action = el.inferred_action.replace("|", "\\|").strip() or "—"
        kind = el.element_type.replace("|", "\\|").strip() or "—"
        lines.append(f"| {idx} | {label} | {kind} | {action} |")

    return "\n".join(lines)


def annotate(
    *,
    raw_bytes: bytes,
    original_filename: str,
    mime_type: str,
    assets_root: Path,
    asset_url_base: str,
) -> tuple[AnnotationResult, str]:
    """Run the full pipeline. Returns (result, markdown_block)."""
    uploaded_dir = assets_root / "uploaded"
    annotated_dir = assets_root / "annotated"
    uploaded_dir.mkdir(parents=True, exist_ok=True)
    annotated_dir.mkdir(parents=True, exist_ok=True)

    base = _safe_filename(original_filename)
    original_name = base
    annotated_name = base  # same uuid, mirrored in annotated/

    img = _load_image_normalized(raw_bytes)
    w, h = img.size

    # Save the original as PNG so we have a consistent canonical form.
    original_path = uploaded_dir / original_name
    img.save(original_path, format="PNG")

    # Run detection.
    detection = _detect(raw_bytes, mime_type)
    raw_elements = detection.get("elements", []) or []
    page_summary = (detection.get("page_summary") or "Annotated page").strip()

    elements: list[Element] = []
    for el in raw_elements:
        bbox = el.get("bbox") or {}
        try:
            nx = float(bbox.get("x", 0))
            ny = float(bbox.get("y", 0))
            nw = float(bbox.get("w", 0))
            nh = float(bbox.get("h", 0))
        except (TypeError, ValueError):
            continue
        # Convert normalized to pixels and clamp.
        px = max(0, int(round(nx * w)))
        py = max(0, int(round(ny * h)))
        pw = max(1, int(round(nw * w)))
        ph = max(1, int(round(nh * h)))
        elements.append(
            Element(
                label=str(el.get("label", "")).strip(),
                element_type=str(el.get("element_type", "other")).strip() or "other",
                inferred_action=str(el.get("inferred_action", "")).strip(),
                bbox_px=(px, py, pw, ph),
            )
        )

    annotated_img = _draw_boxes(img, elements)
    annotated_path = annotated_dir / annotated_name
    annotated_img.save(annotated_path, format="PNG")

    result = AnnotationResult(
        page_summary=page_summary,
        elements=elements,
        original_filename=original_name,
        annotated_filename=annotated_name,
        width=w,
        height=h,
    )
    markdown = _markdown_block(result, asset_url_base)
    return result, markdown
