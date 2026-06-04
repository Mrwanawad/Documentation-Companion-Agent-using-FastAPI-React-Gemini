# Setup & Run Guide

How to get the **Documentation Companion Agent** running locally. For what the app *is* and how it works, see [README.md](README.md).

The app has two processes you run side by side:

- **Backend** — FastAPI on `http://localhost:8000`
- **Frontend** — Vite dev server on `http://localhost:5173` (proxies `/api` to the backend)

---

## 1. Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Python** | 3.11+ (repo uses 3.13) | For the FastAPI backend |
| **Node.js** | 18+ (20+ recommended) | For the Vite frontend **and** for `npx chrome-devtools-mcp` |
| **npm / npx** | bundled with Node | `npx` launches the browser-automation server |
| **Google Chrome** | recent stable | Driven headlessly by `chrome-devtools-mcp` (only needed if you use the browser walkthrough) |
| **Gemini API key** | — | Get one from [Google AI Studio](https://aistudio.google.com/apikey) |

Check what you have:

```bash
python3 --version
node --version
npx --version
```

### Installing Python

The backend needs **Python 3.11 or newer** (the repo is developed on 3.13). If `python3 --version` is missing or below 3.11, install it:

**macOS**

```bash
# Homebrew (recommended)
brew install python@3.13

# …or download the official installer from https://www.python.org/downloads/macos/
```

**Windows**

```powershell
# winget (Windows 10/11)
winget install Python.Python.3.13

# …or download the installer from https://www.python.org/downloads/windows/
# In the installer, tick "Add python.exe to PATH" before clicking Install.
```

On Windows, use `python` and `py` instead of `python3` (e.g. `py --version`, `py -m venv .venv`).

**Linux (Debian/Ubuntu)**

```bash
sudo apt update
sudo apt install python3.13 python3.13-venv python3-pip
# If 3.13 isn't in your distro's repos, add the deadsnakes PPA first:
#   sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update
```

**Linux (Fedora)**

```bash
sudo dnf install python3.13
```

After installing, confirm the version is 3.11+:

```bash
python3 --version    # Windows: py --version
```

> **Why 3.11+?** The backend's dependencies (FastAPI, Pydantic v2, and the Gemini SDK) require a modern Python. Versions below 3.11 will fail to install or run.

---

## 2. Backend

```bash
cd backend

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create your .env from the template
cp .env.example .env
```

Open `backend/.env` and set your key (the other values can stay as-is):

```dotenv
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-3-flash-preview
WORKSPACE_DIR=../workspace
CORS_ORIGINS=http://localhost:5173
```

Run the API (keep this terminal open):

```bash
uvicorn app.main:app --reload --port 8000
```

> **Working directory matters.** `WORKSPACE_DIR=../workspace` is resolved relative to where you launch uvicorn. Run it from inside `backend/` so the workspace lands at the repo root (`workspace/`), which is what the frontend and `.gitignore` expect.

**Verify it's up:**

```bash
curl http://localhost:8000/api/health
# {"status":"ok","workspace":"/…/documentation companion/workspace"}
```

Interactive API docs: <http://localhost:8000/docs>

---

## 3. Frontend

In a **second terminal**:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The dev server proxies every `/api/*` request to the backend on port 8000 (see [vite.config.ts](frontend/vite.config.ts)), so you don't configure any URLs.

---

## 4. First run — try it out

1. Click **+ New** in the sidebar.
2. Name the page (e.g. *Login page* or *Create invoice form*) and choose whether to enable **Browser walkthrough**.
3. Describe the page in the chat. The agent interviews you and writes the guide on the right; click **Preview/Edit** in the canvas to read or hand-edit the Markdown.
4. **Attach a screenshot** (📎) to get an annotated diagram with a numbered element table appended to *Screenshots And Assets*.
5. If browser walkthrough is on, give the agent the page URL — it will open Chrome, capture evidence, and **ask you before entering any credentials**.

> **First browser walkthrough is slow.** The first `browser_open` runs `npx -y chrome-devtools-mcp@latest`, which downloads the MCP server (and Chrome, if needed). This needs internet access and can take a minute; later runs are fast.

---

## 5. Production build (optional)

Build the static frontend:

```bash
cd frontend
npm run build        # outputs frontend/dist/
npm run preview      # optional: preview the build locally
```

Run the backend without auto-reload:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

If you serve `frontend/dist/` from a different origin than the API, add that origin to `CORS_ORIGINS` in `backend/.env` (comma-separated). The app ships with **no authentication**, so don't expose it directly to the public internet.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Chat replies `GEMINI_API_KEY is not configured.` | `GEMINI_API_KEY` missing in `backend/.env`, or the backend was started before `.env` existed — set it and restart uvicorn. |
| Frontend loads but every action fails / network errors | Backend isn't running on port 8000, or you started the frontend without the backend. Start both. |
| `browser_open` errors or hangs the first time | `npx`/Chrome not installed, or no internet for the first `chrome-devtools-mcp` download. Verify `npx --version` and that Chrome is installed. |
| Annotation upload returns `502 Annotation failed` | Gemini vision call failed — usually a bad/over-quota API key or an unsupported image. Check the backend logs. |
| `workspace/` appears in the wrong place | You launched uvicorn from outside `backend/`. Stop it, `cd backend`, and rerun. |
| `413` on upload | Image exceeds the 20 MB cap (or the document already has 100 images). |
| Editing the document does nothing / Save disabled | The chat is **approved** and therefore read-only. Change its status first. |

### Resetting state

All runtime data is files. To wipe everything and start clean:

```bash
rm -rf workspace/        # deletes all chats, documents, assets, and Chrome profiles
```

Chat *history* (the conversation) is in-memory only and clears on every backend restart by design — the persisted guides are unaffected.
