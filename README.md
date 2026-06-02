# 🍈 Guava — Self-Hosted Voice AI

> Speech-to-text, text-to-speech, and voice cloning — powered by open-source
> models I host myself, not third-party AI APIs.

## What it does

| Feature | Model | Status |
|---------|-------|--------|
| Speech → Text | faster-whisper | ✅ working |
| Text → Speech | Kokoro | ✅ working |
| Voice Cloning | Kokoro + FreeVC (smooth) / XTTS-v2 (closest match) | ✅ working |
| Lip Sync | Wav2Lip | ✅ working |

Lip Sync takes a face (video or photo) + audio and produces a video with the
lips synced to the audio — chain it with a cloned voice for a full talking video.
Wav2Lip weights aren't committed; download them on setup:
`inference/wav2lip_src/checkpoints/wav2lip_gan.pth` and
`inference/wav2lip_src/face_detection/detection/sfd/s3fd.pth`.

Voice cloning offers two modes — a smooth Kokoro→FreeVC pipeline and a
higher-fidelity XTTS-v2 path — and reports a speaker-similarity score so you can
see how close the clone is. It has a consent gate and reads-aloud sample scripts.

## Architecture

```
Next.js (web/) ──► FastAPI inference service (inference/)
                        └─ faster-whisper · Kokoro · FreeVC · XTTS-v2 · Wav2Lip
```

## Evaluated but not included

**Microsoft VibeVoice** — a more realistic TTS model. Tested it directly and
shelved it: the lightweight realtime-0.5B isn't cleanly installable (its repo was
disabled), and the available 1.5B model pins `transformers==4.51.3`, which
hard-conflicts with Coqui (needs ≥4.57) — they can't share one environment, and
1.5B is too heavy for CPU. A future GPU deployment could run it as an isolated
service.

The web app never calls a third-party AI API — every model runs in the
inference service. Swapping a model means changing one wrapper, not the app.

## Repo layout

- `web/` — Next.js 16 app (App Router, TypeScript, Tailwind)
- `inference/` — FastAPI service wrapping the voice models

## Local development

```bash
# 1. Inference service
cd inference
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 7860

# 2. Web app (new terminal)
cd web
npm install
echo "NEXT_PUBLIC_INFERENCE_URL=http://localhost:7860" > .env.local
npm run dev
```

Open http://localhost:3000.

## Status

Built feature by feature. See commit history for the build story.
