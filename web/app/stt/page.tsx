"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { transcribe, type SttResult } from "@/lib/stt";

type Phase = "idle" | "working" | "warming" | "done" | "error";

export default function SttPage() {
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<SttResult | null>(null);
  const [error, setError] = useState("");
  const warmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function run() {
    if (!file) return;
    setPhase("working");
    setError("");
    setResult(null);

    // If it's slow, tell the user the model is warming up rather than looking
    // frozen (the first transcription loads the model into memory).
    warmTimer.current = setTimeout(() => setPhase("warming"), 4000);

    try {
      const res = await transcribe(file);
      setResult(res);
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setPhase("error");
    } finally {
      if (warmTimer.current) clearTimeout(warmTimer.current);
    }
  }

  const busy = phase === "working" || phase === "warming";

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <Link href="/" className="text-sm text-gray-500 hover:text-pink-500">
        ← Guava
      </Link>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight">
        Speech to Text
      </h1>
      <p className="mt-2 text-gray-600 dark:text-gray-400">
        Upload an audio file and get a transcript with SRT and VTT export.
      </p>

      <div className="mt-8 rounded-xl border border-gray-200 p-6 dark:border-gray-800">
        <input
          type="file"
          accept="audio/*,video/*"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setPhase("idle");
            setResult(null);
            setError("");
          }}
          className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-pink-500 file:px-4 file:py-2 file:text-white hover:file:bg-pink-600"
        />

        <button
          onClick={run}
          disabled={!file || busy}
          className="mt-4 rounded-md bg-gray-900 px-5 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-gray-900"
        >
          {busy ? "Transcribing…" : "Transcribe"}
        </button>

        {phase === "warming" && (
          <p className="mt-3 text-sm text-amber-600">
            Warming up the model (the first run loads it into memory)…
          </p>
        )}
        {phase === "error" && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>

      {result && (
        <section className="mt-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-medium">Transcript</h2>
            <span className="text-xs text-gray-400">
              {result.language?.toUpperCase()} · {result.durationSec}s
            </span>
          </div>
          <textarea
            readOnly
            value={result.text}
            className="h-48 w-full rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm dark:border-gray-800 dark:bg-gray-900"
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <DownloadButton name="transcript.txt" content={result.text} label="Download .txt" />
            <DownloadButton name="transcript.srt" content={result.srt} label="Download .srt" />
            <DownloadButton name="transcript.vtt" content={result.vtt} label="Download .vtt" />
          </div>
        </section>
      )}
    </main>
  );
}

function DownloadButton({
  name,
  content,
  label,
}: {
  name: string;
  content: string;
  label: string;
}) {
  function download() {
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <button
      onClick={download}
      className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:border-pink-400 hover:text-pink-500 dark:border-gray-700"
    >
      {label}
    </button>
  );
}
