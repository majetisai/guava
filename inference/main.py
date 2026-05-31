"""
Guava inference service.

A small FastAPI app that wraps the self-hosted voice models. Runs locally for
development and deploys to a free Hugging Face Space (CPU) for the live demo.

Endpoints (added per feature):
  POST /stt    audio -> text (+ SRT, VTT)   [live]
  POST /tts    text  -> audio               [planned]
  POST /clone  sample + text -> audio        [planned]
"""
from __future__ import annotations

import os
import tempfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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
        features={"stt": True, "tts": False, "clone": False},
    )


class SttResponse(BaseModel):
    text: str
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
) -> SttResponse:
    """Transcribe an uploaded audio file. The model is imported lazily so the
    service boots fast and only pays the load cost on the first transcription."""
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

        result = transcribe(tmp_path, language=language)
        return SttResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:  # surface a clean error to the client
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
