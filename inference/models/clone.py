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


def _split_sentences(text: str) -> list[str]:
    """Split text into sentence-ish chunks so long input can be generated piece
    by piece (with progress) and stitched back together. Splits on . ! ? and
    newlines, keeping the delimiter."""
    import re

    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


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
    chunks = _split_sentences(text) or [text]
    total = len(chunks)

    audio_parts: list[np.ndarray] = []
    for i, chunk in enumerate(chunks, start=1):
        wav = model.tts(
            text=chunk,
            speaker_wav=reference_audio_path,
            language=language,
        )
        audio_parts.append(np.asarray(wav, dtype=np.float32))
        if on_progress:
            on_progress(i, total)

    audio = np.concatenate(audio_parts) if audio_parts else np.zeros(0, np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    buf.seek(0)
    return buf.read()
