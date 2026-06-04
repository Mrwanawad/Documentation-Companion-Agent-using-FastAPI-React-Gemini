from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import audio, chats, messages, uploads
from .config import settings
from .services import browser as browser_service


app = FastAPI(title="Documentation Companion Agent", version="0.1.0")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await browser_service.shutdown_browsers()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chats.router)
app.include_router(messages.router)
app.include_router(uploads.router)
app.include_router(audio.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "workspace": str(settings.workspace_path)}
