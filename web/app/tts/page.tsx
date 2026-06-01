"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getVoices, synthesize, type VoiceMap } from "@/lib/tts";
import { DownloadButtons } from "@/components/DownloadButtons";

type Phase = "idle" | "working" | "warming" | "done" | "error";

const MAX_CHARS = 2000;

export default function TtsPage() {
  const [text, setText] = useState("");
  const [voices, setVoices] = useState<VoiceMap>({});
  const [voice, setVoice] = useState("af_heart");
  const [speed, setSpeed] = useState(1.0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [audioUrl, setAudioUrl] = useState("");
  const [error, setError] = useState("");

  // Load the available voices once.
  useEffect(() => {
    getVoices()
      .then((v) => {
        setVoices(v);
        const first = Object.keys(v)[0];
        if (first) setVoice(first);
      })
      .catch(() => setVoices({ af_heart: "Heart (US, female)" }));
  }, []);

  // Clean up the previous object URL when a new one replaces it.
  useEffect(() => {
    return () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, [audioUrl]);

  async function run() {
    if (!text.trim()) return;
    setPhase("working");
    setError("");
    const warm = setTimeout(() => setPhase("warming"), 4000);

    try {
      const blob = await synthesize(text, voice, speed);
      setAudioUrl(URL.createObjectURL(blob));
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setPhase("error");
    } finally {
      clearTimeout(warm);
    }
  }

  const busy = phase === "working" || phase === "warming";

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <Link href="/" className="text-sm text-gray-500 hover:text-pink-500">
        ← Guava
      </Link>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight">
        Text to Speech
      </h1>
      <p className="mt-2 text-gray-600 dark:text-gray-400">
        Type something, pick a voice, and turn it into natural speech.
      </p>

      <div className="mt-8 rounded-xl border border-gray-200 p-6 dark:border-gray-800">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX_CHARS))}
          placeholder="Type or paste text here…"
          className="h-40 w-full rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm dark:border-gray-800 dark:bg-gray-900"
        />
        <div className="mt-1 text-right text-xs text-gray-400">
          {text.length} / {MAX_CHARS}
        </div>

        {/* Voice + speed controls */}
        <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
          <label className="flex items-center gap-2">
            <span className="text-gray-500">Voice</span>
            <select
              value={voice}
              onChange={(e) => setVoice(e.target.value)}
              className="rounded-md border border-gray-300 bg-transparent px-2 py-1.5 dark:border-gray-700"
            >
              {Object.entries(voices).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2">
            <span className="text-gray-500">Speed</span>
            <input
              type="range"
              min={0.5}
              max={2}
              step={0.1}
              value={speed}
              onChange={(e) => setSpeed(parseFloat(e.target.value))}
              className="accent-pink-500"
            />
            <span className="w-8 font-mono text-xs text-gray-500">
              {speed.toFixed(1)}x
            </span>
          </label>
        </div>

        <button
          onClick={run}
          disabled={!text.trim() || busy}
          className="mt-5 rounded-md bg-gradient-to-r from-pink-500 to-purple-500 px-5 py-2 text-sm font-medium text-white shadow-sm transition hover:shadow-md disabled:opacity-40"
        >
          {busy ? "Generating…" : "Generate speech"}
        </button>

        {phase === "warming" && (
          <p className="mt-3 text-sm text-amber-600">
            Warming up the model (the first run loads it into memory)…
          </p>
        )}
        {phase === "error" && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>

      {phase === "done" && audioUrl && (
        <section className="mt-8">
          <h2 className="mb-3 text-lg font-medium">Result</h2>
          <audio src={audioUrl} controls autoPlay className="w-full" />
          <div className="mt-4">
            <DownloadButtons audioUrl={audioUrl} baseName="guava-speech" />
          </div>
        </section>
      )}
    </main>
  );
}
