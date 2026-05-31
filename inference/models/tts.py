"""
Text-to-speech using Kokoro (82M, CPU-friendly).

The pipeline loads once per language and is reused. Kokoro is tiny and genuinely
fast on CPU, so it fits the free-tier setup well. Output is 24kHz mono audio.
"""
from __future__ import annotations

import io
from functools import lru_cache

import numpy as np
import soundfile as sf
from kokoro import KPipeline

SAMPLE_RATE = 24000

# Voices the UI offers. Prefix: a=American, b=British English.
# f=female, m=male. (Kokoro ships more; this is a curated set.)
VOICES: dict[str, str] = {
    "af_heart": "Heart (US, female)",
    "af_bella": "Bella (US, female)",
    "af_nicole": "Nicole (US, female)",
    "am_adam": "Adam (US, male)",
    "am_michael": "Michael (US, male)",
    "bf_emma": "Emma (UK, female)",
    "bf_isabella": "Isabella (UK, female)",
    "bm_george": "George (UK, male)",
    "bm_lewis": "Lewis (UK, male)",
}


@lru_cache(maxsize=2)
def _pipeline(lang_code: str) -> KPipeline:
    return KPipeline(lang_code=lang_code)


def synthesize(text: str, voice: str = "af_heart", speed: float = 1.0) -> bytes:
    """Render text to speech and return WAV bytes.

    The voice prefix selects the accent: voices starting with 'b' are British
    (lang_code 'b'), everything else uses American English (lang_code 'a')."""
    lang_code = "b" if voice.startswith("b") else "a"
    pipeline = _pipeline(lang_code)

    # Kokoro yields one chunk per sentence/line; concatenate into one clip.
    chunks: list[np.ndarray] = []
    for _gs, _ps, audio in pipeline(text, voice=voice, speed=speed):
        chunks.append(audio)

    if not chunks:
        raise ValueError("No audio produced (empty text?).")

    full = np.concatenate(chunks)
    buf = io.BytesIO()
    sf.write(buf, full, SAMPLE_RATE, format="WAV")
    buf.seek(0)
    return buf.read()
