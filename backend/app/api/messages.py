"""POST /api/chats/{id}/messages — streams the agent's reply as SSE."""

from collections import defaultdict

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from google.genai import types
from pydantic import BaseModel

from .. import store
from ..services import agent


router = APIRouter(prefix="/api/chats", tags=["messages"])


# In-memory chat history per chat_id. Wiped on server restart (matches the
# "chat history is ephemeral" requirement: documents persist, chat does not).
_history: dict[str, list[types.Content]] = defaultdict(list)


class MessageBody(BaseModel):
    text: str


@router.post("/{chat_id}/messages")
async def post_message(chat_id: str, body: MessageBody) -> StreamingResponse:
    chat = store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Message text is required")

    history = _history[chat_id]
    stream = agent.run_turn(chat, history, body.text.strip())

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
