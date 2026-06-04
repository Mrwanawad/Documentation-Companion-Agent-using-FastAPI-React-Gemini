# Documentation Companion Agent

> An AI agent that interviews a developer about **one page** of a SaaS/ERP product and writes a reviewable Markdown user guide for that page — verifying claims against a real browser and turning screenshots into annotated, labelled diagrams along the way.

Built for **Coject**. The whole product runs on **Gemini 3** as its sole LLM — both for the conversational agent (tool calling) and for vision (structured-output image annotation).

---

## What it does

You create a "chat" for a single screen of your app (e.g. *Boards list page*, *Create invoice form*). The agent then:

1. **Interviews you** one focused question at a time, challenging vague answers, and writes the answers straight into a structured Markdown guide — section by section, never the whole file at once.
2. **Drives a real headless Chrome** (optional, per-chat) to verify what you described: it navigates to the page, reads the accessibility tree, inspects forms, console, network and Lighthouse, takes screenshots, and records the walkthrough as evidence. When it hits a login or OTP screen it **stops and asks you** rather than guessing credentials.
3. **Annotates screenshots** you upload: Gemini 3 vision detects every interactive element with bounding boxes, Pillow draws numbered boxes onto the image, and a "what each control does" table is appended to the guide.
4. **Flags gaps** — anything skipped, unknown, or where the observed behaviour didn't match what you said goes into a *Gaps & Red Flags* section.

The result is a help-article-style guide a product owner could read to learn that one page, plus an audit trail of how every claim was verified.

---

## Architecture at a glance

```
┌─────────────────────────┐         ┌──────────────────────────────────────────┐
│  Frontend (React + Vite)│  /api   │  Backend (FastAPI)                         │
│                         │ ──────► │                                            │
│  • Sidebar (chats)      │  proxy  │  api/chats     chat + document CRUD        │
│  • ChatPanel (SSE)      │ ◄────── │  api/messages  SSE chat turn (agent loop)  │
│  • CanvasPanel (md)     │  SSE    │  api/uploads   image annotation + assets   │
└─────────────────────────┘         │                                            │
                                     │  services/agent          Gemini 3 + tools │
                                     │  services/browser ─┐                       │
                                     │  services/cdp_mcp ─┴─► chrome-devtools-mcp │
                                     │  services/annotator      Gemini vision     │
                                     │  services/document_editor section editor   │
                                     │  store.py  ──► workspace/ (files on disk)  │
                                     └────────────────────────────────────────────┘
                                                       │
                                              ┌────────┴─────────┐
                                              │ Gemini 3 API     │
                                              │ chrome-devtools  │ (npx subprocess)
                                              └──────────────────┘
```

