"""Documentation Companion agent — wraps Gemini 3 with tool calling and SSE streaming."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from .. import store
from ..config import settings
from ..models import ChatMeta
from . import annotator
from . import browser as browser_service
from . import document_editor


@dataclass
class Attachment:
    """A file the user attached to a chat message (read fully into memory)."""

    filename: str
    mime: str
    data: bytes

    @property
    def is_image(self) -> bool:
        return self.mime.startswith("image/")

    @property
    def is_pdf(self) -> bool:
        return self.mime == "application/pdf"


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
- `browser_describe_form()` — return a structured snapshot of every form field on \
the current page (id, name, label, placeholder, type, required, validation rules, \
current value, select options). Call this once to populate the "Form Fields & \
Validations" section in one shot, instead of asking about each field.

## Inspection tools (powered by Chrome DevTools)
These give you DevTools-level visibility into the page beyond what a user can see:

- `browser_console_messages()` — every console log/warning/error since navigation. \
Use to flag JS errors as Limitations or Red Flags.
- `browser_network_requests(page_size?)` — list of XHR/fetch/asset requests with \
method, URL, status. Use to document which endpoints back which sections, and to \
red-flag 4xx/5xx.
- `browser_network_request_detail(url)` — headers + body for a specific request.
- `browser_evaluate(function)` — run any JS arrow-function in the page \
(`"() => document.querySelectorAll('h2').length"`).
- `browser_lighthouse_audit(categories?)` — full Lighthouse audit. Use sparingly — \
the report is large; categories=['accessibility'] etc. to narrow.
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

## BATCH YOUR TOOL CALLS
You have a tool-loop budget per turn. Each iteration of the loop costs one \
budget unit, regardless of how many tool calls you make in that iteration. \
Make MULTIPLE tool calls in one iteration whenever they're independent — \
Gemini supports parallel function calling and our backend handles them. \
Specifically:

- Fill all login fields AND click submit in ONE turn (one iteration with \
multiple function calls), not one fill per turn.
- Do NOT call `browser_observe` immediately after `browser_open` — the open \
response already contains the same snapshot. Only call `browser_observe` when \
you suspect the page changed (e.g. after a redirect you didn't initiate).
- Do NOT call `browser_describe_form` until you actually need to write the \
Form Fields & Validations section — typically AFTER you're past login.

## TARGETS — USE VISIBLE LABELS, NOT RAW IDS
`browser_click(target)` and `browser_fill(target, value)` resolve `target` \
against the a11y snapshot returned by chrome-devtools-mcp. That snapshot uses \
the user-visible label/placeholder/aria-name — NOT the raw HTML `id` or `name` \
attribute. So:

✅ `browser_fill("Email Address", "...")`              — uses the label
✅ `browser_fill("example@email.com", "...")`          — uses the placeholder
✅ `browser_click("Continue")` / `browser_click("Sign In")` — visible button text
❌ `browser_fill("txtUserName", "...")`                — raw id, will NOT match
❌ `browser_fill("Input.Email", "...")`                — raw form name, will NOT match
❌ `browser_click("Login")` when the button actually says "Sign In" or "Continue"

If you don't know what label is on the page, look at `observed_labels` from the \
last tool response — that lists what's actually clickable/fillable.

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
            name="browser_describe_form",
            description=(
                "Return a structured snapshot of every visible form field on the current "
                "page: tag, type, id, name, label, placeholder, required, validation rules, "
                "current value, and select options. Use this once to gather everything you "
                "need to write the 'Form Fields & Validations' section in one shot — "
                "instead of asking the developer about each field."
            ),
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
        types.FunctionDeclaration(
            name="browser_console_messages",
            description=(
                "Return all console messages (logs, warnings, errors) the page has emitted "
                "since the last navigation. Use this to surface frontend errors in the guide's "
                "'Limitations & Known Issues' section, or to flag a red flag when the developer "
                "described smooth behavior but the page is throwing errors."
            ),
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
        types.FunctionDeclaration(
            name="browser_network_requests",
            description=(
                "Return the list of network requests the page has made (URL, method, status, "
                "size). Use this when documenting how the page loads data (which endpoints "
                "back which sections), or to flag failed/4xx/5xx requests."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "page_size": types.Schema(
                        type="INTEGER",
                        description="Max number of requests to return (default 30, max 100).",
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="browser_network_request_detail",
            description="Return full headers/body for a specific network request, looked up by URL.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "url": types.Schema(type="STRING"),
                },
                required=["url"],
            ),
        ),
        types.FunctionDeclaration(
            name="browser_evaluate",
            description=(
                "Run an arbitrary JavaScript function in the page and return the result. "
                "The 'function' argument must be a JS arrow-function source string, "
                "e.g. \"() => document.title\" or \"() => Array.from(document.querySelectorAll('h2')).map(h => h.innerText)\". "
                "Use this for one-off page introspection that the other tools don't cover."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "function": types.Schema(type="STRING"),
                },
                required=["function"],
            ),
        ),
        types.FunctionDeclaration(
            name="browser_lighthouse_audit",
            description=(
                "Run Chrome Lighthouse on the current page and return the report. "
                "Use this to flag performance / accessibility / best-practices issues that "
                "should go in 'Limitations & Known Issues' or as red flags."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "categories": types.Schema(
                        type="ARRAY",
                        items=types.Schema(type="STRING"),
                        description="Subset of 'performance','accessibility','best-practices','seo','pwa'. Empty/omitted = all.",
                    ),
                },
            ),
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


def _browser_config_block(chat: ChatMeta) -> str:
    """Saved walkthrough config injected into the prompt when present."""
    url = (chat.browser_url or "").strip()
    email = (chat.browser_email or "").strip()
    password = (chat.browser_password or "").strip()
    notes = (chat.browser_notes or "").strip()
    if not any([url, email, password, notes]):
        return ""
    lines = ["\n## Saved walkthrough config (provided by the developer)"]
    if url:
        lines.append(f"- Start URL: {url} — open this when asked to browse or when the developer uses /browse.")
    if email:
        lines.append(f"- Login email/username: {email}")
    if password:
        lines.append(f"- Login password: {password}")
    if notes:
        lines.append(f"- Notes: {notes}")
    if email or password:
        lines.append(
            "These credentials were supplied by the developer for THIS walkthrough. You MAY "
            "use them to log in WITHOUT asking first. Only stop and ask if a needed credential "
            "is missing above or the provided ones are rejected."
        )
    return "\n".join(lines)


def _system_instruction(chat: ChatMeta, doc: str, browser_on: bool) -> str:
    sections = "\n".join(f"- {s}" for s in document_editor.section_names_for_prompt(browser_on))
    guidance = (BROWSER_ON_GUIDANCE + _browser_config_block(chat)) if browser_on else BROWSER_OFF_GUIDANCE
    return SYSTEM_PROMPT_TEMPLATE.format(
        section_list=sections,
        name=chat.name,
        browser_state="ENABLED" if browser_on else "DISABLED",
        browser_guidance=guidance,
        document=doc,
    )


def _assets_root(chat: ChatMeta) -> Path:
    return settings.workspace_path / "documents" / chat.id / chat.current_version / "assets"


def _asset_url_base(chat: ChatMeta) -> str:
    return f"/api/chats/{chat.id}/assets"


async def _exec_tool(
    chat: ChatMeta, name: str, args: dict[str, Any], browser_on: bool
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
        if not browser_on:
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
        if not browser_on:
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

    if name == "browser_describe_form":
        if not browser_on:
            return ({"ok": False, "error": "Browser walkthrough is disabled for this chat."}, False, None)
        if browser_service.get_session(chat.id) is None:
            return ({"ok": False, "error": "No browser session — call browser_open first."}, False, None)
        try:
            fields = await browser_service.describe_form(chat.id)
        except Exception as e:
            return ({"ok": False, "error": f"{type(e).__name__}: {e}"}, False, None)
        return ({"ok": True, "fields": fields, "field_count": len(fields)}, False, None)

    if name in ("browser_console_messages", "browser_network_requests",
                "browser_network_request_detail", "browser_evaluate",
                "browser_lighthouse_audit"):
        if not browser_on:
            return ({"ok": False, "error": "Browser walkthrough is disabled for this chat."}, False, None)
        if browser_service.get_session(chat.id) is None:
            return ({"ok": False, "error": "No browser session — call browser_open first."}, False, None)
        try:
            if name == "browser_console_messages":
                text = await browser_service.console_messages(chat.id)
            elif name == "browser_network_requests":
                text = await browser_service.network_requests(chat.id, int(args.get("page_size", 30)))
            elif name == "browser_network_request_detail":
                text = await browser_service.network_request_detail(chat.id, str(args.get("url", "")))
            elif name == "browser_evaluate":
                text = await browser_service.evaluate(chat.id, str(args.get("function", "")))
            else:  # browser_lighthouse_audit
                cats = args.get("categories")
                text = await browser_service.lighthouse_audit(chat.id, list(cats) if cats else None)
        except Exception as e:
            return ({"ok": False, "error": f"{type(e).__name__}: {e}"}, False, None)
        return ({"ok": True, "output": text}, False, None)

    if name in ("browser_click", "browser_fill"):
        if not browser_on:
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
        if not browser_on:
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


def _safe_asset_name(original: str, default_suffix: str) -> str:
    suffix = Path(original).suffix.lower() or default_suffix
    return f"{uuid.uuid4().hex[:10]}{suffix}"


async def run_turn(
    chat: ChatMeta,
    history: list[types.Content],
    user_message: str,
    attachments: list[Attachment] | None = None,
    force_browse: bool = False,
) -> AsyncIterator[str]:
    """Run one chat turn. Yields SSE event strings. Mutates `history` in place."""
    if not settings.gemini_api_key:
        yield _sse({"type": "error", "message": "GEMINI_API_KEY is not configured."})
        yield _sse({"type": "done"})
        return

    attachments = attachments or []
    # `/browse` (force_browse) turns the browser on for this turn even if the
    # chat's persistent toggle is off.
    browser_on = chat.browser_enabled or force_browse
    base_url = annotator.asset_url_base_for(chat.id)

    # --- Phase 0: process attachments before the model turn ---------------
    # Images are annotated + appended to the doc; PDFs are saved + linked. Both
    # are turned into Gemini Parts so the model sees them this turn. Events are
    # streamed as each file finishes. `file_parts` carry the bytes for this turn
    # only; after the loop they're collapsed to text refs (`collapsed_refs`).
    file_parts: list[types.Part] = []
    notes: list[str] = []
    collapsed_refs: list[str] = []

    for att in attachments:
        if att.is_image:
            try:
                result = annotator.annotate_and_append(
                    chat.id, chat.current_version, att.data, att.filename, att.mime
                )
            except Exception as e:
                notes.append(f"Attached image '{att.filename}' could not be annotated ({e}).")
                file_parts.append(types.Part.from_bytes(data=att.data, mime_type=att.mime))
                collapsed_refs.append(f"screenshot '{att.filename}' (annotation failed)")
                yield _sse({"type": "attachment", "kind": "image", "name": att.filename, "error": str(e)})
                continue
            elements_payload = [
                {
                    "index": i + 1,
                    "label": el.label,
                    "element_type": el.element_type,
                    "inferred_action": el.inferred_action,
                    "is_repeated_group": el.is_repeated_group,
                    "instance_count": el.instance_count,
                }
                for i, el in enumerate(result.elements)
            ]
            yield _sse({
                "type": "attachment",
                "kind": "image",
                "name": att.filename,
                "annotated_url": f"{base_url}/annotated/{result.annotated_filename}",
                "original_url": f"{base_url}/uploaded/{result.original_filename}",
                "page_summary": result.page_summary,
                "elements": elements_payload[:12],
                "element_count": len(result.elements),
            })
            yield _sse({"type": "doc_updated"})
            file_parts.append(types.Part.from_bytes(data=att.data, mime_type=att.mime))
            notes.append(
                f"User attached screenshot '{att.filename}'. Detected: {result.page_summary} "
                f"The annotated screenshot and its interactive-element table have already been "
                f"written to the 'Screenshots And Assets' section of the document."
            )
            collapsed_refs.append(f"screenshot '{att.filename}' (annotated in document)")

        elif att.is_pdf:
            files_dir = annotator.assets_root_for(chat.id, chat.current_version) / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            saved = _safe_asset_name(att.filename, ".pdf")
            (files_dir / saved).write_bytes(att.data)
            file_url = f"{base_url}/files/{saved}"
            doc = store.read_guide(chat.id) or ""
            try:
                new_doc = document_editor.link_attachment(doc, att.filename, file_url)
                store.write_guide(chat.id, new_doc)
            except Exception:
                pass
            yield _sse({"type": "attachment", "kind": "pdf", "name": att.filename, "file_url": file_url})
            yield _sse({"type": "doc_updated"})
            file_parts.append(types.Part.from_bytes(data=att.data, mime_type="application/pdf"))
            notes.append(
                f"User attached PDF '{att.filename}' (linked in the document's "
                f"'Attachments & References' section). Use it as reference when documenting this page."
            )
            collapsed_refs.append(f"PDF '{att.filename}' (linked in document)")
        else:
            notes.append(f"Attached file '{att.filename}' has an unsupported type and was ignored.")

    # --- Build the multimodal user turn -----------------------------------
    combined_text = user_message.strip()
    if not combined_text:
        combined_text = f"[Attached {len(attachments)} file(s)]" if attachments else ""
    if notes:
        combined_text = (combined_text + "\n\n" + "\n".join(notes)).strip()
    user_content = types.Content(
        role="user", parts=[types.Part(text=combined_text)] + file_parts
    )
    history.append(user_content)

    client = _client()
    doc = store.read_guide(chat.id) or ""  # read AFTER attachment writes so the prompt sees them
    config = types.GenerateContentConfig(
        system_instruction=_system_instruction(chat, doc, browser_on),
        tools=_tools(browser_on),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    doc_touched = False
    safety_loops = 0

    try:
        while True:
            safety_loops += 1
            if safety_loops > 25:
                yield _sse({"type": "error", "message": "Tool loop exceeded safety limit (25 iterations)."})
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
                response, modified, browser_payload = await _exec_tool(chat, name, args, browser_on)
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

    # Collapse this turn's binary file parts to text refs so later turns don't
    # re-send megabytes of image/PDF bytes (request-size + token safety). The
    # model already saw the bytes during this turn.
    if file_parts:
        collapsed = combined_text
        if collapsed_refs:
            collapsed = (combined_text + "\n\n[Attachments this turn: " + "; ".join(collapsed_refs) + "]").strip()
        user_content.parts = [types.Part(text=collapsed or "[attachments]")]

    yield _sse({"type": "done"})
