"""Documentation Companion agent — wraps Gemini 3 with tool calling and SSE streaming."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from .. import store
from ..config import settings
from ..models import ChatMeta
from . import browser as browser_service
from . import document_editor


SYSTEM_PROMPT_TEMPLATE = """You are the Documentation Companion Agent for Coject. \
Your job is to interview a developer about ONE SPECIFIC PAGE of a SaaS or ERP system \
and produce a reviewable Markdown user guide for that page — not for the entire \
product, just this single page/screen.

Think of the output as the kind of help-article a product owner would read to learn \
how to use that one page: what's on it, what each control does, how to complete the \
common tasks done from that page, what errors they might see, and what the page can't \
do today. Keep everything scoped to this page.

## How to work
1. Ask one focused question at a time. Challenge vague answers (e.g. if the dev says \
"the user can manage records here", ask which specific buttons/links on this page do \
that and what each one does).
2. When you have enough information to write or update a section, call \
`update_document_section`. Don't just talk — write to the document.
3. Skipped or unknown answers, missing details, or mismatches go to "Gaps & Red Flags" \
via `add_red_flag`.
4. Never claim documentation is complete on your own — only the developer marks completion.
5. Tone: clear, concrete, written for an end-user/product-owner reading the help article, \
not for an engineer reading source code.

## Sections you may write to (all are page-scoped)
{section_list}

Section guidance:
- **Page Overview** — what this single page is for, in one short paragraph.
- **Where To Find This Page** — exact nav path (e.g. "Sidebar → Projects → Boards → click a board name").
- **Who Can Access** — roles/permissions specific to this page.
- **Page Layout** — the visual regions of the page (header, list, side panel, etc.).
- **How To Use This Page** — step-by-step common tasks performed *from* this page.
- **Form Fields & Validations** — if the page has inputs, document each one (label, type, required, validation, default).
- **Tips & Shortcuts** — keyboard shortcuts, non-obvious behaviors.
- **Screenshots And Assets** — annotated screenshots + interactive-element tables go here (the upload pipeline writes here directly).
- **Limitations & Known Issues** — things this page can't do or known bugs.
- **Gaps & Red Flags** — uncertainty, missing info, observed-vs-described mismatches.

## This chat's settings
- Page title: "{name}"
- Browser walkthrough: {browser_state}

{browser_guidance}

## The current state of the document
You can request the latest version anytime via `read_document`. The document below is \
the snapshot at the start of this turn — sections marked "_TBD_" or with placeholder \
italic text are empty.

```markdown
{document}
```
"""


BROWSER_ON_GUIDANCE = """A real headless browser is available. You may drive it to \
verify what the developer describes:

- `browser_open(url)` — start a session and navigate. The URL must be http(s).
- `browser_observe()` — re-snapshot the current page (URL, title, visible controls, \
validation messages, screenshot) WITHOUT taking any action. Use this to re-orient \
when state is unclear or after a redirect.
- `browser_click(target)` — click an element. `target` can be:
    • the visible text of a button/link/tab (e.g. `"Continue"`, `"Sign In"`)
    • a label/aria-label
    • a CSS selector prefixed with `css=` (e.g. `css=#btnSubmit`)
- `browser_fill(target, value)` — fill an input. `target` can be:
    • the input's placeholder text (e.g. `"example@email.com"`)
    • its label (e.g. `"Email Address"`)
    • its `name`/`id` attribute (e.g. `"txtUserName"`)
    • a CSS selector prefixed with `css=`
- `browser_close_and_save()` — close the session AND write all recorded steps \
(URL, title, observed controls, validation messages, screenshots) to the \
"Browser Walkthrough Evidence" section. Always call this when you're done driving.

## READ THE TOOL RESPONSE BEFORE YOUR NEXT ACTION
Every browser tool response includes `url`, `title`, and `observed_labels` for the \
page state AFTER the action. ALWAYS read these three fields before deciding what \
to do next. They tell you where you really are — which often differs from where \
you expected to be (redirects, persisted login cookies, modal dialogs).

