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


def clone_speak(
    text: str,
    reference_audio_path: str,
    language: str = "en",
) -> bytes:
    """Generate `text` spoken in the voice from `reference_audio_path`.
    Returns WAV bytes."""
    wav = _model().tts(
        text=text,
        speaker_wav=reference_audio_path,
        language=language,
    )

    audio = np.asarray(wav, dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    buf.seek(0)
    return buf.read()
