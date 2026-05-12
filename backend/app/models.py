from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ChatStatus(str, Enum):
    DRAFT = "draft"
    COMPLETE = "complete"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatMeta(BaseModel):
    id: str
    name: str
    browser_enabled: bool = True
    status: ChatStatus = ChatStatus.DRAFT
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    current_version: str = "v1.0"


class ChatCreate(BaseModel):
    name: str
    browser_enabled: bool = True


class ChatUpdate(BaseModel):
    name: Optional[str] = None
    browser_enabled: Optional[bool] = None
    status: Optional[ChatStatus] = None


class DocumentRead(BaseModel):
    chat_id: str
    version: str
    content: str
    readonly: bool


class DocumentWrite(BaseModel):
    content: str
