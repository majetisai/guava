import Link from "next/link";

const features = [
  {
    href: "/stt",
    title: "Speech to Text",
    blurb: "Upload audio, get an accurate transcript with SRT and VTT export.",
    status: "Live",
  },
  {
    href: "/tts",
    title: "Text to Speech",
    blurb: "Turn text into natural speech across a set of built-in voices.",
    status: "Live",
  },
  {
    href: "/clone",
    title: "Voice Cloning",
    blurb: "Clone a voice from a short sample — with a real consent flow.",
    status: "Planned",
  },
];

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-16">
      <p className="mb-3 text-sm font-medium tracking-widest text-pink-500 uppercase">
        Guava
      </p>
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
        A self-hosted voice toolkit.
      </h1>
      <p className="mt-4 max-w-xl text-lg text-gray-600 dark:text-gray-300">
        Speech-to-text, text-to-speech, and voice cloning — running on
        open-source models, not someone else&apos;s API.
      </p>

      <div className="mt-12 grid gap-4 sm:grid-cols-3">
        {features.map((f) => (
          <Link
            key={f.href}
            href={f.href}
            className="group rounded-xl border border-gray-200 p-5 transition hover:border-pink-400 hover:shadow-sm dark:border-gray-800"
          >
            <h2 className="font-medium group-hover:text-pink-500">{f.title}</h2>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              {f.blurb}
            </p>
            <span className="mt-4 inline-block text-xs text-gray-400">
              {f.status}
            </span>
          </Link>
        ))}
      </div>

      <p className="mt-12 text-sm text-gray-400">
        Built with Next.js, Supabase, and a FastAPI inference service.
      </p>
    </main>
  );
}
