"""Image upload + annotation endpoint, and static asset serving for documents."""

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import store
from ..config import settings
from ..services import annotator, document_editor


router = APIRouter(prefix="/api/chats", tags=["uploads"])


MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB per image (Phase-4 cap)
MAX_IMAGES_PER_DOC = 100


class UploadedElement(BaseModel):
    index: int
    label: str
    element_type: str
    inferred_action: str


class UploadResponse(BaseModel):
    annotated_url: str
    original_url: str
    page_summary: str
    elements: list[UploadedElement]
    element_count: int


def _assets_root(chat_id: str, version: str) -> Path:
    return settings.workspace_path / "documents" / chat_id / version / "assets"


def _asset_url_base(chat_id: str) -> str:
    return f"/api/chats/{chat_id}/assets"


@router.post("/{chat_id}/uploads", response_model=UploadResponse)
async def upload_image(chat_id: str, file: UploadFile = File(...)) -> UploadResponse:
    chat = store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Upload must be an image")

    raw = await file.read()
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit",
        )

    assets_root = _assets_root(chat_id, chat.current_version)
    existing_count = 0
    uploaded_dir = assets_root / "uploaded"
    if uploaded_dir.exists():
        existing_count = sum(1 for p in uploaded_dir.iterdir() if p.is_file())
    if existing_count >= MAX_IMAGES_PER_DOC:
        raise HTTPException(
            status_code=409,
            detail=f"This document already has {existing_count} images (max {MAX_IMAGES_PER_DOC}).",
        )

    try:
        result, markdown_block = annotator.annotate(
            raw_bytes=raw,
            original_filename=file.filename or "upload.png",
            mime_type=content_type,
            assets_root=assets_root,
            asset_url_base=_asset_url_base(chat_id),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Annotation failed: {e}")

    # Append the new annotated block to Screenshots And Assets.
    doc = store.read_guide(chat_id, chat.current_version) or ""
    try:
        new_doc = document_editor.append_to_section(
            doc, document_editor.SCREENSHOTS_SECTION, markdown_block
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    ok = store.write_guide(chat_id, new_doc, chat.current_version)
    if not ok:
        raise HTTPException(status_code=409, detail="Document write rejected (approved?)")

    elements = [
        UploadedElement(
            index=i + 1,
            label=el.label,
            element_type=el.element_type,
            inferred_action=el.inferred_action,
        )
        for i, el in enumerate(result.elements)
    ]

    return UploadResponse(
        annotated_url=f"{_asset_url_base(chat_id)}/annotated/{result.annotated_filename}",
        original_url=f"{_asset_url_base(chat_id)}/uploaded/{result.original_filename}",
        page_summary=result.page_summary,
        elements=elements,
        element_count=len(elements),
    )


@router.get("/{chat_id}/assets/{kind}/{filename}")
def get_asset(chat_id: str, kind: str, filename: str) -> FileResponse:
    if kind not in ("uploaded", "annotated"):
        raise HTTPException(status_code=404, detail="Unknown asset kind")
    # Block path traversal — only allow plain filenames.
    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    chat = store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    path = _assets_root(chat_id, chat.current_version) / kind / filename
    try:
        resolved = path.resolve()
        resolved.relative_to(_assets_root(chat_id, chat.current_version).resolve())
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Invalid asset path")

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(resolved)