- **No database.** State lives as plain files under [workspace/](workspace/).
- **Chat history is ephemeral** — kept in memory and wiped on server restart (documents persist; conversations don't). See [messages.py](backend/app/api/messages.py).
- **Each chat gets its own Chrome profile** (`--user-data-dir`), so logins persist across turns and chats stay isolated.

---

## Tech stack

| Layer | Choice |
|-------|--------|
| Frontend | React 18, TypeScript, Vite 6, `react-markdown` + `remark-gfm` |
| Backend | FastAPI, Uvicorn, Pydantic v2 / pydantic-settings |
| LLM | **Gemini 3** via `google-genai` (`gemini-3-flash-preview` by default) — chat tool-calling **and** vision structured output |
| Browser automation | `chrome-devtools-mcp` driven over the Model Context Protocol (`mcp` Python client, spawned via `npx`) |
| Image annotation | Pillow (box drawing) + Gemini 3 vision (element detection) |
| Storage | File system (`workspace/`) — no DB |

---

## How a chat turn works

The agent loop lives in [agent.py](backend/app/services/agent.py) (`run_turn`):

1. The user message is appended to the in-memory history for that chat.
2. A system prompt is assembled from the **current document snapshot**, the list of writable sections, and browser guidance (on/off depending on the chat toggle).
3. Gemini 3 is streamed. Each chunk is forwarded to the UI as an SSE event:
   - `text` — assistant prose
   - `tool_call` — a function the model wants to run
   - `browser_step` — a recorded browser action + screenshot
   - `doc_updated` — the guide changed; the canvas should refetch
   - `error` / `done`
4. Any function calls are executed by `_exec_tool`, their results appended to history, and the loop repeats so the model can react. Gemini's parallel function calling is supported — several tool calls per iteration count as one of the **25-iteration** safety budget.
5. Gemini 3 `thought_signature`s are preserved on the round trip by re-sending the original parts.

### Tools the agent can call

**Document tools** (always available):

| Tool | Purpose |
|------|---------|
| `update_document_section` | Replace the body of one `## Section` |
| `add_red_flag` | Append an expected/observed/recommended entry to *Gaps & Red Flags* |
| `read_document` | Return the current full guide |

**Browser tools** (only when *Browser walkthrough* is enabled for the chat):

| Tool | Purpose |
|------|---------|
| `browser_open(url)` | Start a session and navigate (http/https only) |
| `browser_observe()` | Re-snapshot the page without acting |
| `browser_describe_form()` | Structured dump of every form field (label, type, required, validation, options) |
| `browser_click(target)` / `browser_fill(target, value)` | Act by visible label, placeholder, name/id, or `css=` selector |
| `browser_console_messages()` | Console logs/warnings/errors |
| `browser_network_requests()` / `browser_network_request_detail(url)` | XHR/fetch/asset traffic |
| `browser_evaluate(function)` | Run an arbitrary JS arrow-function in the page |
| `browser_lighthouse_audit(categories?)` | Lighthouse report |
| `browser_close_and_save()` | Close the session and write all steps into *Browser Walkthrough Evidence* |

Text targets (`"Sign In"`, `"Email Address"`, `"example@email.com"`) are resolved against the chrome-devtools-mcp accessibility snapshot in [browser.py](backend/app/services/browser.py); password/OTP/token fields are redacted in recorded evidence, and the system prompt enforces a **stop-and-ask credentials policy**.

---

## The guide document

Every chat owns one Markdown guide built from a fixed template ([store.py](backend/app/store.py)) with these `##` sections, edited individually by [document_editor.py](backend/app/services/document_editor.py):

`Document Status` · `Version History` · `Page Overview` · `Where To Find This Page` · `Who Can Access` · `Page Layout` · `How To Use This Page` · `Form Fields & Validations` · `Tips & Shortcuts` · `Browser Walkthrough Evidence` · `Screenshots And Assets` · `Limitations & Known Issues` · `Gaps & Red Flags` · `FAQ` · `Approval`

(When browser walkthrough is off, *Browser Walkthrough Evidence* is dropped from what the agent may write.)

### Status lifecycle

`draft → complete → in_review → approved → superseded → archived`

Once a chat is **approved** the document and chat become read-only — both `PUT /document` and agent edits are rejected (see [chats.py](backend/app/api/chats.py)).

---

## Workspace layout

All runtime state is files under [workspace/](workspace/) (git-ignored):

```
workspace/
├── chats/<chat_id>/
│   ├── meta.json                 # ChatMeta (name, status, browser_enabled, …)
│   └── browser-profile/          # per-chat Chrome user-data-dir (auth persistence)
└── documents/<chat_id>/v1.0/
    ├── guide.md                  # the Markdown guide
    ├── metadata.json             # document metadata
    └── assets/
        ├── uploaded/             # original uploaded screenshots
        └── annotated/            # annotated screenshots + browser walkthrough captures
```

---

## HTTP API

Base URL `http://localhost:8000`. Defined in [backend/app/api/](backend/app/api/).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Liveness + resolved workspace path |
| `GET` | `/api/chats` | List chats (newest first) |
| `POST` | `/api/chats` | Create a chat (`{name, browser_enabled}`) |
| `GET` | `/api/chats/{id}` | Get chat metadata |
| `PATCH` | `/api/chats/{id}` | Update name / browser toggle / status |
| `DELETE` | `/api/chats/{id}` | Delete chat + document + assets + Chrome profile |
| `GET` | `/api/chats/{id}/document` | Read the guide Markdown |
| `PUT` | `/api/chats/{id}/document` | Overwrite the guide (blocked if approved) |
| `POST` | `/api/chats/{id}/messages` | **SSE** — run one agent turn |
| `DELETE` | `/api/chats/{id}/messages` | Clear in-memory chat history |
| `POST` | `/api/chats/{id}/uploads` | Upload an image → annotate → append to guide |
| `GET` | `/api/chats/{id}/assets/{kind}/{filename}` | Serve an `uploaded`/`annotated` asset |

Interactive API docs are available at `http://localhost:8000/docs` while the backend runs.

---

## Configuration

Backend settings come from `backend/.env` (see [.env.example](backend/.env.example)) via [config.py](backend/app/config.py):

| Variable | Default | Purpose |
|----------|---------|---------|
| `GEMINI_API_KEY` | *(empty)* | **Required.** Google Gemini API key |
| `GEMINI_MODEL` | `gemini-3-flash-preview` | Model used for chat **and** vision |
| `WORKSPACE_DIR` | `../workspace` | Where chats/documents/assets are stored (relative to the backend working dir) |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |

The frontend talks to the backend through Vite's dev proxy (`/api → http://localhost:8000`, see [vite.config.ts](frontend/vite.config.ts)), so no frontend env vars are needed in development.

---

## Getting started

See **[SETUP.md](SETUP.md)** for the full setup-and-run guide. The short version:

```bash
# 1. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then put your GEMINI_API_KEY in .env
uvicorn app.main:app --reload --port 8000

# 2. Frontend (in a second terminal)
cd frontend
npm install
npm run dev                   # open http://localhost:5173
```

---

## Security & operational notes

- **Asset serving is path-traversal hardened** — only plain filenames under the chat's `uploaded`/`annotated` dirs are served ([uploads.py](backend/app/api/uploads.py)).
- **Credentials policy** — the agent is instructed to stop and ask before filling any password/OTP/token, never to reuse credentials, and to respect "skip login". Secret values are masked in recorded evidence.
- **The app itself has no authentication** — it's built to run locally for an internal R&D workflow. Don't expose it to the public internet as-is.
- **Browser walkthrough needs `npx` + Chrome.** The first `browser_open` downloads `chrome-devtools-mcp@latest` via `npx`, so the first run needs network access.
- **Upload limits:** 20 MB per image, 100 images per document.
- **No automated test suite** ships with the project today.

---

## Project structure

```
documentation companion/
├── README.md                      # this file
├── SETUP.md                       # setup & run guide
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   └── app/
│       ├── main.py                # FastAPI app, CORS, routers, shutdown hook
│       ├── config.py              # settings (.env)
│       ├── models.py              # Pydantic models, ChatStatus
│       ├── store.py               # file-backed chat/document store + guide template
│       ├── api/                   # chats, messages (SSE), uploads
│       └── services/
│           ├── agent.py           # Gemini 3 agent loop + tool definitions
│           ├── browser.py         # walkthrough service (targets → MCP uids, evidence)
│           ├── cdp_mcp.py         # per-chat chrome-devtools-mcp subprocess manager
│           ├── annotator.py       # Gemini vision + Pillow box drawing
│           └── document_editor.py # section-level Markdown editing
└── frontend/
    ├── package.json, vite.config.ts
    └── src/
        ├── App.tsx                # layout + chat selection
        ├── api/client.ts          # fetch + SSE stream parser
        ├── types.ts
        └── components/            # Sidebar, ChatPanel, CanvasPanel, NewChatDialog, StatusBadge
```

For reference, the original product brief and plan are checked in as
`documentation-companion-agent-v1.00-prd.pdf` and `documentation-companion-agent-v1.00-plan.pdf`.
