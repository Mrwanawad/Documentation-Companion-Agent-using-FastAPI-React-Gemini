"""Browser walkthrough service — backed by chrome-devtools-mcp.

Same external API as before (open_session, click, fill, observe, describe_form,
close_session, format_evidence, step_event_payload) so the agent + the rest of
the codebase don't need to change. Internally it spawns a per-chat
chrome-devtools-mcp subprocess via `cdp_mcp` and translates our text-based
targets ('Continue', 'Email Address', `css=#foo`) into the UIDs that
chrome-devtools-mcp's a11y snapshot returns.

Authentication persistence happens via the per-chat `--user-data-dir` flag
passed to the MCP server (replaces the old Playwright `storage_state` flow).
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import cdp_mcp


# ---------------------------------------------------------------------------
# Evidence data structures (unchanged shape so agent.py / SSE / Markdown
# rendering don't have to change).
# ---------------------------------------------------------------------------


@dataclass
class EvidenceStep:
    action: str
    url: str
    title: str
    observed_labels: list[str]
    validation_messages: list[str]
    screenshot_filename: str  # under assets/annotated/
    notes: str = ""


@dataclass
class BrowserSession:
    chat_id: str
    version: str
    assets_root: Path
    asset_url_base: str
    steps: list[EvidenceStep] = field(default_factory=list)

    async def close(self) -> None:
        await cdp_mcp.close(self.chat_id)


_sessions: dict[str, BrowserSession] = {}


def get_session(chat_id: str) -> Optional[BrowserSession]:
    return _sessions.get(chat_id)


# ---------------------------------------------------------------------------
# Snapshot parsing — chrome-devtools-mcp returns the a11y tree as plain text:
#   uid=1_5 button "Continue"
#   uid=1_7 textbox "Email Address" url="..."
# We parse this to resolve our text-based targets to UIDs.
# ---------------------------------------------------------------------------


_SNAPSHOT_LINE_RE = re.compile(
    r"""uid=(?P<uid>\S+)\s+              # the UID token
        (?P<role>\S+)                     # role / element name
        (?:\s+"(?P<name>[^"]*)")?         # optional quoted accessible name
        (?P<rest>.*)$                     # everything else (attributes)
    """,
    re.VERBOSE,
)


# Roles that count as "click targets".
CLICK_ROLES = {"button", "link", "tab", "menuitem", "MenuItemCheckbox", "checkbox", "radio", "switch", "option"}
# Roles that count as "fillable inputs".
FILL_ROLES = {"textbox", "combobox", "searchbox", "spinbutton", "slider", "select"}


@dataclass
class SnapshotElement:
    uid: str
    role: str
    name: str
    attrs: str  # the raw trailing attribute text (placeholder=..., url=..., etc.)


def _parse_snapshot(text: str) -> list[SnapshotElement]:
    out: list[SnapshotElement] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("uid="):
            continue
        m = _SNAPSHOT_LINE_RE.match(line)
        if not m:
            continue
        out.append(
            SnapshotElement(
                uid=m.group("uid"),
                role=m.group("role"),
                name=(m.group("name") or "").strip(),
                attrs=(m.group("rest") or "").strip(),
            )
        )
    return out


def _looks_like_url(s: str) -> bool:
    s = (s or "").strip()
    return s.startswith("http://") or s.startswith("https://")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _resolve_target(
    elements: list[SnapshotElement], target: str, intent: str
) -> tuple[Optional[str], list[str]]:
    """Find the best uid for `target`. Returns (uid_or_None, tried_summary)."""
    t = (target or "").strip()
    if not t:
        return None, ["empty target"]
    t_lower = _norm(t)

    # Explicit `uid=` lets the agent target directly.
    if t.startswith("uid="):
        return t[len("uid="):].strip(), [f"explicit uid={t[4:]}"]

    # CSS / xpath escapes go through evaluate_script later — flag them.
    if t.startswith("css=") or t.startswith("xpath=") or t.startswith("//") or t[:1] in "#.[":
        return None, [f"css/xpath target {t!r} not directly mappable to MCP uid; use evaluate_script"]

    roles_priority = (
        ("button", "link", "tab", "menuitem", "option", "checkbox", "switch")
        if intent == "click"
        else ("textbox", "searchbox", "combobox", "select", "spinbutton")
    )

    # 1. exact name match within priority roles
    for role in roles_priority:
        for el in elements:
            if el.role == role and _norm(el.name) == t_lower:
                return el.uid, [f"exact {role}=‹{el.name}›"]

    # 2. substring name match within priority roles
    for role in roles_priority:
        for el in elements:
            if el.role == role and t_lower in _norm(el.name):
                return el.uid, [f"substring {role}=‹{el.name}›"]

    # 3. attribute match — placeholder/name/id often live in attrs string
    for el in elements:
        attrs_l = _norm(el.attrs)
        if t_lower in attrs_l:
            return el.uid, [f"attr-match role={el.role} attrs={el.attrs!r}"]

    # 4. last resort: any role with matching name
    for el in elements:
        if t_lower in _norm(el.name):
            return el.uid, [f"any-role={el.role} name=‹{el.name}›"]

    tried = [f"{e.role}:‹{e.name[:40]}›" for e in elements[:8]]
    return None, [f"no match; visible: {', '.join(tried) or '(empty snapshot)'}"]


# ---------------------------------------------------------------------------
# Observation: turn raw MCP outputs into our EvidenceStep + screenshot.
# ---------------------------------------------------------------------------


_TITLE_JS = "() => document.title"
_URL_JS = "() => location.href"
_VALIDATION_JS = """() => {
  const sel = '[role="alert"], .error, .invalid-feedback, [aria-invalid="true"], .help-block.error';
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(sel)) {
    const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!t || seen.has(t)) continue;
    seen.add(t); out.push(t.slice(0, 200));
    if (out.length >= 10) break;
  }
  return out;
}"""


async def _eval_js(session: BrowserSession, function_src: str) -> str:
    mcp = cdp_mcp.get(session.chat_id)
    assert mcp is not None
    return await mcp.call("evaluate_script", {"function": function_src})


def _strip_eval_wrapper(raw: str) -> str:
    """evaluate_script returns a markdown-ish block with the result. Pull the value out."""
    # The chrome-devtools-mcp output for evaluate_script looks like:
    #   ## Result
    #   ```
    #   <value>
    #   ```
    # — pull just the value between the first pair of backticks if present.
    m = re.search(r"```(?:\w+)?\n([\s\S]*?)\n```", raw)
    if m:
        return m.group(1).strip()
    return raw.strip()


def _extract_observed_labels(snapshot_text: str, limit: int = 30) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for el in _parse_snapshot(snapshot_text):
        if el.role in CLICK_ROLES or el.role in FILL_ROLES:
            name = el.name or el.attrs[:40]
            label = f"{el.role}: {name}".strip()
            if label in seen:
                continue
            seen.add(label)
            out.append(label[:80])
            if len(out) >= limit:
                break
    return out


async def _take_screenshot(session: BrowserSession) -> str:
    """Capture a screenshot via MCP and save it under assets/annotated/. Returns filename."""
    mcp = cdp_mcp.get(session.chat_id)
    assert mcp is not None
    filename = f"browser_{uuid.uuid4().hex[:10]}.png"
    out_dir = session.assets_root / "annotated"
    out_dir.mkdir(parents=True, exist_ok=True)

    # chrome-devtools-mcp's take_screenshot supports a filePath arg in some
    # versions; the universal path is to ask for a base64-encoded image back
    # and write it ourselves.
    try:
        raw = await mcp.call(
            "take_screenshot",
            {"format": "png", "filePath": str(out_dir / filename)},
        )
        # Some versions write the file and return a confirmation; others
        # return base64. If the file got written, we're done.
        if (out_dir / filename).exists():
            return filename
        # Otherwise look for a base64 payload in the response.
        m = re.search(r"base64,([A-Za-z0-9+/=]+)", raw)
        if m:
            (out_dir / filename).write_bytes(base64.b64decode(m.group(1)))
            return filename
    except Exception:
        # Fall through to the simpler form below.
        pass

    try:
        raw = await mcp.call("take_screenshot", {"format": "png"})
        m = re.search(r"base64,([A-Za-z0-9+/=]+)", raw)
        if m:
            (out_dir / filename).write_bytes(base64.b64decode(m.group(1)))
            return filename
    except Exception:
        pass

    # Last resort: keep going without an image.
    return ""


async def _record_step(session: BrowserSession, action: str, notes: str = "") -> EvidenceStep:
    mcp = cdp_mcp.get(session.chat_id)
    assert mcp is not None

    try:
        snapshot_text = await mcp.call("take_snapshot", {})
    except Exception as e:
        snapshot_text = ""
        if not notes:
            notes = f"take_snapshot failed: {e}"
    try:
        url = _strip_eval_wrapper(await _eval_js(session, _URL_JS)).strip('"').strip("'")
    except Exception:
        url = ""
    try:
        title = _strip_eval_wrapper(await _eval_js(session, _TITLE_JS)).strip('"').strip("'")
    except Exception:
        title = ""
    try:
        validations_raw = _strip_eval_wrapper(await _eval_js(session, _VALIDATION_JS))
        validations = json.loads(validations_raw) if validations_raw.startswith("[") else []
    except Exception:
        validations = []

    screenshot_filename = await _take_screenshot(session)
    step = EvidenceStep(
        action=action,
        url=url,
        title=title,
        observed_labels=_extract_observed_labels(snapshot_text),
        validation_messages=validations,
        screenshot_filename=screenshot_filename,
        notes=notes,
    )
    session.steps.append(step)
    return step


# ---------------------------------------------------------------------------
# Public API — same shape as the old Playwright-backed module.
# ---------------------------------------------------------------------------


async def open_session(
    chat_id: str,
    version: str,
    assets_root: Path,
    asset_url_base: str,
    url: str,
) -> tuple[BrowserSession, EvidenceStep]:
    if not _looks_like_url(url):
        raise ValueError(f"Refusing to open non-http(s) URL: {url!r}")

    # Reset any prior session for this chat.
    existing = _sessions.pop(chat_id, None)
    if existing is not None:
        await existing.close()

    await cdp_mcp.start(chat_id)
    session = BrowserSession(
        chat_id=chat_id,
        version=version,
        assets_root=assets_root,
        asset_url_base=asset_url_base,
    )
    _sessions[chat_id] = session

    mcp = cdp_mcp.get(chat_id)
    assert mcp is not None
    # Force a desktop viewport — chrome-devtools-mcp defaults to a mobile-ish
    # size, which makes responsive layouts render their narrow variant. Most
    # SaaS / ERP guides target the desktop view, so we want that by default.
    try:
        await mcp.call("resize_page", {"width": 1280, "height": 800})
    except Exception:
        pass
    try:
        await mcp.call("navigate_page", {"url": url})
    except Exception as e:
        step = await _record_step(session, f"Navigate to {url} (failed)", notes=str(e))
        return session, step

    step = await _record_step(session, f"Navigate to {url}")
    return session, step


async def observe(chat_id: str) -> EvidenceStep:
    session = _sessions.get(chat_id)
    if session is None:
        raise RuntimeError("No browser session — call browser_open first.")
    return await _record_step(session, "Observe current page")


async def click(chat_id: str, target: str) -> tuple[EvidenceStep, Optional[str]]:
    session = _sessions.get(chat_id)
    if session is None:
        raise RuntimeError("No browser session — call browser_open first.")
    mcp = cdp_mcp.get(chat_id)
    assert mcp is not None

    snapshot_text = await mcp.call("take_snapshot", {})
    elements = _parse_snapshot(snapshot_text)
    uid, why = _resolve_target(elements, target, intent="click")
    if uid is None:
        notes = f"No element matches {target!r}. {why[0]}"
        step = await _record_step(session, f"Click {target!r} (failed)", notes=notes)
        return step, notes

    try:
        await mcp.call("click", {"uid": uid})
        step = await _record_step(session, f"Click {target!r} (uid={uid})")
        return step, None
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        step = await _record_step(session, f"Click {target!r} (uid={uid}) (failed)", notes=msg)
        return step, msg


async def fill(chat_id: str, target: str, value: str) -> tuple[EvidenceStep, Optional[str]]:
    session = _sessions.get(chat_id)
    if session is None:
        raise RuntimeError("No browser session — call browser_open first.")
    mcp = cdp_mcp.get(chat_id)
    assert mcp is not None

    snapshot_text = await mcp.call("take_snapshot", {})
    elements = _parse_snapshot(snapshot_text)
    uid, why = _resolve_target(elements, target, intent="fill")
    if uid is None:
        notes = f"No input matches {target!r}. {why[0]}"
        step = await _record_step(session, f"Fill {target!r} (failed)", notes=notes)
        return step, notes

    safe_value = "***" if any(k in target.lower() for k in ("password", "pwd", "secret", "token")) else value
    try:
        await mcp.call("fill", {"uid": uid, "value": value})
        step = await _record_step(session, f"Fill {target!r} with {safe_value!r} (uid={uid})")
        return step, None
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        step = await _record_step(
            session, f"Fill {target!r} with {safe_value!r} (uid={uid}) (failed)", notes=msg
        )
        return step, msg


_DESCRIBE_FORM_JS = r"""() => {
  const out = [];
  const sel = 'input:not([type="hidden"]):not([type="submit"]):not([type="button"]),'
            + ' textarea, select';
  for (const el of document.querySelectorAll(sel)) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (rect.width === 0 && rect.height === 0) continue;
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    let label = '';
    if (el.id) {
      const lbl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (lbl) label = (lbl.innerText || lbl.textContent || '').trim();
    }
    if (!label && el.labels && el.labels.length > 0) {
      label = (el.labels[0].innerText || '').trim();
    }
    if (!label) label = (el.getAttribute('aria-label') || '').trim();
    const type = (el.type || el.tagName).toLowerCase();
    const required = el.required || el.hasAttribute('data-val-required')
                  || el.getAttribute('aria-required') === 'true';
    const validation = {};
    const m = (k, attr) => { const v = el.getAttribute(attr); if (v) validation[k] = v; };
    m('required', 'data-val-required');
    m('email', 'data-val-email');
    m('pattern', 'data-val-regex');
    m('regex', 'pattern');
    m('minLength', 'minlength');
    m('maxLength', 'maxlength');
    m('min', 'min');
    m('max', 'max');
    let options = [];
    if (el.tagName.toLowerCase() === 'select') {
      options = Array.from(el.options).map(o => ({value:o.value, text:(o.text||'').trim()})).slice(0,30);
    }
    out.push({
      tag: el.tagName.toLowerCase(),
      type, id: el.id || '', name: el.name || '',
      label, placeholder: el.placeholder || '',
      required, value: (type === 'password') ? '' : (el.value || ''),
      validation, options,
    });
    if (out.length >= 80) break;
  }
  return out;
}"""


async def describe_form(chat_id: str) -> list[dict[str, Any]]:
    session = _sessions.get(chat_id)
    if session is None:
        raise RuntimeError("No browser session — call browser_open first.")
    raw = await _eval_js(session, _DESCRIBE_FORM_JS)
    body = _strip_eval_wrapper(raw)
    try:
        return json.loads(body)
    except Exception:
        return []


async def close_session(chat_id: str) -> Optional[BrowserSession]:
    sess = _sessions.pop(chat_id, None)
    if sess is None:
        # Always still try to tear down a dangling MCP process for this chat.
        await cdp_mcp.close(chat_id)
        return None
    await sess.close()  # this in turn closes the MCP process
    return sess


# ---------------------------------------------------------------------------
# Inspection tools that we expose as their own agent functions.
# These delegate straight to the MCP server.
# ---------------------------------------------------------------------------


async def console_messages(chat_id: str) -> str:
    mcp = cdp_mcp.get(chat_id)
    if mcp is None:
        raise RuntimeError("No browser session — call browser_open first.")
    return await mcp.call("list_console_messages", {})


async def network_requests(chat_id: str, page_size: int = 30) -> str:
    mcp = cdp_mcp.get(chat_id)
    if mcp is None:
        raise RuntimeError("No browser session — call browser_open first.")
    return await mcp.call("list_network_requests", {"pageSize": page_size})


async def network_request_detail(chat_id: str, url: str) -> str:
    mcp = cdp_mcp.get(chat_id)
    if mcp is None:
        raise RuntimeError("No browser session — call browser_open first.")
    return await mcp.call("get_network_request", {"url": url})


async def evaluate(chat_id: str, function_src: str) -> str:
    mcp = cdp_mcp.get(chat_id)
    if mcp is None:
        raise RuntimeError("No browser session — call browser_open first.")
    raw = await mcp.call("evaluate_script", {"function": function_src})
    return _strip_eval_wrapper(raw)


async def lighthouse_audit(chat_id: str, categories: list[str] | None = None) -> str:
    mcp = cdp_mcp.get(chat_id)
    if mcp is None:
        raise RuntimeError("No browser session — call browser_open first.")
    args: dict[str, Any] = {}
    if categories:
        args["categories"] = categories
    return await mcp.call("lighthouse_audit", args)


# ---------------------------------------------------------------------------
# Evidence formatting + SSE payload (unchanged shape).
# ---------------------------------------------------------------------------


def format_evidence(session: BrowserSession) -> str:
    if not session.steps:
        return "_No browser steps were recorded._"
    first_url = session.steps[0].url
    lines: list[str] = [f"**Environment / URL:** {first_url}", ""]
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


# ---------------------------------------------------------------------------
# Lifecycle hook the app calls on shutdown.
# ---------------------------------------------------------------------------


async def shutdown_browsers() -> None:
    """Close all sessions + their MCP subprocesses. Call on FastAPI shutdown."""
    for chat_id in list(_sessions.keys()):
        try:
            await close_session(chat_id)
        except Exception:
            pass
    await cdp_mcp.shutdown_all()


# ---------------------------------------------------------------------------
# Profile cleanup hook for chat delete.
# ---------------------------------------------------------------------------


def cleanup_profile(chat_id: str) -> None:
    """Wipe the per-chat Chrome profile directory. Called on chat delete."""
    profile = cdp_mcp.profile_dir_for(chat_id)
    if profile.exists():
        try:
            shutil.rmtree(profile)
        except Exception:
            pass