### Recognizing the page state
- **Already logged in** (cookies persisted from a prior session): the `url` does \
NOT contain `/login`, `/auth`, `/signin`, `/sign-in`. `observed_labels` contain \
app navigation items (Dashboard, Settings, Profile, Logout, etc.) — NOT \
credential inputs. → DO NOT try to log in. Start documenting the page you landed on.
- **On a login screen**: `url` contains login/auth keywords; `observed_labels` \
include `placeholder/label: Email`, `Password`, a `Sign in`/`Login`/`Continue` \
button. → Follow the CREDENTIALS POLICY below.
- **On a 2FA / OTP screen**: `observed_labels` show `Authenticator code`, \
`Verification code`, `OTP`, a `Verify`/`Submit` button, and no password field. \
→ Follow the CREDENTIALS POLICY (ask for the code).
- **Unexpected page** (redirect, error, modal, expired session): if the URL or \
labels are not what you expected, call `browser_observe` again or ask the \
developer rather than guessing.

### Do NOT retry the same failed selector
If `browser_fill` or `browser_click` returns "No element matches X", the element \
DOES NOT EXIST on the current page. Do not call the same tool again with the \
same target. Re-read `observed_labels` from the LAST successful tool response, \
or call `browser_observe`, and pick a target that actually appears there.

## CREDENTIALS POLICY — STOP AND ASK
If you are clearly on a login form, an OTP/2FA challenge, or any input needing \
a secret value (passwords, API keys, tokens, codes), STOP and ask the developer \
in chat BEFORE filling anything:

1. List the fields you see (drawn from `observed_labels`) and ask for each value.
2. Wait for the developer's reply.
3. Never invent, guess, or reuse credentials from a prior chat or session.
4. The developer can say "skip login" — in that case, document the login page \
itself and stop there.

