"""Image upload + annotation endpoint, and static asset serving for documents.

The chat-message turn ([services/agent.py]) is the primary path for attachments
now; this endpoint remains for direct API use and shares the same annotation
logic via `annotator.annotate_and_append`.
"""

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import store
from ..config import settings
from ..services import annotator


router = APIRouter(prefix="/api/chats", tags=["uploads"])


MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB per image
ASSET_KINDS = ("uploaded", "annotated", "files")


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

    try:
        result = annotator.annotate_and_append(
            chat_id, chat.current_version, raw, file.filename or "upload.png", content_type
        )
    except ValueError as e:  # per-document image cap
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Annotation failed: {e}")

    base = _asset_url_base(chat_id)
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
        annotated_url=f"{base}/annotated/{result.annotated_filename}",
        original_url=f"{base}/uploaded/{result.original_filename}",
        page_summary=result.page_summary,
        elements=elements,
        element_count=len(elements),
    )


@router.get("/{chat_id}/assets/{kind}/{filename}")
def get_asset(chat_id: str, kind: str, filename: str) -> FileResponse:
    if kind not in ASSET_KINDS:
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
