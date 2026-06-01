"""
Voice cloning using Coqui XTTS-v2 (zero-shot, CPU).

Give it a short reference clip (~6-15s of clean speech) and some text, and it
generates that text spoken in the reference voice. No training — it's zero-shot,
so a clone is ready immediately. XTTS-v2 is large (~1.8GB) and slow on CPU, so
callers should run this as a background job.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache

import numpy as np
import soundfile as sf

# Auto-agree to Coqui's non-commercial license (CPML). XTTS-v2 otherwise prompts
# interactively on first load, which hangs a headless server. This project is a
# non-commercial portfolio piece, which the CPML permits.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

SAMPLE_RATE = 24000

# Languages XTTS-v2 can speak in (the cloned voice can cross languages).
LANGUAGES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "pl": "Polish",
    "tr": "Turkish",
    "ru": "Russian",
    "nl": "Dutch",
    "cs": "Czech",
    "ar": "Arabic",
    "zh-cn": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "hi": "Hindi",
}


@lru_cache(maxsize=1)
def _model():
    # Imported here so the heavy library only loads when cloning is first used.
    from TTS.api import TTS

    # Coqui's XTTS-v2; runs on CPU. The first call downloads the weights.
    return TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")


def _clean_text(text: str) -> str:
    """Reduce XTTS hallucinations. The model tends to invent extra speech around
    quote marks, stray symbols, and odd spacing, so we normalize the text before
    synthesis: strip quotes/brackets, collapse whitespace, normalize dashes."""
    import re

    t = text.replace("“", "").replace("”", "").replace('"', "")
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("—", ", ").replace("–", ", ").replace("--", ", ")
    t = t.replace("…", ".")
    # drop characters XTTS doesn't speak but may react to
    t = re.sub(r"[\"`*_#<>\[\]{}|~^]", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def _split_sentences(text: str) -> list[str]:
    """Split text into sentence-ish chunks so long input can be generated piece
    by piece (with progress) and stitched back together. Each chunk is cleaned;
    fragments shorter than 2 chars are dropped (they trigger hallucinations) and
    every chunk is made to end with punctuation so the model knows it's done."""
    import re

    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    out: list[str] = []
    for p in parts:
        c = _clean_text(p)
        if len(c) < 2:
            continue
        if c[-1] not in ".!?":
            c += "."
        out.append(c)
    return out


# A short silence inserted between stitched sentences so they don't run together.
_GAP = np.zeros(int(SAMPLE_RATE * 0.18), dtype=np.float32)


def _trim_trailing(audio: np.ndarray) -> np.ndarray:
    """Trim trailing near-silence from a chunk. XTTS often appends a quiet tail
    that can carry mumbled/hallucinated artifacts; cutting it removes the random
    sounds at the end while leaving the real speech intact."""
    if audio.size == 0:
        return audio
    win = int(SAMPLE_RATE * 0.02)  # 20ms analysis windows
    threshold = 0.015              # below this RMS is treated as silence
    last_voiced = 0
    for start in range(0, len(audio) - win, win):
        seg = audio[start : start + win]
        if np.sqrt(np.mean(seg * seg)) > threshold:
            last_voiced = start + win
    if last_voiced == 0:
        return audio
    # keep a little padding after the last voiced window so it doesn't clip
    end = min(len(audio), last_voiced + int(SAMPLE_RATE * 0.08))
    return audio[:end]


def clone_speak(
    text: str,
    reference_audio_path: str,
    language: str = "en",
    on_progress=None,
) -> bytes:
    """Generate `text` spoken in the voice from `reference_audio_path`.

    Long text is split into sentences and generated one at a time. `on_progress`,
    if given, is called as on_progress(done, total) after each chunk so callers
    can report a progress bar. Returns the concatenated WAV bytes."""
    model = _model()
    chunks = _split_sentences(text)
    if not chunks:
        chunks = [_clean_text(text) or text]
    total = len(chunks)

    audio_parts: list[np.ndarray] = []
    for i, chunk in enumerate(chunks, start=1):
        wav = model.tts(
            text=chunk,
            speaker_wav=reference_audio_path,
            language=language,
            # Anti-hallucination settings. Lower temperature + a repetition
            # penalty stop the decoder from "running away" into invented words
            # at the end of a chunk; a short length_penalty discourages it from
            # padding past the actual text.
            temperature=0.65,
            repetition_penalty=10.0,
            length_penalty=1.0,
            top_k=50,
            top_p=0.85,
            enable_text_splitting=False,
        )
        audio = _trim_trailing(np.asarray(wav, dtype=np.float32))
        if audio_parts:
            audio_parts.append(_GAP)
        audio_parts.append(audio)
        if on_progress:
            on_progress(i, total)

    audio = np.concatenate(audio_parts) if audio_parts else np.zeros(0, np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    buf.seek(0)
    return buf.read()
