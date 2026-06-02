"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { startLipsync, waitForLipsync } from "@/lib/lipsync";

type Phase = "idle" | "working" | "done" | "error";

export default function LipsyncPage() {
  const [face, setFace] = useState<File | null>(null);
  const [faceUrl, setFaceUrl] = useState("");
  const [audio, setAudio] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState("");

  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [resultUrl, setResultUrl] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!face) return setFaceUrl("");
    const u = URL.createObjectURL(face);
    setFaceUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [face]);

  useEffect(() => {
    if (!audio) return setAudioUrl("");
    const u = URL.createObjectURL(audio);
    setAudioUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [audio]);

  const faceIsVideo = face?.type.startsWith("video");

  async function run() {
    if (!face || !audio) return;
    setPhase("working");
    setError("");
    setResultUrl("");
    setElapsed(0);
    try {
      const jobId = await startLipsync(face, audio, face.name, audio.name);
      const url = await waitForLipsync(jobId, setElapsed);
      setResultUrl(url);
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setPhase("error");
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <Link href="/" className="text-sm text-gray-500 hover:text-pink-500">
        ← Guava
      </Link>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight">Lip Sync</h1>
      <p className="mt-2 text-gray-600 dark:text-gray-400">
        Upload a video or photo of a face, attach audio, and get a video with the
        lips synced to that audio. Pair it with a cloned voice for a full talking
        video.
      </p>

      <div className="mt-8 rounded-xl border border-gray-200 p-6 dark:border-gray-800">
        {/* Face */}
        <p className="mb-2 text-sm font-medium">1. Face (video or photo)</p>
        <input
          type="file"
          accept="video/*,image/*"
          onChange={(e) => {
            setFace(e.target.files?.[0] ?? null);
            setPhase("idle");
            setResultUrl("");
          }}
          className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-pink-500 file:px-4 file:py-2 file:text-white hover:file:bg-pink-600"
        />
        <p className="mt-2 text-xs text-gray-500">
          A clear, front-facing shot works best. Short clips process faster on
          CPU.
        </p>
        {faceUrl &&
          (faceIsVideo ? (
            <video src={faceUrl} controls className="mt-3 w-full rounded-lg" />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={faceUrl}
              alt="face preview"
              className="mt-3 max-h-64 rounded-lg"
            />
          ))}

        {/* Audio */}
        <p className="mt-6 mb-2 text-sm font-medium">2. Audio</p>
        <input
          type="file"
          accept="audio/*"
          onChange={(e) => {
            setAudio(e.target.files?.[0] ?? null);
            setPhase("idle");
            setResultUrl("");
          }}
          className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-pink-500 file:px-4 file:py-2 file:text-white hover:file:bg-pink-600"
        />
        <p className="mt-2 text-xs text-gray-500">
          Tip: generate audio in{" "}
          <Link href="/tts" className="text-pink-500 hover:underline">
            Text to Speech
          </Link>{" "}
          or{" "}
          <Link href="/clone" className="text-pink-500 hover:underline">
            Voice Cloning
          </Link>
          , download it, and use it here.
        </p>
        {audioUrl && <audio src={audioUrl} controls className="mt-3 w-full" />}

        <button
          onClick={run}
          disabled={!face || !audio || phase === "working"}
          className="mt-6 rounded-md bg-gradient-to-r from-pink-500 to-purple-500 px-5 py-2 text-sm font-medium text-white shadow-sm transition hover:shadow-md disabled:opacity-40"
        >
          {phase === "working" ? "Syncing…" : "Generate lip-synced video"}
        </button>

        {phase === "working" && (
          <p className="mt-3 text-sm text-amber-600">
            Working… lip-sync runs on CPU, so this takes a bit
            {elapsed > 0 ? ` (${elapsed}s)` : ""}. Larger/longer clips take
            longer.
          </p>
        )}
        {phase === "error" && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>

      {phase === "done" && resultUrl && (
        <section className="mt-8">
          <h2 className="mb-3 text-lg font-medium">Result</h2>
          <video src={resultUrl} controls autoPlay className="w-full rounded-lg" />
          <div className="mt-3">
            <a
              href={resultUrl}
              download="guava-lipsync.mp4"
              className="inline-block rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:border-pink-400 hover:text-pink-500 dark:border-gray-700"
            >
              Download .mp4
            </a>
          </div>
        </section>
      )}
    </main>
  );
}
