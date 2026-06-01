"""
Guava inference service.

A small FastAPI app that wraps the self-hosted voice models. Runs locally for
development and deploys to a free Hugging Face Space (CPU) for the live demo.

Endpoints (added per feature):
  POST /stt    audio -> text (+ SRT, VTT)   [live]
  POST /tts    text  -> audio (WAV)         [live]
  POST /clone  sample + text -> job id       [live, async]
  GET  /clone/status/{id} -> job status / audio
"""
from __future__ import annotations

import os
import tempfile
import uuid

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
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
        features={"stt": True, "tts": True, "clone": True},
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


# --------------------------------------------------------------------------
# Voice cloning (Coqui XTTS-v2) — async, because it's slow on CPU
# --------------------------------------------------------------------------

MAX_CLONE_CHARS = int(os.getenv("GUAVA_MAX_CLONE_CHARS", "500"))

# In-memory job store. Fine for a single-process demo; a real deployment would
# use Redis or a DB. Each entry: {status, audio (bytes|None), error (str|None)}.
_clone_jobs: dict[str, dict] = {}


def _run_clone(job_id: str, text: str, ref_path: str, language: str) -> None:
    """Background worker: generate the clone, store the result, clean up."""
    try:
        from models.clone import clone_speak  # lazy import (loads XTTS-v2)

        wav = clone_speak(text, ref_path, language=language)
        _clone_jobs[job_id] = {"status": "completed", "audio": wav, "error": None}
    except Exception as exc:
        _clone_jobs[job_id] = {"status": "failed", "audio": None, "error": str(exc)}
    finally:
        if os.path.exists(ref_path):
            os.remove(ref_path)


@app.get("/clone/languages")
def clone_languages() -> dict:
    """Languages the cloned voice can speak in."""
    from models.clone import LANGUAGES

    return {"languages": LANGUAGES}


@app.post("/clone")
async def clone(
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    text: str = Form(...),
    language: str = Form(default="en"),
) -> dict:
    """Start a voice-clone job. Returns a job id immediately; poll
    /clone/status/{id} for the result. Cloning is slow on CPU, so we don't
    block the request."""
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is empty.")
    if len(text) > MAX_CLONE_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text too long. Max {MAX_CLONE_CHARS} characters for cloning.",
        )

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty reference audio.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Reference audio too large.")

    # Persist the reference clip; the worker deletes it when done.
    suffix = os.path.splitext(audio.filename or "")[1] or ".wav"
    fd, ref_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)

    job_id = uuid.uuid4().hex
    _clone_jobs[job_id] = {"status": "running", "audio": None, "error": None}
    background.add_task(_run_clone, job_id, text, ref_path, language)
    return {"jobId": job_id, "status": "running"}


@app.get("/clone/status/{job_id}")
def clone_status(job_id: str) -> dict:
    """Poll a clone job. While running, returns {status:"running"}. On success
    the client should fetch /clone/result/{id} for the audio."""
    job = _clone_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    return {"status": job["status"], "error": job["error"]}


@app.get("/clone/result/{job_id}")
def clone_result(job_id: str) -> Response:
    """Return the generated WAV for a completed job."""
    job = _clone_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    if job["status"] != "completed" or job["audio"] is None:
        raise HTTPException(status_code=409, detail="Job not completed.")
    return Response(content=job["audio"], media_type="audio/wav")
