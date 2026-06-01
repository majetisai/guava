// Voice cloning client. Cloning is slow on CPU, so the backend runs it as an
// async job: start it, poll status, then fetch the resulting audio.

const BASE = process.env.NEXT_PUBLIC_INFERENCE_URL ?? "http://localhost:7860";

export type LanguageMap = Record<string, string>;

export async function getCloneLanguages(): Promise<LanguageMap> {
  const res = await fetch(`${BASE}/clone/languages`);
  if (!res.ok) throw new Error(`Failed to load languages (${res.status})`);
  const body = await res.json();
  return body.languages as LanguageMap;
}

export async function startClone(
  referenceAudio: Blob,
  text: string,
  language: string,
  filename = "reference.wav",
): Promise<string> {
  const form = new FormData();
  form.append("audio", referenceAudio, filename);
  form.append("text", text);
  form.append("language", language);

  const res = await fetch(`${BASE}/clone`, { method: "POST", body: form });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // keep status message
    }
    throw new Error(detail);
  }
  const body = await res.json();
  return body.jobId as string;
}

export type CloneStatus = "running" | "completed" | "failed";

export type CloneProgress = {
  status: CloneStatus;
  error: string | null;
  done: number;
  total: number;
};

export async function getCloneStatus(jobId: string): Promise<CloneProgress> {
  const res = await fetch(`${BASE}/clone/status/${jobId}`);
  if (!res.ok) throw new Error(`Status check failed (${res.status})`);
  return res.json();
}

export function cloneResultUrl(jobId: string): string {
  return `${BASE}/clone/result/${jobId}`;
}

// Poll until the job finishes (or fails). Resolves with the audio URL.
// onTick reports elapsed seconds plus how many sentence-chunks are done.
export async function waitForClone(
  jobId: string,
  onTick?: (elapsedSec: number, done: number, total: number) => void,
): Promise<string> {
  const start = Date.now();
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { status, error, done, total } = await getCloneStatus(jobId);
    if (status === "completed") return cloneResultUrl(jobId);
    if (status === "failed") throw new Error(error || "Cloning failed.");
    onTick?.(Math.floor((Date.now() - start) / 1000), done, total);
    await new Promise((r) => setTimeout(r, 2000));
  }
}
