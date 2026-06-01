"""
Speech-to-text using faster-whisper (CPU).

The model loads once on first use and is reused. On the free CPU tier we use the
"small" model with int8 quantization — a good accuracy/speed balance for short
clips. Override GUAVA_WHISPER_MODEL with "base"/"tiny" for more speed, or
"large-v3" if a GPU ever becomes available.
"""
from __future__ import annotations

import os
from functools import lru_cache

from faster_whisper import WhisperModel

MODEL_SIZE = os.getenv("GUAVA_WHISPER_MODEL", "small")


@lru_cache(maxsize=1)
def _model() -> WhisperModel:
    # int8 keeps memory and latency down on CPU.
    return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def _fmt_ts(seconds: float, sep: str) -> str:
    """Format seconds as HH:MM:SS<sep>mmm (sep is ',' for SRT, '.' for VTT)."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def transcribe(
    audio_path: str,
    language: str | None = None,
    task: str = "transcribe",
) -> dict:
    """Transcribe a file and return text plus SRT and VTT subtitle strings.

    task="transcribe" keeps the spoken language; task="translate" renders the
    output in English (Whisper only translates *to* English)."""
    segments, info = _model().transcribe(
        audio_path,
        language=language,  # None -> auto-detect
        task=task,
        # VAD with a low threshold: trims silence without dropping quiet or
        # short speech (an aggressive filter can blank out brief clips).
        vad_filter=True,
        vad_parameters={"threshold": 0.2, "min_silence_duration_ms": 500},
    )

    text_parts: list[str] = []
    srt_lines: list[str] = []
    vtt_lines: list[str] = ["WEBVTT", ""]
    seg_list: list[dict] = []  # structured segments for the UI (timestamps + seek)

    for i, seg in enumerate(segments, start=1):
        chunk = seg.text.strip()
        text_parts.append(chunk)
        seg_list.append(
            {"start": round(seg.start, 2), "end": round(seg.end, 2), "text": chunk}
        )

        srt_lines.append(str(i))
        srt_lines.append(f"{_fmt_ts(seg.start, ',')} --> {_fmt_ts(seg.end, ',')}")
        srt_lines.append(chunk)
        srt_lines.append("")

        vtt_lines.append(f"{_fmt_ts(seg.start, '.')} --> {_fmt_ts(seg.end, '.')}")
        vtt_lines.append(chunk)
        vtt_lines.append("")

    return {
        "text": " ".join(text_parts).strip(),
        "segments": seg_list,
        "srt": "\n".join(srt_lines).strip() + "\n",
        "vtt": "\n".join(vtt_lines).strip() + "\n",
        "language": info.language,
        "durationSec": round(info.duration, 2),
    }
