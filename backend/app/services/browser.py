"""Per-chat headless browser session driven by the agent.

Lifecycle: a session is created on the first `browser_open` tool call and lives
until the agent calls `browser_close` (or the chat is deleted / backend shuts
down). All actions auto-capture a screenshot and a structured snapshot of the
visible interactive controls and validation messages, which feed into the
Browser Walkthrough Evidence section of the page guide.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import (
    Browser,
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    async_playwright,
)


# Per-process: one Playwright runtime + one Chromium browser are reused across
# all chat sessions. Each session gets its own browser context (cookies, etc.)
# and a single page within it.
_pw_lock = asyncio.Lock()
_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None


async def _ensure_browser() -> Browser:
    global _playwright, _browser
    async with _pw_lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        if _playwright is None:
            _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
        return _browser


async def shutdown_browsers() -> None:
    """Close all sessions + the shared browser. Call on app shutdown."""
    global _playwright, _browser
    for sess in list(_sessions.values()):
        try:
            await sess.close()
        except Exception:
            pass
    _sessions.clear()
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None


@dataclass
class EvidenceStep:
    action: str
    url: str
    title: str
    observed_labels: list[str]
    validation_messages: list[str]
    screenshot_filename: str  # relative to assets/annotated/ (reusing that folder)
    notes: str = ""


@dataclass
class BrowserSession:
    chat_id: str
    version: str
    assets_root: Path
    asset_url_base: str
    page: Page
    context: Any  # BrowserContext
    steps: list[EvidenceStep] = field(default_factory=list)

    async def close(self) -> None:
        try:
            await self.page.close()
        except Exception:
            pass
        try:
            await self.context.close()
        except Exception:
            pass


_sessions: dict[str, BrowserSession] = {}


def get_session(chat_id: str) -> Optional[BrowserSession]:
    return _sessions.get(chat_id)


async def open_session(
    chat_id: str,
    version: str,
    assets_root: Path,
    asset_url_base: str,
    url: str,
) -> tuple[BrowserSession, EvidenceStep]:
    """Open a new session (closing any existing one), navigate, return first step."""
    if not _looks_like_url(url):
        raise ValueError(f"Refusing to open non-http(s) URL: {url!r}")

    existing = _sessions.pop(chat_id, None)
    if existing is not None:
        await existing.close()

    browser = await _ensure_browser()
    context = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()
    session = BrowserSession(
        chat_id=chat_id,
        version=version,
        assets_root=assets_root,
        asset_url_base=asset_url_base,
        page=page,
        context=context,
    )
    _sessions[chat_id] = session

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    except PWTimeoutError:
        # Goto timeout is non-fatal for evidence purposes — capture what we have.
        pass

    step = await _record_step(session, f"Navigate to {url}")
    return session, step


async def _wait_settled(page: Page) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=4_000)
    except PWTimeoutError:
        pass


async def _snapshot_observations(page: Page) -> tuple[list[str], list[str]]:
    """Return (interactive_labels, validation_messages) seen on the page."""
    try:
        # Interactive control labels (truncated).
        labels = await page.evaluate(
            """() => {
              const out = [];
              const seen = new Set();
              const sel = 'button, a, input, select, textarea, [role="button"], [role="link"], [role="tab"]';
              const els = Array.from(document.querySelectorAll(sel));
              for (const el of els) {
                if (out.length >= 30) break;
                const tag = el.tagName.toLowerCase();
                let text = '';
                if (tag === 'input' || tag === 'textarea' || tag === 'select') {
                  text = el.getAttribute('placeholder') || el.getAttribute('aria-label')
                       || el.getAttribute('name') || el.getAttribute('id') || '';
                  if (!text && tag === 'input') text = el.getAttribute('type') || '';
                } else {
                  text = (el.innerText || el.getAttribute('aria-label') || '').trim();
                }
                text = (text || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
                if (!text) continue;
                const key = tag + '|' + text;
                if (seen.has(key)) continue;
                seen.add(key);
                out.push(`${tag}: ${text}`);
              }
              return out;
            }"""
        )
    except Exception:
        labels = []

    try:
        validations = await page.evaluate(
            """() => {
              const sel = '[role="alert"], .error, .invalid-feedback, [aria-invalid="true"], .help-block.error';
              const out = [];
              const seen = new Set();
              for (const el of document.querySelectorAll(sel)) {
                const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                if (!t || seen.has(t)) continue;
                seen.add(t);
                out.push(t.slice(0, 200));
                if (out.length >= 10) break;
              }
              return out;
            }"""
        )
    except Exception:
        validations = []

    return list(labels or []), list(validations or [])


async def _record_step(session: BrowserSession, action: str) -> EvidenceStep:
    page = session.page
    await _wait_settled(page)

    try:
        title = (await page.title()) or ""
    except Exception:
        title = ""
    url = page.url
    labels, validations = await _snapshot_observations(page)

    filename = f"browser_{uuid.uuid4().hex[:10]}.png"
    out_dir = session.assets_root / "annotated"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(out_dir / filename), full_page=False)
    except Exception:
        filename = ""

    step = EvidenceStep(
        action=action,
        url=url,
        title=title,
        observed_labels=labels,
        validation_messages=validations,
        screenshot_filename=filename,
    )
    session.steps.append(step)
    return step


def _looks_like_url(s: str) -> bool:
    s = (s or "").strip()
    return s.startswith("http://") or s.startswith("https://")


PER_STRATEGY_TIMEOUT_MS = 2_000


async def observe(chat_id: str) -> EvidenceStep:
    """Re-snapshot the current page without acting on it."""
    session = _sessions.get(chat_id)
    if session is None:
        raise RuntimeError("No browser session — call browser_open first.")
    return await _record_step(session, "Observe current page")


async def click(chat_id: str, target: str) -> tuple[EvidenceStep, Optional[str]]:
    """Click an element. `target` may be visible text, placeholder/label, or `css=…`."""
    session = _sessions.get(chat_id)
    if session is None:
        raise RuntimeError("No browser session — call browser_open first.")

    err = await _try_action(
        _candidate_locators(session.page, target, intent="click"),
        target,
        lambda loc: loc.click(timeout=PER_STRATEGY_TIMEOUT_MS),
    )
    action = f"Click {target!r}" + ("" if err is None else " (failed)")
    step = await _record_step(session, action)
    if err is not None:
        step.notes = err
    return step, err


async def fill(chat_id: str, target: str, value: str) -> tuple[EvidenceStep, Optional[str]]:
    """Fill an input. `target` may be placeholder/label, visible text, or `css=…`."""
    session = _sessions.get(chat_id)
    if session is None:
        raise RuntimeError("No browser session — call browser_open first.")

    err = await _try_action(
        _candidate_locators(session.page, target, intent="fill"),
        target,
        lambda loc: loc.fill(value, timeout=PER_STRATEGY_TIMEOUT_MS),
    )
    action = f"Fill {target!r} with {value!r}" + ("" if err is None else " (failed)")
    step = await _record_step(session, action)
    if err is not None:
        step.notes = err
    return step, err


async def _try_action(candidates, target: str, action) -> Optional[str]:
    """Run `action(locator)` against each candidate until one succeeds.

    Returns None on success; otherwise a human-friendly summary of which
    strategies were tried, which had matches, and why the actionable one
    failed (if any).
    """
    tried: list[str] = []
    actionable_error: Optional[str] = None
    actionable_strategy: Optional[str] = None

    for name, loc in candidates:
        try:
            count = await loc.count()
        except Exception:
            count = 0
        if count == 0:
            tried.append(f"{name}=0")
            continue
        tried.append(f"{name}={count}")
        try:
            await action(loc)
            return None
        except Exception as e:
            # First match exists but couldn't be acted on (hidden / disabled /
            # not the actual control). Remember the most specific error.
            if actionable_error is None:
                actionable_error = f"{type(e).__name__}: {_short_msg(e)}"
                actionable_strategy = name
            continue

    summary = ", ".join(tried) if tried else "(no strategies attempted)"
    if actionable_error is not None:
        return (
            f"No element matching {target!r} could be acted on. "
            f"Tried [{summary}]; closest match via {actionable_strategy} failed with: {actionable_error}. "
            f"Suggest passing `css=#id`, the field's `name`/`id`, or its exact visible label."
        )
    return (
        f"No element on the page matches {target!r}. "
        f"Tried [{summary}]. "
        f"Check the spelling of the visible label/placeholder, or pass `css=#id` instead."
    )


def _short_msg(e: Exception) -> str:
    msg = str(e).strip()
    # Playwright errors include the full call log — keep the first line, which
    # is the actual cause; the rest is wait-loop noise.
    first_line = msg.splitlines()[0] if msg else ""
    return first_line[:200]


def _candidate_locators(page: Page, target: str, intent: str):
    """Yield (strategy_name, locator) pairs in priority order.

    Every locator is wrapped in `.first` so a strict-mode violation (multiple
    matching elements, common with hidden duplicate inputs) becomes a clean
    match on the first visible one instead of a hard failure.
    """
    t = (target or "").strip()
    if not t:
        return

    # Explicit prefixes win — no fallbacks.
    if t.startswith("css="):
        yield "css", page.locator(t[len("css=") :]).first
        return
    if t.startswith("text="):
        yield "text=", page.get_by_text(t[len("text=") :], exact=False).first
        return
    if t.startswith("xpath=") or t.startswith("//"):
        body = t[len("xpath=") :] if t.startswith("xpath=") else t
        yield "xpath", page.locator(f"xpath={body}").first
        return
    # Bare CSS hint (id, class, attribute selector).
    if t[0] in "#.[":
        yield "css", page.locator(t).first
        return

    if intent == "fill":
        yield "placeholder", page.get_by_placeholder(t).first
        yield "label", page.get_by_label(t, exact=False).first
        yield "role:textbox", page.get_by_role("textbox", name=t).first
        yield "name/id", page.locator(
            f'input[name="{t}"], input[id="{t}"], textarea[name="{t}"], textarea[id="{t}"]'
        ).first
        yield "text", page.get_by_text(t, exact=False).first
    else:
        yield "role:button", page.get_by_role("button", name=t).first
        yield "role:link", page.get_by_role("link", name=t).first
        yield "role:tab", page.get_by_role("tab", name=t).first
        yield "label", page.get_by_label(t, exact=False).first
        yield "text", page.get_by_text(t, exact=False).first
        yield "aria-label", page.locator(f'[aria-label="{t}"]').first


async def close_session(chat_id: str) -> Optional[BrowserSession]:
    """Pop and close the session for this chat. Returns it (or None) for evidence formatting."""
    sess = _sessions.pop(chat_id, None)
    if sess is None:
        return None
    await sess.close()
    return sess


def format_evidence(session: BrowserSession) -> str:
    """Render the recorded steps as Markdown for the Browser Walkthrough Evidence section."""
    if not session.steps:
        return "_No browser steps were recorded._"

    first_url = session.steps[0].url
    lines: list[str] = [
        f"**Environment / URL:** {first_url}",
        "",
    ]
    for i, step in enumerate(session.steps, start=1):
        lines.append(f"#### Step {i}: {step.action}")
        lines.append("")
        lines.append(f"- **URL after:** {step.url}")
        if step.title:
            lines.append(f"- **Page title:** {step.title}")
        if step.observed_labels:
            joined = "; ".join(step.observed_labels[:12])
            lines.append(f"- **Observed controls:** {joined}")
        if step.validation_messages:
            joined = " · ".join(step.validation_messages)
            lines.append(f"- **Validation messages:** {joined}")
        if step.notes:
            lines.append(f"- **Note:** {step.notes}")
        if step.screenshot_filename:
            url = f"{session.asset_url_base}/annotated/{step.screenshot_filename}"
            lines.append("")
            lines.append(f"![Step {i} screenshot]({url})")
        lines.append("")
    return "\n".join(lines).rstrip()


def step_event_payload(session: BrowserSession, step: EvidenceStep) -> dict[str, Any]:
    """SSE-friendly serialization of a single step."""
    screenshot_url = (
        f"{session.asset_url_base}/annotated/{step.screenshot_filename}"
        if step.screenshot_filename
        else None
    )
    return {
        "action": step.action,
        "url": step.url,
        "title": step.title,
        "observed_labels": step.observed_labels[:12],
        "validation_messages": step.validation_messages,
        "screenshot_url": screenshot_url,
        "notes": step.notes,
    }
