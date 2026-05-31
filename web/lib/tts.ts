// Text-to-speech client. Sends text to the inference service and gets back a
// WAV audio blob (as an object URL ready for an <audio> element).

const BASE = process.env.NEXT_PUBLIC_INFERENCE_URL ?? "http://localhost:7860";

export type VoiceMap = Record<string, string>;

export async function getVoices(): Promise<VoiceMap> {
  const res = await fetch(`${BASE}/voices`);
  if (!res.ok) throw new Error(`Failed to load voices (${res.status})`);
  const body = await res.json();
  return body.voices as VoiceMap;
}

export async function synthesize(
  text: string,
  voice: string,
  speed: number,
): Promise<Blob> {
  const res = await fetch(`${BASE}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice, speed }),
  });

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // non-JSON error; keep status message
    }
    throw new Error(detail);
  }

  return res.blob();
}
