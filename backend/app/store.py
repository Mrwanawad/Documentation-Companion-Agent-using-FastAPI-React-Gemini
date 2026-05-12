import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

from .config import settings
from .models import ChatMeta, ChatStatus, utcnow_iso


GUIDE_TEMPLATE = """# {name}

_Page-level user guide. This document describes a single page/screen within the system._

## Document Status
- **Status:** Draft
- **Version:** v1.0

## Version History
- v1.0 — Draft created

## Page Overview
_What this page is and what it lets the user do. One short paragraph._

## Where To Find This Page
_Navigation path from the app entry point (e.g. Sidebar → Projects → Boards)._

## Who Can Access
_Roles and permissions required to view/use this page._

## Page Layout
_The main visual regions of the page (header, list, form, side panel, footer)._

## How To Use This Page
_Step-by-step instructions for the most common tasks performed on this page._

## Form Fields & Validations
_For pages with inputs: each field's label, type, required?, validation rule, default._

## Tips & Shortcuts
_Keyboard shortcuts, less obvious behaviors, power-user tips._

## Browser Walkthrough Evidence
_TBD_

## Screenshots And Assets
_Annotated screenshots of the page with element tables go here._

## Limitations & Known Issues
_Things this page can't do today, or known bugs._

## Gaps & Red Flags
_None recorded yet._

## FAQ
_Common questions about this page._

## Approval
- **Reviewer:** Coject R&D Team
- **State:** pending
"""


def _ws() -> Path:
    p = settings.workspace_path
    (p / "chats").mkdir(parents=True, exist_ok=True)
    (p / "documents").mkdir(parents=True, exist_ok=True)
    return p


def _chat_dir(chat_id: str) -> Path:
    return _ws() / "chats" / chat_id


def _doc_dir(chat_id: str, version: str = "v1.0") -> Path:
    return _ws() / "documents" / chat_id / version


def _meta_path(chat_id: str) -> Path:
    return _chat_dir(chat_id) / "meta.json"


def _guide_path(chat_id: str, version: str = "v1.0") -> Path:
    return _doc_dir(chat_id, version) / "guide.md"


def _metadata_path(chat_id: str, version: str = "v1.0") -> Path:
    return _doc_dir(chat_id, version) / "metadata.json"


def list_chats() -> list[ChatMeta]:
    _ws()
    chats: list[ChatMeta] = []
    for child in (_ws() / "chats").iterdir():
        if not child.is_dir():
            continue
        meta_file = child / "meta.json"
        if not meta_file.exists():
            continue
        try:
            chats.append(ChatMeta(**json.loads(meta_file.read_text())))
        except Exception:
            continue
    chats.sort(key=lambda c: c.updated_at, reverse=True)
    return chats


def get_chat(chat_id: str) -> Optional[ChatMeta]:
    path = _meta_path(chat_id)
    if not path.exists():
        return None
    return ChatMeta(**json.loads(path.read_text()))


def create_chat(name: str, browser_enabled: bool) -> ChatMeta:
    chat_id = uuid.uuid4().hex[:12]
    meta = ChatMeta(id=chat_id, name=name, browser_enabled=browser_enabled)
    chat_dir = _chat_dir(chat_id)
    chat_dir.mkdir(parents=True, exist_ok=True)
    _meta_path(chat_id).write_text(meta.model_dump_json(indent=2))

    doc_dir = _doc_dir(chat_id)
    (doc_dir / "assets" / "uploaded").mkdir(parents=True, exist_ok=True)
    (doc_dir / "assets" / "annotated").mkdir(parents=True, exist_ok=True)
    _guide_path(chat_id).write_text(GUIDE_TEMPLATE.format(name=name))
    _metadata_path(chat_id).write_text(json.dumps({
        "product": name,
        "version": "v1.0",
        "status": "draft",
        "language": "en",
        "approvedBy": "TBD",
        "approvedAt": "TBD",
        "source": "Documentation Companion Agent",
        "coverageTarget": "95% product-owner self-service",
        "browserEnabled": browser_enabled,
    }, indent=2))
    return meta


def update_chat(chat_id: str, **changes) -> Optional[ChatMeta]:
    meta = get_chat(chat_id)
    if meta is None:
        return None
    data = meta.model_dump()
    for k, v in changes.items():
        if v is not None:
            data[k] = v
    data["updated_at"] = utcnow_iso()
    new_meta = ChatMeta(**data)
    _meta_path(chat_id).write_text(new_meta.model_dump_json(indent=2))
    return new_meta


def touch_chat(chat_id: str) -> None:
    meta = get_chat(chat_id)
    if meta is None:
        return
    update_chat(chat_id, updated_at=utcnow_iso())


def delete_chat(chat_id: str) -> bool:
    chat_dir = _chat_dir(chat_id)
    doc_dir = _ws() / "documents" / chat_id
    existed = chat_dir.exists() or doc_dir.exists()
    if chat_dir.exists():
        shutil.rmtree(chat_dir)
    if doc_dir.exists():
        shutil.rmtree(doc_dir)
    return existed


def read_guide(chat_id: str, version: str = "v1.0") -> Optional[str]:
    path = _guide_path(chat_id, version)
    if not path.exists():
        return None
    return path.read_text()


def write_guide(chat_id: str, content: str, version: str = "v1.0") -> bool:
    meta = get_chat(chat_id)
    if meta is None:
        return False
    if meta.status == ChatStatus.APPROVED:
        return False
    _guide_path(chat_id, version).write_text(content)
    update_chat(chat_id, updated_at=utcnow_iso())
    return True
