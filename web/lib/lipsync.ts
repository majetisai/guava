// Lip-sync client. Sends a face (video or photo) + audio to the inference
// service, which re-syncs the face's lips to the audio. Async job: start, poll,
// then fetch the result video.

const BASE = process.env.NEXT_PUBLIC_INFERENCE_URL ?? "http://localhost:7860";

export async function startLipsync(
  face: Blob,
  audio: Blob,
  faceName = "face.mp4",
  audioName = "audio.wav",
): Promise<string> {
  const form = new FormData();
  form.append("face", face, faceName);
  form.append("audio", audio, audioName);

  const res = await fetch(`${BASE}/lipsync`, { method: "POST", body: form });
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

export type LipsyncStatus = "running" | "completed" | "failed";

export function lipsyncResultUrl(jobId: string): string {
  return `${BASE}/lipsync/result/${jobId}`;
}

// Poll until done. Resolves with the result video URL.
export async function waitForLipsync(
  jobId: string,
  onTick?: (elapsedSec: number) => void,
): Promise<string> {
  const start = Date.now();
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const res = await fetch(`${BASE}/lipsync/status/${jobId}`);
    if (!res.ok) throw new Error(`Status check failed (${res.status})`);
    const { status, error } = await res.json();
    if (status === "completed") return lipsyncResultUrl(jobId);
    if (status === "failed") throw new Error(error || "Lip-sync failed.");
    onTick?.(Math.floor((Date.now() - start) / 1000));
    await new Promise((r) => setTimeout(r, 2000));
  }
}
