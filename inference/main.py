"""
Guava inference service.

A small FastAPI app that wraps the self-hosted voice models. Runs locally for
development and deploys to a free Hugging Face Space (CPU) for the live demo.

Endpoints (added per feature):
  POST /stt    audio -> text (+ SRT, VTT)   [live]
  POST /tts    text  -> audio (WAV)         [live]
  POST /clone  sample + text -> audio        [planned]
"""
from __future__ import annotations

import os
import tempfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(
    title="Guava Inference",
    version="0.1.0",
    description="Self-hosted voice models for Guava (STT, TTS, voice cloning).",
)

# The Next.js app calls this from the browser, so allow cross-origin requests.
# Tighten the origins list once the deployed web URL is known.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Health(BaseModel):
    status: str
    service: str
    version: str
    features: dict[str, bool]


@app.get("/")
def health() -> Health:
    return Health(
        status="ok",
        service="guava-inference",
        version="0.1.0",
        features={"stt": True, "tts": True, "clone": False},
    )


class Segment(BaseModel):
    start: float
    end: float
    text: str


class SttResponse(BaseModel):
    text: str
    segments: list[Segment]
    srt: str
    vtt: str
    language: str
    durationSec: float


# Reject oversized uploads early (free CPU can't handle long files well anyway).
MAX_UPLOAD_BYTES = int(os.getenv("GUAVA_MAX_UPLOAD_MB", "25")) * 1024 * 1024


@app.post("/stt")
async def stt(
    audio: UploadFile = File(...),
    language: str | None = Form(default=None),
    task: str = Form(default="transcribe"),
) -> SttResponse:
    """Transcribe an uploaded audio file. The model is imported lazily so the
    service boots fast and only pays the load cost on the first transcription.

    task: "transcribe" (keep spoken language) or "translate" (output English)."""
    if task not in ("transcribe", "translate"):
        raise HTTPException(status_code=400, detail="task must be transcribe or translate.")

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB on the free tier.",
        )

    suffix = os.path.splitext(audio.filename or "")[1] or ".bin"
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        from models.stt import transcribe  # lazy import (loads faster-whisper)

        result = transcribe(tmp_path, language=language, task=task)
        return SttResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:  # surface a clean error to the client
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# A friendly subset of the 99+ languages Whisper supports, for the UI dropdown.
# code -> display name. "auto" lets Whisper detect the language itself.
SUPPORTED_LANGUAGES = {
    "auto": "Auto-detect",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "hi": "Hindi",
    "ar": "Arabic",
    "tr": "Turkish",
    "pl": "Polish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "te": "Telugu",
    "ta": "Tamil",
}


@app.get("/languages")
def languages() -> dict:
    """Languages the UI offers. Whisper transcribes all of them and can also
    translate any of them *to English* (the translate task)."""
    return {"languages": SUPPORTED_LANGUAGES}


# --------------------------------------------------------------------------
# Text to Speech (Kokoro)
# --------------------------------------------------------------------------

MAX_TTS_CHARS = int(os.getenv("GUAVA_MAX_TTS_CHARS", "2000"))


class TtsRequest(BaseModel):
    text: str
    voice: str = "af_heart"
    speed: float = 1.0


@app.get("/voices")
def voices() -> dict:
    """Voices available for text-to-speech."""
    from models.tts import VOICES

    return {"voices": VOICES}


@app.post("/tts")
def tts(req: TtsRequest) -> Response:
    """Render text to speech and return a WAV file. The model is imported lazily
    so the service boots fast and only loads Kokoro on the first request."""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is empty.")
    if len(text) > MAX_TTS_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text too long. Max {MAX_TTS_CHARS} characters.",
        )
    if not 0.5 <= req.speed <= 2.0:
        raise HTTPException(status_code=400, detail="Speed must be between 0.5 and 2.0.")

    try:
        from models.tts import synthesize  # lazy import (loads Kokoro)

        wav = synthesize(text, voice=req.voice, speed=req.speed)
        return Response(content=wav, media_type="audio/wav")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {exc}")
