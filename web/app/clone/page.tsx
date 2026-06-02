"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  getCloneLanguages,
  startClone,
  waitForClone,
  type LanguageMap,
} from "@/lib/clone";
import { DownloadButtons } from "@/components/DownloadButtons";

type Phase = "idle" | "working" | "done" | "error";

const MAX_CHARS = 3000;

// Phonetically rich passages to read while recording the reference. Covering a
// wide range of sounds gives the cloning model a fuller picture of the voice,
// which improves the match. These are classics designed for exactly this.
const SAMPLE_SCRIPTS = [
  {
    name: "Rainbow Passage",
    text: "When the sunlight strikes raindrops in the air, they act as a prism and form a rainbow. The rainbow is a division of white light into many beautiful colors. These take the shape of a long round arch, with its path high above, and its two ends apparently beyond the horizon.",
  },
  {
    name: "Quick & varied",
    text: "The quick brown fox jumps over the lazy dog. She sells seashells by the seashore. How much wood would a woodchuck chuck? My voice is my own, clear and natural, with my real accent and rhythm as I speak these everyday words.",
  },
  {
    name: "Numbers & names",
    text: "On Monday the third, we drove about ninety-five miles to visit Aunt Priya and Uncle James. The weather was bright and warm, around seventy degrees, and the whole journey took just over two hours, with a short stop for coffee.",
  },
];

