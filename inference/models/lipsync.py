"""
Lip-sync via Wav2Lip (CPU).

Takes a face source (a video clip or a single photo) plus an audio file, and
produces a video where the face's lips are synced to the audio. This is the
"improve my video with new audio" feature — and it pairs with Guava's TTS and
voice cloning (generate audio there, sync it onto a video here).

Wav2Lip is run as a subprocess against its own source tree (inference.py), which
keeps its 2020-era code isolated from the rest of the service. Large inputs are
downscaled first so CPU inference stays reasonable.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

# Wav2Lip source lives alongside the inference service.
_W2L_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wav2lip_src")
_CHECKPOINT = os.path.join(_W2L_DIR, "checkpoints", "wav2lip_gan.pth")

# Cap the working resolution: Wav2Lip only needs the face region, and full-res
# frames make CPU inference crawl. We downscale the longest side to this.
_MAX_DIM = 480


def _downscale(src: str) -> str:
    """Downscale a video/image so its longest side is <= _MAX_DIM. Returns a temp
    file path (or the original if it's already small / on any error)."""
    import cv2

    cap = cv2.VideoCapture(src)
    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    cap.release()
    if not w or not h or max(w, h) <= _MAX_DIM:
        return src

    scale = _MAX_DIM / max(w, h)
    nw, nh = int(w * scale) // 2 * 2, int(h * scale) // 2 * 2  # even dims for codecs
    ext = os.path.splitext(src)[1] or ".mp4"
    fd, out = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", src, "-vf", f"scale={nw}:{nh}", out],
        check=True,
    )
    return out


def lipsync(face_path: str, audio_path: str) -> bytes:
    """Sync the face in `face_path` (video or image) to `audio_path`. Returns the
    resulting MP4 as bytes."""
    if not os.path.exists(_CHECKPOINT):
        raise RuntimeError("Wav2Lip checkpoint is missing.")

    face = _downscale(face_path)
    fd, out_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)

    cmd = [
        "python", "inference.py",
        "--checkpoint_path", _CHECKPOINT,
        "--face", face,
        "--audio", audio_path,
        "--outfile", out_path,
        "--wav2lip_batch_size", "16",
        "--face_det_batch_size", "4",
        "--resize_factor", "1",
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=_W2L_DIR, capture_output=True, timeout=1800
        )
        if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            err = proc.stderr.decode("utf-8", "ignore")[-400:]
            # A common, user-fixable case: no face found in the source.
            if "Face not detected" in err or "face" in err.lower():
                raise RuntimeError(
                    "No face detected in the video/photo. Use a clear, front-facing shot."
                )
            raise RuntimeError(f"Lip-sync failed: {err or 'unknown error'}")
        with open(out_path, "rb") as f:
            return f.read()
    except subprocess.TimeoutExpired:
        raise RuntimeError("Lip-sync timed out (try a shorter clip).")
    finally:
        for p in (out_path,):
            if os.path.exists(p):
                os.remove(p)
        if face != face_path and os.path.exists(face):
            os.remove(face)
