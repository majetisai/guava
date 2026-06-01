"use client";

import { useState } from "react";
import { downloadAudio, type AudioFormat } from "@/lib/download";

const FORMATS: { fmt: AudioFormat; label: string; hint: string }[] = [
  { fmt: "mp3", label: "MP3", hint: "small, plays everywhere" },
  { fmt: "wav", label: "WAV", hint: "uncompressed, largest" },
  { fmt: "m4a", label: "M4A", hint: "small, Apple-friendly" },
  { fmt: "flac", label: "FLAC", hint: "lossless" },
];

// Download an audio URL in several formats. Non-WAV formats are converted on
// the server, so we show a per-format "Converting…" state.
export function DownloadButtons({
  audioUrl,
  baseName,
}: {
  audioUrl: string;
  baseName: string;
}) {
  const [busy, setBusy] = useState<AudioFormat | null>(null);
  const [error, setError] = useState("");

  async function handle(fmt: AudioFormat) {
    setBusy(fmt);
    setError("");
    try {
      await downloadAudio(audioUrl, fmt, baseName);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <p className="mb-2 text-xs text-gray-400">Download as</p>
      <div className="flex flex-wrap gap-2">
        {FORMATS.map(({ fmt, label, hint }) => (
          <button
            key={fmt}
            onClick={() => handle(fmt)}
            disabled={busy !== null}
            title={hint}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:border-pink-400 hover:text-pink-500 disabled:opacity-50 dark:border-gray-700"
          >
            {busy === fmt ? "Converting…" : label}
          </button>
        ))}
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
