"""POST /api/chats/{id}/messages — streams the agent's reply as SSE.

The request is multipart/form-data: a `text` field plus zero or more `files`
(images and/or PDFs). Files are read fully into memory here — before the SSE
generator runs — because FastAPI closes the UploadFile temp files once this
handler returns.
"""

from collections import defaultdict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from google.genai import types

from .. import store
from ..services import agent
from ..services.agent import Attachment


router = APIRouter(prefix="/api/chats", tags=["messages"])


# In-memory chat history per chat_id. Wiped on server restart (matches the
# "chat history is ephemeral" requirement: documents persist, chat does not).
_history: dict[str, list[types.Content]] = defaultdict(list)


MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB per attachment
MAX_FILES_PER_MESSAGE = 8


def _is_allowed(content_type: str) -> bool:
    return content_type.startswith("image/") or content_type == "application/pdf"


@router.post("/{chat_id}/messages")
async def post_message(
    chat_id: str,
    text: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    browse: bool = Form(False),
) -> StreamingResponse:
    chat = store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    text = (text or "").strip()

    if len(files) > MAX_FILES_PER_MESSAGE:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {MAX_FILES_PER_MESSAGE} per message).",
        )

    attachments: list[Attachment] = []
    for f in files:
        content_type = (f.content_type or "").lower()
        if not _is_allowed(content_type):
            raise HTTPException(
                status_code=415,
                detail=(
                    f"Unsupported file type '{content_type or 'unknown'}' for "
                    f"'{f.filename}'. Only images and PDFs are allowed."
                ),
            )
        raw = await f.read()
        if len(raw) > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"'{f.filename}' exceeds the {MAX_FILE_BYTES // (1024 * 1024)} MB limit.",
            )
        attachments.append(
            Attachment(filename=f.filename or "upload", mime=content_type, data=raw)
        )

    if not text and not attachments:
        raise HTTPException(
            status_code=400, detail="Message text or at least one attachment is required"
        )

    history = _history[chat_id]
    stream = agent.run_turn(chat, history, text, attachments, force_browse=browse)

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/{chat_id}/messages", status_code=204)
def clear_history(chat_id: str) -> None:
    _history.pop(chat_id, None)
