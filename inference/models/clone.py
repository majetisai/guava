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


@lru_cache(maxsize=1)
def _xtts():
    """XTTS-v2 — direct zero-shot cloning. Stronger voice match than the hybrid
    path, but less smooth. Loaded only when 'match' mode is used."""
    from TTS.api import TTS

    return TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")


@lru_cache(maxsize=1)
def _speaker_encoder():
    """Resemblyzer voice encoder for speaker-similarity scoring."""
    from resemblyzer import VoiceEncoder

    return VoiceEncoder(verbose=False)


def _similarity(ref_wav_path: str, clone_audio: np.ndarray) -> float | None:
    """Cosine similarity (0..1) between the reference voice and the clone, using
    speaker embeddings. Returns None if it can't be computed."""
    try:
        from resemblyzer import preprocess_wav

        enc = _speaker_encoder()
        fd, tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        sf.write(tmp, clone_audio, SAMPLE_RATE)
        try:
            e_ref = enc.embed_utterance(preprocess_wav(ref_wav_path))
            e_clone = enc.embed_utterance(preprocess_wav(tmp))
            return round(float(np.dot(e_ref, e_clone)), 3)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    except Exception:
        return None


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


def _to_wav_bytes(audio: np.ndarray, sr: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    buf.seek(0)
    return buf.read()


def _clone_smooth(text: str, ref: str, language: str, on_progress) -> np.ndarray:
    """Hybrid path: Kokoro speaks (smooth, exact text) -> FreeVC morphs to the
    reference voice. Best flow, moderate voice match."""
    lang_code, voice = _KOKORO_LANG.get(language, _KOKORO_LANG["en"])
    cleaned = _clean_text(text) or text

    speech = _kokoro_speak(cleaned, lang_code, voice)
    if on_progress:
        on_progress(1, 2)
    if speech.size == 0:
        raise ValueError("No speech produced (empty text?).")

    fd, src_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    sf.write(src_path, speech, SAMPLE_RATE)
    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        try:
            _converter().voice_conversion_to_file(
                source_wav=src_path, target_wav=ref, file_path=out_path
            )
        except Exception as exc:
            raise RuntimeError(
                f"Voice conversion failed (check the reference audio): {exc}"
            ) from exc
        if on_progress:
            on_progress(2, 2)
        converted, _ = sf.read(out_path, dtype="float32")
        return np.asarray(converted, dtype=np.float32)
    finally:
        for p in (src_path, out_path):
            if os.path.exists(p):
                os.remove(p)


def _clone_match(text: str, ref: str, language: str, on_progress) -> np.ndarray:
    """Direct XTTS-v2 zero-shot clone: stronger voice match, less smooth."""
    cleaned = _clean_text(text) or text
    if on_progress:
        on_progress(1, 2)
    wav = _xtts().tts(
        text=cleaned,
        speaker_wav=ref,
        language=language if language in LANGUAGES else "en",
        temperature=0.7,
        repetition_penalty=10.0,
        enable_text_splitting=True,
    )
    if on_progress:
        on_progress(2, 2)
    return np.asarray(wav, dtype=np.float32)


def clone_speak(
    text: str,
    reference_audio_path: str,
    language: str = "en",
    mode: str = "smooth",
    on_progress=None,
) -> dict:
    """Clone `text` in the reference voice.

    mode="smooth"  -> Kokoro + FreeVC hybrid (best flow, moderate match)
    mode="match"   -> XTTS-v2 direct (stronger voice match, less smooth)

    Returns {"audio": wav_bytes, "similarity": float|None} where similarity is
    the 0..1 speaker match between the clone and the reference."""
    ref = _prepare_reference(reference_audio_path)
    try:
        if mode == "match":
            audio = _clone_match(text, ref, language, on_progress)
        else:
            audio = _clone_smooth(text, ref, language, on_progress)

        similarity = _similarity(ref, audio)
        return {"audio": _to_wav_bytes(audio), "similarity": similarity}
    finally:
        if ref != reference_audio_path and os.path.exists(ref):
            os.remove(ref)
