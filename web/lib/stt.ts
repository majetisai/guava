// Speech-to-text client. Posts an audio file to the inference service and
// returns the transcript plus subtitle formats. Swapping the backend model
// never changes this signature.

const BASE = process.env.NEXT_PUBLIC_INFERENCE_URL ?? "http://localhost:7860";

export type SttResult = {
  text: string;
  srt: string;
  vtt: string;
  language: string;
  durationSec: number;
};

export async function transcribe(
  audio: File,
  language?: string,
): Promise<SttResult> {
  const form = new FormData();
  form.append("audio", audio);
  if (language) form.append("language", language);

  const res = await fetch(`${BASE}/stt`, { method: "POST", body: form });

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // non-JSON error body; keep the status message
    }
    throw new Error(detail);
  }

  return res.json();
}
