"""POST /api/transcribe — transcribe a short audio clip with Gemini.

Used by the composer's microphone button. Browser-recorded WAV audio is posted
here and Gemini returns the transcript, which the UI drops into the message box.
"""

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..services import transcriber


router = APIRouter(prefix="/api", tags=["audio"])


MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB — plenty for a spoken message


class TranscriptResponse(BaseModel):
    text: str


@router.post("/transcribe", response_model=TranscriptResponse)
async def transcribe_audio(file: UploadFile = File(...)) -> TranscriptResponse:
    content_type = (file.content_type or "").lower()
    if not (content_type.startswith("audio/") or content_type.startswith("video/")):
        raise HTTPException(status_code=415, detail="Upload must be an audio recording")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio recording")
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio exceeds the {MAX_AUDIO_BYTES // (1024 * 1024)} MB limit.",
        )

    try:
        text = transcriber.transcribe(raw, content_type or "audio/wav")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {e}")

    return TranscriptResponse(text=text)
