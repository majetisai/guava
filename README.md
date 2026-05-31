# 🍈 Guava — Self-Hosted Voice AI

> Speech-to-text, text-to-speech, and voice cloning — powered by open-source
> models I host myself, not third-party AI APIs.

## What it does

| Feature | Model | Status |
|---------|-------|--------|
| Speech → Text | faster-whisper | ✅ working |
| Text → Speech | Kokoro | planned |
| Voice Cloning | OpenVoice (with consent flow) | planned |

## Architecture

```
Next.js (web/) ──► FastAPI inference service (inference/)
                        └─ faster-whisper · Kokoro · OpenVoice
```

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
