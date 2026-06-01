// Audio download helpers. WAV is downloaded directly; other formats are
// converted on the server (ffmpeg) and then downloaded.

const BASE = process.env.NEXT_PUBLIC_INFERENCE_URL ?? "http://localhost:7860";

export type AudioFormat = "wav" | "mp3" | "m4a" | "flac";

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// Download `audioUrl` as the given format. WAV needs no conversion; everything
// else is routed through the /convert endpoint.
export async function downloadAudio(
  audioUrl: string,
  format: AudioFormat,
  baseName: string,
): Promise<void> {
  const srcRes = await fetch(audioUrl);
  if (!srcRes.ok) throw new Error("Couldn't load the audio to download.");
  const wav = await srcRes.blob();

  if (format === "wav") {
    triggerDownload(wav, `${baseName}.wav`);
    return;
  }

  const form = new FormData();
  form.append("audio", wav, "audio.wav");
  form.append("fmt", format);
  const res = await fetch(`${BASE}/convert`, { method: "POST", body: form });
  if (!res.ok) {
    let detail = `Conversion failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // keep status message
    }
    throw new Error(detail);
  }
  triggerDownload(await res.blob(), `${baseName}.${format}`);
}
