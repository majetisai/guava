"""
Voice cloning via a two-stage hybrid pipeline (CPU).

Stage 1: Kokoro speaks the text — clean, smooth, and says ONLY the text (no
         hallucination, because it isn't trying to clone).
Stage 2: FreeVC (a text-free voice converter, bundled with coqui-tts) morphs
         that clean speech to match the user's uploaded reference voice.

Result: Kokoro's smoothness with the user's voice — which is what XTTS alone
could not deliver. FreeVC only changes the voice timbre; it can't invent words,
so the random-words problem goes away by construction.
"""
from __future__ import annotations

import io
import os
import tempfile
from functools import lru_cache

import numpy as np
import soundfile as sf

# Auto-agree to Coqui's non-commercial license (CPML) so model loads don't prompt
# interactively and hang the headless server. Non-commercial portfolio use.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

SAMPLE_RATE = 24000

# Languages the clone can speak in. Limited to what Kokoro (stage 1) supports,
# since Kokoro generates the actual speech. Code -> (display name, kokoro lang).
LANGUAGES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "hi": "Hindi",
    "ja": "Japanese",
    "zh-cn": "Chinese",
}

# Map our language codes to Kokoro's single-letter codes + a default voice.
_KOKORO_LANG = {
    "en": ("a", "af_heart"),
    "es": ("e", "ef_dora"),
    "fr": ("f", "ff_siwis"),
    "it": ("i", "if_sara"),
    "pt": ("p", "pf_dora"),
    "hi": ("h", "hf_alpha"),
    "ja": ("j", "jf_alpha"),
    "zh-cn": ("z", "zf_xiaobei"),
}


@lru_cache(maxsize=1)
def _converter():
    """FreeVC voice converter (bundled with coqui-tts). Loads once."""
    from TTS.api import TTS

    return TTS("voice_conversion_models/multilingual/vctk/freevc24").to("cpu")


def _clean_text(text: str) -> str:
    """Normalize text so synthesis is clean: strip quotes/brackets/stray symbols,
    normalize dashes and whitespace."""
    import re

    t = text.replace("“", "").replace("”", "").replace('"', "")
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("—", ", ").replace("–", ", ").replace("--", ", ")
    t = t.replace("…", ".")
    t = re.sub(r"[\"`*_#<>\[\]{}|~^]", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


# A short silence between stitched sentences so they don't run together.
_GAP = np.zeros(int(SAMPLE_RATE * 0.15), dtype=np.float32)


@lru_cache(maxsize=1)
def _kokoro(lang_code: str):
    from kokoro import KPipeline

    return KPipeline(lang_code=lang_code)


def _kokoro_speak(text: str, lang_code: str, voice: str) -> np.ndarray:
    """Stage 1: generate clean speech with Kokoro. Returns float32 audio at
    SAMPLE_RATE. Kokoro outputs 24kHz, matching our sample rate."""
    pipeline = _kokoro(lang_code)
    parts: list[np.ndarray] = []
    for _gs, _ps, audio in pipeline(text, voice=voice):
        parts.append(np.asarray(audio, dtype=np.float32))
    if not parts:
        return np.zeros(0, dtype=np.float32)
    out = parts[0] if len(parts) == 1 else np.concatenate(parts)
    return out


def _decode_to_wav(path: str) -> str:
    """Decode any input (webm/mp3/m4a/…) to a clean mono WAV via ffmpeg. FreeVC
    and soundfile can't reliably read compressed formats like webm, so we always
    normalize the container first. Returns a temp WAV path."""
    import subprocess

    fd, out = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", path, "-ac", "1", "-ar", str(SAMPLE_RATE), out],
        check=True,
    )
    return out


def _prepare_reference(path: str) -> str:
    """Decode the reference to WAV, then clean it: trim silence + normalize
    volume so the converter has a clear, well-leveled voice to copy."""
    wav_path = _decode_to_wav(path)
    try:
        import librosa

        y, _ = librosa.load(wav_path, sr=SAMPLE_RATE, mono=True)
        if y.size == 0:
            return wav_path
        y, _ = librosa.effects.trim(y, top_db=30)
        peak = float(np.max(np.abs(y)))
        if peak > 0:
            y = y * (0.95 / peak)
        sf.write(wav_path, y, SAMPLE_RATE)
        return wav_path
    except Exception:
        # decoding succeeded even if trimming didn't — the WAV is still usable
        return wav_path


def clone_speak(
    text: str,
    reference_audio_path: str,
    language: str = "en",
    on_progress=None,
) -> bytes:
    """Two-stage clone: Kokoro speaks the text, then FreeVC converts the result
    to the reference voice. `on_progress(done, total)` reports progress across
    the two stages. Returns WAV bytes."""
    lang_code, voice = _KOKORO_LANG.get(language, _KOKORO_LANG["en"])
    cleaned = _clean_text(text)
    if not cleaned:
        cleaned = text

    # --- Stage 1: clean speech from Kokoro ---
    speech = _kokoro_speak(cleaned, lang_code, voice)
    if on_progress:
        on_progress(1, 2)
    if speech.size == 0:
        raise ValueError("No speech produced (empty text?).")

    # Write Kokoro's output to a temp file for the converter to read.
    fd, src_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    sf.write(src_path, speech, SAMPLE_RATE)

    ref = _prepare_reference(reference_audio_path)
    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    try:
        # --- Stage 2: morph the clean speech to the reference voice ---
        try:
            _converter().voice_conversion_to_file(
                source_wav=src_path,
                target_wav=ref,
                file_path=out_path,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Voice conversion failed (check the reference audio): {exc}"
            ) from exc
        if on_progress:
            on_progress(2, 2)

        converted, sr = sf.read(out_path, dtype="float32")
        buf = io.BytesIO()
        sf.write(buf, converted, sr, format="WAV")
        buf.seek(0)
        return buf.read()
    finally:
        for p in (src_path, out_path):
            if os.path.exists(p):
                os.remove(p)
        if ref != reference_audio_path and os.path.exists(ref):
            os.remove(ref)