export default function ClonePage() {
  // consent gate — nothing clones until this is checked
  const [consent, setConsent] = useState(false);

  const [file, setFile] = useState<Blob | null>(null);
  const [fileName, setFileName] = useState("");
  const [refUrl, setRefUrl] = useState("");
  const [scriptIdx, setScriptIdx] = useState(0); // which sample script to read
  const [showScript, setShowScript] = useState(false);
  const [text, setText] = useState("");
  const [languages, setLanguages] = useState<LanguageMap>({});
  const [language, setLanguage] = useState("en");

  const [mode, setMode] = useState<"smooth" | "match">("smooth");
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [resultUrl, setResultUrl] = useState("");
  const [similarity, setSimilarity] = useState<number | null>(null);
  const [error, setError] = useState("");

  // recording
  const [recording, setRecording] = useState(false);
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [micId, setMicId] = useState("");
  const [level, setLevel] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const meterRef = useRef<{ ctx: AudioContext; raf: number } | null>(null);

  useEffect(() => {
    getCloneLanguages()
      .then(setLanguages)
      .catch(() => setLanguages({ en: "English" }));
  }, []);

  // Enumerate microphones (filtering Chrome's virtual default duplicates) so
  // the user can choose the right input device.
  useEffect(() => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    const refresh = () =>
      navigator.mediaDevices
        .enumerateDevices()
        .then((devs) =>
          setMics(
            devs.filter(
              (d) =>
                d.kind === "audioinput" &&
                d.deviceId !== "default" &&
                d.deviceId !== "communications",
            ),
          ),
        )
        .catch(() => {});
    refresh();
    navigator.mediaDevices.addEventListener?.("devicechange", refresh);
    return () =>
      navigator.mediaDevices.removeEventListener?.("devicechange", refresh);
  }, []);

  useEffect(() => {
    if (!file) {
      setRefUrl("");
      return;
    }
    const url = URL.createObjectURL(file);
    setRefUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function pickFile(f: File | null) {
    setFile(f);
    setFileName(f?.name ?? "");
    setPhase("idle");
    setResultUrl("");
  }

  // Live input-level meter from the mic stream.
  function startMeter(stream: MediaStream) {
    try {
      const Ctx =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      const ctx = new Ctx();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const v of data) {
          const d = (v - 128) / 128;
          sum += d * d;
        }
        setLevel(Math.min(1, Math.sqrt(sum / data.length) * 3));
        const raf = requestAnimationFrame(tick);
        if (meterRef.current) meterRef.current.raf = raf;
      };
      const raf = requestAnimationFrame(tick);
      meterRef.current = { ctx, raf };
    } catch {
      // meter is optional
    }
  }

  function stopMeter() {
    if (meterRef.current) {
      cancelAnimationFrame(meterRef.current.raf);
      void meterRef.current.ctx.close();
      meterRef.current = null;
    }
    setLevel(0);
  }

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError(
        "Recording needs a secure context (https or localhost) and a supported browser.",
      );
      return;
    }
    try {
      const constraints: MediaStreamConstraints = {
        audio: micId ? { deviceId: { exact: micId } } : true,
      };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);

      // Refresh labels now that permission is granted; remember the device used.
      navigator.mediaDevices
        .enumerateDevices()
        .then((devs) =>
          setMics(
            devs.filter(
              (d) =>
                d.kind === "audioinput" &&
                d.deviceId !== "default" &&
                d.deviceId !== "communications",
            ),
          ),
        )
        .catch(() => {});
      const usedId = stream.getAudioTracks()[0]?.getSettings().deviceId;
      if (usedId && !micId) setMicId(usedId);

      startMeter(stream);

      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        const blob = new Blob(chunksRef.current, {
          type: rec.mimeType || "audio/webm",
        });
        stream.getTracks().forEach((t) => t.stop());
        stopMeter();
        setRecording(false);
        if (blob.size === 0) {
          setError("Recording captured no audio. Check that the right mic is selected and not muted.");
          return;
        }
        setFile(blob);
        setFileName("reference.webm");
        setPhase("idle");
        setResultUrl("");
        setError("");
      };
      recorderRef.current = rec;
      rec.start(250);
      setError("");
      setRecording(true);
    } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      const msg =
        name === "NotAllowedError"
          ? "Microphone permission was denied. Allow mic access in your browser's site settings, then try again."
          : name === "NotFoundError"
            ? "No microphone was found. Check that one is connected and enabled."
            : name === "NotReadableError"
              ? "The microphone is in use by another app. Close it and try again."
              : `Couldn't access the microphone${name ? ` (${name})` : ""}.`;
      setError(msg);
    }
  }

  async function run() {
    if (!file || !text.trim() || !consent) return;
    setPhase("working");
    setError("");
    setResultUrl("");
    setSimilarity(null);
    setElapsed(0);
    setProgress({ done: 0, total: 0 });
    try {
      const jobId = await startClone(
        file,
        text,
        language,
        mode,
        fileName || "reference.wav",
      );
      const { url, similarity: sim } = await waitForClone(
        jobId,
        (sec, done, total) => {
          setElapsed(sec);
          setProgress({ done, total });
        },
      );
      setResultUrl(url);
      setSimilarity(sim);
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setPhase("error");
    }
  }

  const canClone = consent && !!file && !!text.trim() && phase !== "working";

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <Link href="/" className="text-sm text-gray-500 hover:text-pink-500">
        ← Guava
      </Link>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight">Voice Cloning</h1>
      <p className="mt-2 text-gray-600 dark:text-gray-400">
        Provide a short voice sample and some text — the cloned voice will speak
        it back. Zero-shot, no training.
      </p>

      {/* Consent gate */}
      <div className="mt-6 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm dark:border-amber-800/60 dark:bg-amber-950/30">
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            className="mt-0.5 accent-pink-500"
          />
          <span className="text-amber-900 dark:text-amber-200">
            I confirm this voice is mine, or I have the explicit permission of
            the person it belongs to. Cloning someone&apos;s voice without consent
            may be illegal.
          </span>
        </label>
      </div>

      {/* Everything below is disabled until consent is given */}
      <div
        className={`mt-6 rounded-xl border border-gray-200 p-6 dark:border-gray-800 ${
          consent ? "" : "pointer-events-none opacity-40"
        }`}
      >
        <p className="mb-2 text-sm font-medium">1. Reference voice</p>
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="file"
            accept="audio/*"
            onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
            className="block flex-1 text-sm file:mr-4 file:rounded-md file:border-0 file:bg-pink-500 file:px-4 file:py-2 file:text-white hover:file:bg-pink-600"
          />
          <button
            onClick={toggleRecording}
            className={`flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium transition ${
              recording
                ? "bg-red-500 text-white shadow-md shadow-red-500/30"
                : "bg-gradient-to-r from-pink-500 to-purple-500 text-white shadow-sm hover:shadow-md"
            }`}
          >
            {recording ? "Stop" : "🎙️ Record"}
          </button>
        </div>

        {/* Sample script: reading a phonetically rich passage gives the model a
            fuller picture of the voice, improving the clone match. */}
        <div className="mt-3">
          <button
            onClick={() => setShowScript((v) => !v)}
            className="text-xs text-pink-500 hover:underline"
          >
            {showScript ? "Hide sample script" : "✨ Need something to read? Use a sample script"}
          </button>
          {showScript && (
            <div className="mt-2 rounded-lg border border-gray-200 p-3 dark:border-gray-800">
              <div className="mb-2 flex flex-wrap gap-1.5">
                {SAMPLE_SCRIPTS.map((s, i) => (
                  <button
                    key={s.name}
                    onClick={() => setScriptIdx(i)}
                    className={`rounded-full px-2.5 py-1 text-xs transition ${
                      scriptIdx === i
                        ? "bg-pink-500 text-white"
                        : "border border-gray-300 text-gray-500 hover:border-pink-400 dark:border-gray-700"
                    }`}
                  >
                    {s.name}
                  </button>
                ))}
              </div>
              <p className="text-sm leading-relaxed text-gray-700 dark:text-gray-300">
                {SAMPLE_SCRIPTS[scriptIdx].text}
              </p>
              <p className="mt-2 text-xs text-gray-400">
                Press Record and read this aloud naturally in your own accent for
                the best clone. Covers a wide range of sounds.
              </p>
            </div>
          )}
        </div>

        {/* Mic picker (only with 2+ mics) + live level while recording */}
        {(mics.length > 1 || recording) && (
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
            {mics.length > 1 && (
              <label className="flex items-center gap-2">
                <span className="text-gray-500">Mic</span>
                <select
                  value={micId}
                  onChange={(e) => setMicId(e.target.value)}
                  disabled={recording}
                  className="max-w-56 rounded-md border border-gray-300 bg-transparent px-2 py-1 disabled:opacity-50 dark:border-gray-700"
                >
                  <option value="">System default</option>
                  {mics.map((m, i) => (
                    <option key={m.deviceId} value={m.deviceId}>
                      {m.label || `Microphone ${i + 1}`}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {recording && (
              <div className="flex items-center gap-2">
                <span className="text-gray-500">Level</span>
                <div className="h-2 w-32 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-800">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-green-400 to-pink-500 transition-[width] duration-75"
                    style={{ width: `${Math.round(level * 100)}%` }}
                  />
                </div>
                {level < 0.02 && (
                  <span className="text-amber-600">no sound — check mic</span>
                )}
              </div>
            )}
          </div>
        )}

        <details className="mt-2 text-xs text-gray-500">
          <summary className="cursor-pointer hover:text-pink-500">
            Tips for a better clone (accent, clarity)
          </summary>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>
              Use <strong>15–30 seconds</strong> of clear speech — longer, cleaner
              samples capture your accent far better than a short clip.
            </li>
            <li>
              Record in a <strong>quiet room</strong>, close to the mic, no music
              or background noise.
            </li>
            <li>
              Speak naturally in <strong>your own accent</strong> — the clone
              copies the accent in your sample, so a thin or noisy clip makes it
              drift toward a generic accent.
            </li>
            <li>
              Keep the script plain — drop quotes, stage directions, and notes
              like &ldquo;(pause here)&rdquo;; the model reads everything literally.
            </li>
          </ul>
        </details>
        {refUrl && (
          <audio
            src={refUrl}
            controls
            onLoadedMetadata={(e) => {
              // Fix Chrome's duration:Infinity bug for recorded webm blobs.
              const a = e.target as HTMLAudioElement;
              if (a.duration === Infinity) {
                a.currentTime = 1e101;
                a.ontimeupdate = () => {
                  a.ontimeupdate = null;
                  a.currentTime = 0;
                };
              }
            }}
            className="mt-3 w-full"
          />
        )}

        <p className="mt-6 mb-2 text-sm font-medium">2. What should it say?</p>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX_CHARS))}
          placeholder="Type the words the cloned voice should speak…"
          className="h-28 w-full rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm dark:border-gray-800 dark:bg-gray-900"
        />
        <div className="mt-1 flex items-center justify-between text-xs text-gray-400">
          <label className="flex items-center gap-2">
            <span>Language</span>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="rounded-md border border-gray-300 bg-transparent px-2 py-1 dark:border-gray-700"
            >
              {Object.entries(languages).map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <span>
            {text.length} / {MAX_CHARS}
          </span>
        </div>
        <p className="mt-1 text-xs text-gray-400">
          On CPU, longer text takes longer — it generates sentence by sentence
          so you can watch the progress.
        </p>

        {/* Mode: trade off smoothness vs. voice match */}
        <p className="mt-6 mb-2 text-sm font-medium">3. Cloning mode</p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            onClick={() => setMode("smooth")}
            className={`flex-1 rounded-lg border p-3 text-left text-sm transition ${
              mode === "smooth"
                ? "border-pink-400 bg-pink-50 dark:bg-pink-950/20"
                : "border-gray-200 hover:border-pink-300 dark:border-gray-800"
            }`}
          >
            <span className="font-medium">✨ Smoothest</span>
            <span className="mt-1 block text-xs text-gray-500">
              Natural flow, clear speech. Voice match is moderate.
            </span>
          </button>
          <button
            onClick={() => setMode("match")}
            className={`flex-1 rounded-lg border p-3 text-left text-sm transition ${
              mode === "match"
                ? "border-pink-400 bg-pink-50 dark:bg-pink-950/20"
                : "border-gray-200 hover:border-pink-300 dark:border-gray-800"
            }`}
          >
            <span className="font-medium">🎯 Closest match</span>
            <span className="mt-1 block text-xs text-gray-500">
              Stronger voice match. Slightly less smooth, slower.
            </span>
          </button>
        </div>

        <button
          onClick={run}
          disabled={!canClone}
          className="mt-5 rounded-md bg-gradient-to-r from-pink-500 to-purple-500 px-5 py-2 text-sm font-medium text-white shadow-sm transition hover:shadow-md disabled:opacity-40"
        >
          {phase === "working" ? "Cloning…" : "Clone voice"}
        </button>

        {phase === "working" && (
          <div className="mt-4">
            {/* Sentence-by-sentence progress. total stays 0 until the first
                chunk reports, e.g. during model download on the first run. */}
            {progress.total > 0 ? (
              <>
                <div className="mb-1 flex items-center justify-between text-xs text-gray-500">
                  <span>
                    Generating sentence {progress.done} of {progress.total}
                  </span>
                  <span>{elapsed}s</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-800">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-pink-500 to-purple-500 transition-[width] duration-300"
                    style={{
                      width: `${Math.round((progress.done / progress.total) * 100)}%`,
                    }}
                  />
                </div>
              </>
            ) : (
              <p className="text-sm text-amber-600">
                Preparing… the first run downloads the model, which can take a
                couple of minutes{elapsed > 0 ? ` (${elapsed}s)` : ""}.
              </p>
            )}
          </div>
        )}
        {phase === "error" && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>

      {phase === "done" && resultUrl && (
        <section className="mt-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-medium">Cloned result</h2>
            {similarity !== null && <SimilarityBadge score={similarity} />}
          </div>
          <audio src={resultUrl} controls autoPlay className="w-full" />
          <div className="mt-4">
            <DownloadButtons audioUrl={resultUrl} baseName="guava-clone" />
          </div>
        </section>
      )}
    </main>
  );
}

// Shows the speaker-similarity score (0-1) with a plain-language label, so the
// user knows how close the clone is to their voice.
function SimilarityBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const { label, color } =
    score >= 0.85
      ? { label: "Excellent match", color: "text-green-600" }
      : score >= 0.75
        ? { label: "Strong match", color: "text-green-600" }
        : score >= 0.65
          ? { label: "Moderate match", color: "text-amber-600" }
          : { label: "Weak match", color: "text-red-600" };
  return (
    <span
      className="text-xs"
      title="How closely the clone matches your reference voice (speaker-embedding similarity)"
    >
      <span className="text-gray-400">Voice match: </span>
      <span className={`font-medium ${color}`}>
        {pct}% · {label}
      </span>
    </span>
  );
}
