"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  transcribe,
  getLanguages,
  type SttResult,
  type LanguageMap,
} from "@/lib/stt";

type Phase = "idle" | "working" | "warming" | "done" | "error";
type View = "segments" | "plain";

// 75.4 -> "1:15"
function fmtClock(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

export default function SttPage() {
  const [file, setFile] = useState<Blob | null>(null);
  const [fileName, setFileName] = useState("");
  const [audioUrl, setAudioUrl] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<SttResult | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("segments");
  const [currentTime, setCurrentTime] = useState(0);

  // options
  const [languages, setLanguages] = useState<LanguageMap>({});
  const [autoDetect, setAutoDetect] = useState(true); // let the AI detect language
  const [language, setLanguage] = useState("en"); // used only when autoDetect is off
  const [translate, setTranslate] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);

  // recording
  const [recording, setRecording] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const warmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const segRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const scrollBoxRef = useRef<HTMLDivElement | null>(null); // transcript container
  const activeIdx = useRef(-1);

  // Load the supported-languages list once.
  useEffect(() => {
    getLanguages()
      .then(setLanguages)
      .catch(() => setLanguages({ en: "English" }));
  }, []);

  // Make the current file playable.
  useEffect(() => {
    if (!file) {
      setAudioUrl("");
      return;
    }
    const url = URL.createObjectURL(file);
    setAudioUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function pickFile(f: File | null) {
    setFile(f);
    setFileName(f?.name ?? "");
    setPhase("idle");
    setResult(null);
    setError("");
  }

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data.size && chunksRef.current.push(e.data);
      rec.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setFile(blob);
        setFileName("recording.webm");
        setPhase("idle");
        setResult(null);
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
      };
      recorderRef.current = rec;
      rec.start();
      setRecording(true);
    } catch {
      setError("Couldn't access the microphone. Check browser permissions.");
    }
  }

  async function run() {
    if (!file) return;
    setPhase("working");
    setError("");
    setResult(null);
    warmTimer.current = setTimeout(() => setPhase("warming"), 4000);

    try {
      const res = await transcribe(file, {
        // "auto" tells the client to let Whisper detect the language
        language: autoDetect ? "auto" : language,
        task: translate ? "translate" : "transcribe",
        filename: fileName || "audio",
      });
      setResult(res);
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setPhase("error");
    } finally {
      if (warmTimer.current) clearTimeout(warmTimer.current);
    }
  }

  function seek(seconds: number) {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = seconds;
    void a.play();
  }

  // Autoscroll: keep the active segment centered *inside the transcript box*
  // only — we adjust the box's own scrollTop instead of scrollIntoView, which
  // would scroll the whole page.
  function onTimeUpdate(t: number) {
    setCurrentTime(t);
    if (!autoScroll || !result) return;
    const idx = result.segments.findIndex((s) => t >= s.start && t < s.end);
    if (idx === -1 || idx === activeIdx.current) return;
    activeIdx.current = idx;

    const box = scrollBoxRef.current;
    const el = segRefs.current[idx];
    if (!box || !el) return;
    // Position of the segment relative to the box's current scroll, then center
    // it. getBoundingClientRect avoids offsetTop's positioned-ancestor pitfall.
    const offsetWithinBox =
      el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
    const target = offsetWithinBox - box.clientHeight / 2 + el.clientHeight / 2;
    box.scrollTo({ top: target, behavior: "smooth" });
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
        Upload or record audio, play it back, and read the transcript with
        timestamps to check accuracy.
      </p>

      <div className="mt-8 rounded-xl border border-gray-200 p-6 dark:border-gray-800">
        {/* Upload + speak */}
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="file"
            accept="audio/*,video/*"
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
            {recording ? (
              <>
                <span className="flex items-end gap-0.5">
                  <span className="h-3 w-0.5 animate-pulse bg-white" />
                  <span className="h-4 w-0.5 animate-pulse bg-white [animation-delay:150ms]" />
                  <span className="h-2 w-0.5 animate-pulse bg-white [animation-delay:300ms]" />
                </span>
                Stop &amp; use
              </>
            ) : (
              <>
                <span>🎙️</span> Speak
              </>
            )}
          </button>
        </div>

        {/* Player */}
        {audioUrl && (
          <div className="mt-4">
            {fileName && <p className="mb-2 text-xs text-gray-500">{fileName}</p>}
            <audio
              ref={audioRef}
              src={audioUrl}
              controls
              onTimeUpdate={(e) =>
                onTimeUpdate((e.target as HTMLAudioElement).currentTime)
              }
              className="w-full"
            />
          </div>
        )}

        {/* Options */}
        <div className="mt-5 flex flex-wrap items-center gap-3 text-sm">
          <span className="text-xs font-medium tracking-wide text-gray-400 uppercase">
            Language
          </span>

          {/* Auto-detect is its own toggle — the AI figures out the language */}
          <button
            onClick={() => setAutoDetect((v) => !v)}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition ${
              autoDetect
                ? "bg-gradient-to-r from-pink-500 to-purple-500 text-white shadow-sm"
                : "border border-gray-300 text-gray-500 hover:border-pink-400 dark:border-gray-700"
            }`}
          >
            <span>✦</span> Auto-detect
          </button>

          {/* Manual language picker only matters when auto-detect is off */}
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            disabled={autoDetect}
            className="rounded-md border border-gray-300 bg-transparent px-2 py-1.5 text-sm disabled:opacity-40 dark:border-gray-700"
          >
            {Object.entries(languages)
              .filter(([code]) => code !== "auto")
              .map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
          </select>

          {/* Translate toggle, styled to match */}
          <button
            onClick={() => setTranslate((v) => !v)}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition ${
              translate
                ? "bg-gradient-to-r from-pink-500 to-purple-500 text-white shadow-sm"
                : "border border-gray-300 text-gray-500 hover:border-pink-400 dark:border-gray-700"
            }`}
            title="Output the transcript in English, whatever the spoken language"
          >
            <span>🌐</span> Translate to English
          </button>
        </div>

        {/* Generate */}
        <button
          onClick={run}
          disabled={!file || busy}
          className="mt-5 rounded-md bg-gray-900 px-5 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-gray-900"
        >
          {busy ? "Transcribing…" : translate ? "Translate" : "Transcribe"}
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
            <h2 className="text-lg font-medium">
              {translate ? "Translation" : "Transcript"}
            </h2>
            <span className="text-xs text-gray-400">
              {result.language?.toUpperCase()} · {fmtClock(result.durationSec)}
            </span>
          </div>

          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div className="inline-flex rounded-md border border-gray-200 p-0.5 text-xs dark:border-gray-800">
              <button
                onClick={() => setView("segments")}
                className={`rounded px-3 py-1 ${
                  view === "segments"
                    ? "bg-pink-500 text-white"
                    : "text-gray-500 hover:text-pink-500"
                }`}
              >
                Timestamps
              </button>
              <button
                onClick={() => setView("plain")}
                className={`rounded px-3 py-1 ${
                  view === "plain"
                    ? "bg-pink-500 text-white"
                    : "text-gray-500 hover:text-pink-500"
                }`}
              >
                Plain text
              </button>
            </div>
            {view === "segments" && (
              <label className="flex items-center gap-2 text-xs text-gray-500">
                <input
                  type="checkbox"
                  checked={autoScroll}
                  onChange={(e) => setAutoScroll(e.target.checked)}
                  className="accent-pink-500"
                />
                Auto-scroll
              </label>
            )}
          </div>

          {view === "segments" ? (
            <div
              ref={scrollBoxRef}
              className="max-h-80 overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-800"
            >
              {result.segments.map((seg, i) => {
                const active = currentTime >= seg.start && currentTime < seg.end;
                return (
                  <button
                    key={i}
                    ref={(el) => {
                      segRefs.current[i] = el;
                    }}
                    onClick={() => seek(seg.start)}
                    className={`flex w-full gap-3 border-b border-gray-100 px-3 py-2 text-left text-sm last:border-0 hover:bg-pink-50 dark:border-gray-900 dark:hover:bg-gray-900 ${
                      active ? "bg-pink-50 dark:bg-gray-900" : ""
                    }`}
                  >
                    <span className="shrink-0 font-mono text-xs text-pink-500">
                      {fmtClock(seg.start)}
                    </span>
                    <span>{seg.text}</span>
                  </button>
                );
              })}
            </div>
          ) : (
            <textarea
              readOnly
              value={result.text}
              className="h-48 w-full rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm dark:border-gray-800 dark:bg-gray-900"
            />
          )}

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
