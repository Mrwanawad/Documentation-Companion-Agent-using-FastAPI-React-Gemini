"""Speech-to-text via Gemini.

The composer records microphone audio in the browser and posts it here; Gemini
transcribes it. This keeps voice input reliable across browsers (the Web Speech
API is Chrome-only and frequently fails with a `network` error) and on-brand —
Gemini is the app's sole model, and it auto-detects the spoken language
(English or Arabic) without us having to choose.
"""

from __future__ import annotations

from google import genai
from google.genai import types

from ..config import settings


TRANSCRIBE_PROMPT = (
    "Transcribe the speech in this audio recording verbatim. "
    "Automatically detect the spoken language (it may be English or Arabic) and "
    "transcribe in that language. Return ONLY the transcribed text — no quotes, "
    "no commentary, no timestamps, no speaker labels. If there is no intelligible "
    "speech, return an empty string."
)


def transcribe(audio: bytes, mime_type: str) -> str:
    """Return the transcript of an audio clip, or '' if no speech was detected."""
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=audio, mime_type=mime_type or "audio/wav"),
                    types.Part(text=TRANSCRIBE_PROMPT),
                ],
            )
        ],
    )
    return (response.text or "").strip()
