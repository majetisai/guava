// Speech-to-text client. Posts an audio file to the inference service and
// returns the transcript plus subtitle formats. Swapping the backend model
// never changes this signature.

const BASE = process.env.NEXT_PUBLIC_INFERENCE_URL ?? "http://localhost:7860";

export type Segment = {
  start: number;
  end: number;
  text: string;
};

export type SttResult = {
  text: string;
  segments: Segment[];
  srt: string;
  vtt: string;
  language: string;
  durationSec: number;
};

export type LanguageMap = Record<string, string>;

export async function getLanguages(): Promise<LanguageMap> {
  const res = await fetch(`${BASE}/languages`);
  if (!res.ok) throw new Error(`Failed to load languages (${res.status})`);
  const body = await res.json();
  return body.languages as LanguageMap;
}

export async function transcribe(
  audio: Blob,
  opts: { language?: string; task?: "transcribe" | "translate"; filename?: string } = {},
): Promise<SttResult> {
  const form = new FormData();
  form.append("audio", audio, opts.filename ?? "recording.webm");
  // "auto" means let Whisper detect; don't send a language in that case.
  if (opts.language && opts.language !== "auto") form.append("language", opts.language);
  if (opts.task) form.append("task", opts.task);

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
