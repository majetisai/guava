"""
Guava inference service.

A small FastAPI app that wraps the self-hosted voice models. Runs locally for
development and deploys to a free Hugging Face Space (CPU) for the live demo.

Endpoints (added per feature):
  POST /stt      audio -> text (+ SRT, VTT)   [live]
  POST /tts      text  -> audio (WAV)         [live]
  POST /clone    sample + text -> job id       [live, async]
  POST /lipsync  face video/photo + audio -> job id  [live, async]
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
        features={"stt": True, "tts": True, "clone": True, "lipsync": True},
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

MAX_CLONE_CHARS = int(os.getenv("GUAVA_MAX_CLONE_CHARS", "3000"))

# In-memory job store. Fine for a single-process demo; a real deployment would
# use Redis or a DB. Each entry:
#   {status, audio (bytes|None), error (str|None), done (int), total (int)}
_clone_jobs: dict[str, dict] = {}


def _run_clone(job_id: str, text: str, ref_path: str, language: str, mode: str) -> None:
    """Background worker: generate the clone, store result + similarity, clean up."""
    try:
        from models.clone import clone_speak  # lazy import (loads the models)

        def progress(done: int, total: int) -> None:
            job = _clone_jobs.get(job_id)
            if job is not None:
                job["done"] = done
                job["total"] = total

        result = clone_speak(
            text, ref_path, language=language, mode=mode, on_progress=progress
        )
        job = _clone_jobs[job_id]
        job.update(
            status="completed",
            audio=result["audio"],
            similarity=result.get("similarity"),
            error=None,
        )
    except Exception as exc:
        job = _clone_jobs.get(job_id, {})
        job.update(status="failed", audio=None, error=str(exc))
        _clone_jobs[job_id] = job
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
    mode: str = Form(default="smooth"),
) -> dict:
    """Start a voice-clone job. Returns a job id immediately; poll
    /clone/status/{id} for the result. Cloning is slow on CPU, so we don't
    block the request.

    mode: "smooth" (Kokoro+FreeVC, best flow) or "match" (XTTS, stronger voice)."""
    if mode not in ("smooth", "match"):
        raise HTTPException(status_code=400, detail="mode must be smooth or match.")
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
    _clone_jobs[job_id] = {
        "status": "running",
        "audio": None,
        "error": None,
        "done": 0,
        "total": 0,
        "similarity": None,
    }
    background.add_task(_run_clone, job_id, text, ref_path, language, mode)
    return {"jobId": job_id, "status": "running"}


@app.get("/clone/status/{job_id}")
def clone_status(job_id: str) -> dict:
    """Poll a clone job. Returns status, progress, and (on success) the speaker
    similarity score. Fetch /clone/result/{id} for the audio."""
    job = _clone_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    return {
        "status": job["status"],
        "error": job["error"],
        "done": job.get("done", 0),
        "total": job.get("total", 0),
        "similarity": job.get("similarity"),
    }


@app.get("/clone/result/{job_id}")
def clone_result(job_id: str) -> Response:
    """Return the generated WAV for a completed job."""
    job = _clone_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    if job["status"] != "completed" or job["audio"] is None:
        raise HTTPException(status_code=409, detail="Job not completed.")
    return Response(content=job["audio"], media_type="audio/wav")


# --------------------------------------------------------------------------
# Audio format conversion (so the UI can offer MP3 / M4A / FLAC downloads)
# --------------------------------------------------------------------------

# target format -> (ffmpeg args, mime type)
_CONVERT_FORMATS = {
    "mp3": (["-codec:a", "libmp3lame", "-q:a", "2", "-f", "mp3"], "audio/mpeg"),
    "m4a": (["-codec:a", "aac", "-b:a", "192k", "-f", "ipod"], "audio/mp4"),
    "flac": (["-codec:a", "flac", "-f", "flac"], "audio/flac"),
    "ogg": (["-codec:a", "libvorbis", "-q:a", "5", "-f", "ogg"], "audio/ogg"),
}


@app.post("/convert")
async def convert(audio: UploadFile = File(...), fmt: str = Form(...)) -> Response:
    """Convert uploaded audio to another format with ffmpeg and return it.
    Lets the frontend offer MP3/M4A/FLAC/OGG downloads of generated audio."""
    import subprocess

    fmt = fmt.lower()
    if fmt not in _CONVERT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format. Choose one of: {', '.join(_CONVERT_FORMATS)}.",
        )

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio.")

    args, mime = _CONVERT_FORMATS[fmt]
    # Read input from stdin, write output to stdout — no temp files needed.
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", *args, "pipe:1"]
    try:
        proc = subprocess.run(cmd, input=data, capture_output=True, timeout=120)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="ffmpeg is not installed on the server.")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Conversion timed out.")

    if proc.returncode != 0 or not proc.stdout:
        msg = proc.stderr.decode("utf-8", "ignore")[:200] or "conversion failed"
        raise HTTPException(status_code=500, detail=f"Conversion failed: {msg}")

    return Response(content=proc.stdout, media_type=mime)


# --------------------------------------------------------------------------
# Lip-sync (Wav2Lip) — async; takes a face (video/photo) + audio -> video
# --------------------------------------------------------------------------

# face uploads can be bigger than audio (it's video); allow more headroom
# Generous cap — the worker downscales to 480px anyway, so big uploads just cost
# bandwidth. 200MB comfortably covers phone videos.
MAX_FACE_BYTES = int(os.getenv("GUAVA_MAX_FACE_MB", "200")) * 1024 * 1024

_lipsync_jobs: dict[str, dict] = {}


def _run_lipsync(job_id: str, face_path: str, audio_path: str, quality: str) -> None:
    """Background worker: run Wav2Lip, store the video, clean up the inputs."""
    try:
        from models.lipsync import lipsync  # lazy import

        video = lipsync(face_path, audio_path, quality=quality)
        job = _lipsync_jobs[job_id]
        job.update(status="completed", video=video, error=None)
    except Exception as exc:
        job = _lipsync_jobs.get(job_id, {})
        job.update(status="failed", video=None, error=str(exc))
        _lipsync_jobs[job_id] = job
    finally:
        for p in (face_path, audio_path):
            if p and os.path.exists(p):
                os.remove(p)


@app.post("/lipsync")
async def lipsync_start(
    background: BackgroundTasks,
    face: UploadFile = File(...),
    audio: UploadFile = File(...),
    quality: str = Form(default="fast"),
) -> dict:
    """Start a lip-sync job: `face` is a video clip or a photo, `audio` is the
    speech to sync onto it. quality is "fast" (480p) or "high" (720p). Returns a
    job id; poll /lipsync/status/{id}."""
    if quality not in ("fast", "high"):
        raise HTTPException(status_code=400, detail="quality must be fast or high.")
    face_data = await face.read()
    if not face_data:
        raise HTTPException(status_code=400, detail="Empty face file.")
    if len(face_data) > MAX_FACE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Face file too large. Max {MAX_FACE_BYTES // (1024 * 1024)}MB.",
        )
    audio_data = await audio.read()
    if not audio_data:
        raise HTTPException(status_code=400, detail="Empty audio file.")

    face_suffix = os.path.splitext(face.filename or "")[1] or ".mp4"
    fd, face_path = tempfile.mkstemp(suffix=face_suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(face_data)
    audio_suffix = os.path.splitext(audio.filename or "")[1] or ".wav"
    fd, audio_path = tempfile.mkstemp(suffix=audio_suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(audio_data)

    job_id = uuid.uuid4().hex
    _lipsync_jobs[job_id] = {"status": "running", "video": None, "error": None}
    background.add_task(_run_lipsync, job_id, face_path, audio_path, quality)
    return {"jobId": job_id, "status": "running"}


@app.get("/lipsync/status/{job_id}")
def lipsync_status(job_id: str) -> dict:
    job = _lipsync_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    return {"status": job["status"], "error": job["error"]}


@app.get("/lipsync/result/{job_id}")
def lipsync_result(job_id: str) -> Response:
    job = _lipsync_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    if job["status"] != "completed" or job.get("video") is None:
        raise HTTPException(status_code=409, detail="Job not completed.")
    return Response(content=job["video"], media_type="video/mp4")