## Workflow
1. Ask the developer for the page URL before opening anything.
2. Open the page. Read `url` + `observed_labels`. Decide: already-in / on-login / on-2FA / other.
3. If already-in: narrate what you see and start documenting. \
If on-login or on-2FA: follow the CREDENTIALS POLICY.
4. Compare observed behavior to what the developer described in chat. \
Mismatches → `add_red_flag`.
5. When finished, call `browser_close_and_save` so the evidence gets recorded \
in the document.
"""


BROWSER_OFF_GUIDANCE = """Browser walkthrough is disabled for this chat. Do NOT ask \
browser-evidence questions and do NOT write to the "Browser Walkthrough Evidence" \
section. Visual evidence will come from images the developer uploads."""


def _client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)


def _doc_tools() -> list[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration(
            name="update_document_section",
            description=(
                "Replace the body of a single section of the Markdown guide. "
                "Use this whenever you have enough information to write or revise a section."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "section_name": types.Schema(
                        type="STRING",
                        description="Exact section heading (e.g. 'Page Overview', 'How To Use This Page').",
                    ),
                    "content": types.Schema(
                        type="STRING",
                        description="The new Markdown body for the section (no heading; just the body).",
                    ),
                },
                required=["section_name", "content"],
            ),
        ),
        types.FunctionDeclaration(
            name="add_red_flag",
            description="Record a gap, uncertainty, or mismatch in the Gaps & Red Flags section.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "expected": types.Schema(type="STRING"),
                    "observed": types.Schema(type="STRING"),
                    "recommended": types.Schema(type="STRING"),
                },
                required=["expected", "observed", "recommended"],
            ),
        ),
        types.FunctionDeclaration(
            name="read_document",
            description="Return the current full document Markdown so you can see your previous edits.",
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
    ]


def _browser_tools() -> list[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration(
            name="browser_open",
            description="Open a headless browser and navigate to a page URL. Starts a new session.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "url": types.Schema(type="STRING", description="The full http(s) URL of the page to open."),
                },
                required=["url"],
            ),
        ),
        types.FunctionDeclaration(
            name="browser_observe",
            description=(
                "Re-snapshot the currently open page WITHOUT taking an action. "
                "Returns the current url, title, observed_labels, and validation_messages. "
                "Use this to re-orient when state is unclear (after a redirect, a modal opening, "
                "or to confirm whether you're already logged in)."
            ),
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
        types.FunctionDeclaration(
            name="browser_click",
            description=(
                "Click an element. `target` can be: visible text of a button/link/tab; "
                "an aria-label; or a CSS selector prefixed with `css=` (e.g. `css=#btnSubmit`). "
                "The backend tries several locator strategies and uses `.first` to tolerate "
                "duplicate or hidden elements."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "target": types.Schema(type="STRING"),
                },
                required=["target"],
            ),
        ),
        types.FunctionDeclaration(
            name="browser_fill",
            description=(
                "Fill a form input. `target` can be: the input's placeholder text "
                "(e.g. `\"example@email.com\"`); its label (`\"Email Address\"`); its "
                "name/id attribute (e.g. `\"txtUserName\"`); or a `css=` selector. The "
                "backend tries multiple strategies in priority order. For credential "
                "fields (passwords, OTP, etc.) you MUST ask the user before calling this."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "target": types.Schema(type="STRING"),
                    "value": types.Schema(type="STRING"),
                },
                required=["target", "value"],
            ),
        ),
        types.FunctionDeclaration(
            name="browser_close_and_save",
            description=(
                "Close the browser session AND write all recorded steps to the "
                "Browser Walkthrough Evidence section of the guide."
            ),
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
    ]


def _tools(browser_enabled: bool) -> list[types.Tool]:
    decls = _doc_tools()
    if browser_enabled:
        decls += _browser_tools()
    return [types.Tool(function_declarations=decls)]


def _system_instruction(chat: ChatMeta, doc: str) -> str:
    sections = "\n".join(f"- {s}" for s in document_editor.section_names_for_prompt(chat.browser_enabled))
    return SYSTEM_PROMPT_TEMPLATE.format(
        section_list=sections,
        name=chat.name,
        browser_state="ENABLED" if chat.browser_enabled else "DISABLED",
        browser_guidance=BROWSER_ON_GUIDANCE if chat.browser_enabled else BROWSER_OFF_GUIDANCE,
        document=doc,
    )


def _assets_root(chat: ChatMeta) -> Path:
    return settings.workspace_path / "documents" / chat.id / chat.current_version / "assets"


def _asset_url_base(chat: ChatMeta) -> str:
    return f"/api/chats/{chat.id}/assets"


async def _exec_tool(
    chat: ChatMeta, name: str, args: dict[str, Any]
) -> tuple[dict[str, Any], bool, dict[str, Any] | None]:
    """Execute a tool call. Returns (response_payload, doc_modified, browser_step_event_or_none)."""
    if name == "update_document_section":
        doc = store.read_guide(chat.id) or ""
        try:
            new_doc = document_editor.replace_section(
                doc, args["section_name"], args["content"]
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}, False, None
        ok = store.write_guide(chat.id, new_doc)
        return ({"ok": ok, "section": args["section_name"]}, ok, None)

    if name == "add_red_flag":
        doc = store.read_guide(chat.id) or ""
        try:
            new_doc = document_editor.append_red_flag(
                doc,
                args.get("expected", ""),
                args.get("observed", ""),
                args.get("recommended", ""),
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}, False, None
        ok = store.write_guide(chat.id, new_doc)
        return ({"ok": ok}, ok, None)

    if name == "read_document":
        doc = store.read_guide(chat.id) or ""
        return ({"document": doc}, False, None)

    if name == "browser_open":
        if not chat.browser_enabled:
            return ({"ok": False, "error": "Browser walkthrough is disabled for this chat."}, False, None)
        try:
            session, step = await browser_service.open_session(
                chat_id=chat.id,
                version=chat.current_version,
                assets_root=_assets_root(chat),
                asset_url_base=_asset_url_base(chat),
                url=args.get("url", ""),
            )
        except Exception as e:
            return ({"ok": False, "error": f"{type(e).__name__}: {e}"}, False, None)
        payload = browser_service.step_event_payload(session, step)
        return (
            {
                "ok": True,
                "url": step.url,
                "title": step.title,
                "observed_labels": step.observed_labels,
                "validation_messages": step.validation_messages,
            },
            False,
            payload,
        )

    if name == "browser_observe":
        if not chat.browser_enabled:
            return ({"ok": False, "error": "Browser walkthrough is disabled for this chat."}, False, None)
        session = browser_service.get_session(chat.id)
        if session is None:
            return ({"ok": False, "error": "No browser session — call browser_open first."}, False, None)
        try:
            step = await browser_service.observe(chat.id)
        except Exception as e:
            return ({"ok": False, "error": f"{type(e).__name__}: {e}"}, False, None)
        payload = browser_service.step_event_payload(session, step)
        return (
            {
                "ok": True,
                "url": step.url,
                "title": step.title,
                "observed_labels": step.observed_labels,
                "validation_messages": step.validation_messages,
            },
            False,
            payload,
        )

    if name in ("browser_click", "browser_fill"):
        if not chat.browser_enabled:
            return ({"ok": False, "error": "Browser walkthrough is disabled for this chat."}, False, None)
        session = browser_service.get_session(chat.id)
        if session is None:
            return ({"ok": False, "error": "No browser session — call browser_open first."}, False, None)
        try:
            if name == "browser_click":
                step, err = await browser_service.click(chat.id, args.get("target", ""))
            else:
                step, err = await browser_service.fill(
                    chat.id, args.get("target", ""), args.get("value", "")
                )
        except Exception as e:
            return ({"ok": False, "error": f"{type(e).__name__}: {e}"}, False, None)
        payload = browser_service.step_event_payload(session, step)
        return (
            {
                "ok": err is None,
                "error": err,
                "url": step.url,
                "title": step.title,
                "observed_labels": step.observed_labels,
                "validation_messages": step.validation_messages,
            },
            False,
            payload,
        )

    if name == "browser_close_and_save":
        if not chat.browser_enabled:
            return ({"ok": False, "error": "Browser walkthrough is disabled."}, False, None)
        session = browser_service.get_session(chat.id)
        if session is None:
            return ({"ok": False, "error": "No browser session to close."}, False, None)
        evidence_md = browser_service.format_evidence(session)
        await browser_service.close_session(chat.id)
        doc = store.read_guide(chat.id) or ""
        try:
            new_doc = document_editor.replace_section(
                doc, "Browser Walkthrough Evidence", evidence_md
            )
        except ValueError as e:
            return ({"ok": False, "error": str(e)}, False, None)
        ok = store.write_guide(chat.id, new_doc)
        return ({"ok": ok, "steps_recorded": len(session.steps)}, ok, None)

    return ({"ok": False, "error": f"Unknown tool: {name}"}, False, None)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def run_turn(
    chat: ChatMeta,
    history: list[types.Content],
    user_message: str,
) -> AsyncIterator[str]:
    """Run one chat turn. Yields SSE event strings. Mutates `history` in place."""
    if not settings.gemini_api_key:
        yield _sse({"type": "error", "message": "GEMINI_API_KEY is not configured."})
        yield _sse({"type": "done"})
        return

    history.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

    client = _client()
    doc = store.read_guide(chat.id) or ""
    config = types.GenerateContentConfig(
        system_instruction=_system_instruction(chat, doc),
        tools=_tools(chat.browser_enabled),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    doc_touched = False
    safety_loops = 0

    try:
        while True:
            safety_loops += 1
            if safety_loops > 10:
                yield _sse({"type": "error", "message": "Tool loop exceeded safety limit."})
                break

            stream = await client.aio.models.generate_content_stream(
                model=settings.gemini_model,
                contents=history,
                config=config,
            )

            collected_parts: list[types.Part] = []
            pending_function_calls: list[tuple[str, dict[str, Any]]] = []

            async for chunk in stream:
                if not chunk.candidates:
                    continue
                candidate = chunk.candidates[0]
                if not candidate.content or not candidate.content.parts:
                    continue
                for part in candidate.content.parts:
                    # Preserve original parts so Gemini 3's thought_signature
                    # rides along with function_calls on the return trip.
                    collected_parts.append(part)
                    if part.text:
                        yield _sse({"type": "text", "text": part.text})
                    elif part.function_call:
                        fc = part.function_call
                        args = dict(fc.args or {})
                        pending_function_calls.append((fc.name, args))
                        yield _sse({"type": "tool_call", "name": fc.name, "args": args})

            if collected_parts:
                history.append(types.Content(role="model", parts=collected_parts))

            if not pending_function_calls:
                break

            tool_response_parts: list[types.Part] = []
            for name, args in pending_function_calls:
                response, modified, browser_payload = await _exec_tool(chat, name, args)
                if modified:
                    doc_touched = True
                if browser_payload is not None:
                    yield _sse({"type": "browser_step", **browser_payload})
                tool_response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(name=name, response=response)
                    )
                )
            history.append(types.Content(role="user", parts=tool_response_parts))

            if doc_touched:
                yield _sse({"type": "doc_updated"})
                doc_touched = False
            # loop again so the model can produce its post-tool reply

    except Exception as e:  # surface to the UI rather than crash the stream
        yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})

    yield _sse({"type": "done"})
