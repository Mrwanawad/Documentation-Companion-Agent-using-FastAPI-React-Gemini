from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from slugify import slugify

from .. import store
from ..models import ChatCreate, ChatMeta, ChatStatus, ChatUpdate, DocumentRead, DocumentWrite
from ..services import browser as browser_service
from ..services import exporter


router = APIRouter(prefix="/api/chats", tags=["chats"])


@router.get("", response_model=list[ChatMeta])
def list_chats() -> list[ChatMeta]:
    return store.list_chats()


@router.post("", response_model=ChatMeta, status_code=201)
def create_chat(body: ChatCreate) -> ChatMeta:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    return store.create_chat(name=name, browser_enabled=body.browser_enabled)


@router.get("/{chat_id}", response_model=ChatMeta)
def get_chat(chat_id: str) -> ChatMeta:
    meta = store.get_chat(chat_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return meta


@router.patch("/{chat_id}", response_model=ChatMeta)
def update_chat(chat_id: str, body: ChatUpdate) -> ChatMeta:
    meta = store.get_chat(chat_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if meta.status == ChatStatus.APPROVED and body.status not in (None, ChatStatus.SUPERSEDED, ChatStatus.ARCHIVED):
        raise HTTPException(status_code=409, detail="Approved chats are readonly")
    updated = store.update_chat(chat_id, **body.model_dump(exclude_none=True))
    assert updated is not None
    return updated


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(chat_id: str) -> None:
    await browser_service.close_session(chat_id)
    browser_service.cleanup_profile(chat_id)
    ok = store.delete_chat(chat_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chat not found")


@router.get("/{chat_id}/document", response_model=DocumentRead)
def read_document(chat_id: str) -> DocumentRead:
    meta = store.get_chat(chat_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    content = store.read_guide(chat_id, meta.current_version)
    if content is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentRead(
        chat_id=chat_id,
        version=meta.current_version,
        content=content,
        readonly=meta.status == ChatStatus.APPROVED,
    )


@router.get("/{chat_id}/export.html")
def export_document(chat_id: str) -> HTMLResponse:
    meta = store.get_chat(chat_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    html = exporter.render_html(chat_id, meta.current_version, meta.name)
    if html is None:
        raise HTTPException(status_code=404, detail="Document not found")
    filename = slugify(meta.name) or "document"
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="{filename}.html"'},
    )


@router.put("/{chat_id}/document", response_model=DocumentRead)
def write_document(chat_id: str, body: DocumentWrite) -> DocumentRead:
    meta = store.get_chat(chat_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if meta.status == ChatStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Approved documents are readonly")
    ok = store.write_guide(chat_id, body.content, meta.current_version)
    if not ok:
        raise HTTPException(status_code=409, detail="Document write rejected")
    content = store.read_guide(chat_id, meta.current_version) or ""
    return DocumentRead(chat_id=chat_id, version=meta.current_version, content=content, readonly=False)
