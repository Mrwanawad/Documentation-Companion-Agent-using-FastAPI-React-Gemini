"""Per-chat Chrome DevTools MCP session manager.

Spawns `npx chrome-devtools-mcp` as a stdio subprocess per chat, holds the
ClientSession open across HTTP requests via AsyncExitStack, and exposes a
simple `call(name, args)` API that returns the text content of MCP tool
responses (which is how chrome-devtools-mcp formats its output — designed
for direct LLM consumption).

Per-chat lifecycle gives:
- Browser isolation between chats (separate user-data-dir).
- Persistent auth via the user-data-dir (replaces the old auth.json file).
- Clean teardown on chat delete / app shutdown.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..config import settings


class McpSession:
    """A single chrome-devtools-mcp subprocess + ClientSession."""

    def __init__(self, chat_id: str, profile_dir: Path):
        self.chat_id = chat_id
        self.profile_dir = profile_dir
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None
        # The MCP client itself isn't safe to call concurrently from multiple
        # tasks — serialize per session.
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        params = StdioServerParameters(
            command="npx",
            args=[
                "-y",
                "chrome-devtools-mcp@latest",
                "--headless=true",
                f"--user-data-dir={self.profile_dir}",
                "--no-usage-statistics",
                "--no-performance-crux",
            ],
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

    async def call(self, name: str, args: dict[str, Any] | None = None) -> str:
        """Call an MCP tool. Returns the text content of the response.
        Raises RuntimeError if the tool returned an error."""
        if self.session is None:
            raise RuntimeError("MCP session not started")
        async with self._lock:
            result = await self.session.call_tool(name, args or {})
        text = result.content[0].text if result.content else ""
        if result.isError:
            raise RuntimeError(text or f"{name} returned an error")
        return text

    async def close(self) -> None:
        try:
            await self._stack.aclose()
        finally:
            self.session = None


_sessions: dict[str, McpSession] = {}
_starting: dict[str, asyncio.Lock] = {}


def get(chat_id: str) -> Optional[McpSession]:
    return _sessions.get(chat_id)


def profile_dir_for(chat_id: str) -> Path:
    return settings.workspace_path / "chats" / chat_id / "browser-profile"


async def start(chat_id: str) -> McpSession:
    """Start (or return existing) MCP session for this chat."""
    existing = _sessions.get(chat_id)
    if existing is not None:
        return existing
    lock = _starting.setdefault(chat_id, asyncio.Lock())
    async with lock:
        # Re-check in case another task started it while we waited.
        existing = _sessions.get(chat_id)
        if existing is not None:
            return existing
        sess = McpSession(chat_id, profile_dir_for(chat_id))
        await sess.start()
        _sessions[chat_id] = sess
        return sess


async def close(chat_id: str) -> Optional[McpSession]:
    sess = _sessions.pop(chat_id, None)
    if sess is not None:
        try:
            await sess.close()
        except Exception:
            pass
    return sess


async def shutdown_all() -> None:
    for chat_id in list(_sessions.keys()):
        await close(chat_id)
