"use client";
import { useEffect, useState } from "react";
import { BackButton } from "@/components/BackButton";
import { LogStream } from "@/components/LogStream";
import { fetchConfig, startGenerateStory, type AppConfig } from "@/lib/api";

export default function StoryPage() {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [title, setTitle] = useState("");
  const [premise, setPremise] = useState("");
  const [genre, setGenre] = useState("Horror");
  const [language, setLanguage] = useState("English");
  const [duration, setDuration] = useState(3);
  const [segments, setSegments] = useState(5);
  const [outputPath, setOutputPath] = useState("generated_story.json");

  useEffect(() => { fetchConfig().then(setCfg); }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    const jid = await startGenerateStory({ title, premise, genre, language,
      duration_minutes: duration, segment_count: segments, output_path: outputPath });
    setJobId(jid);
  }

  return (
    <main className="max-w-5xl mx-auto p-8">
      <BackButton />
      <h1 className="text-2xl font-bold mb-1">✍️ Generate Story</h1>
      <p className="text-gray-400 text-sm mb-6">AI creates a full story JSON from your title and premise.</p>

      <form onSubmit={submit} className="grid md:grid-cols-2 gap-6">
        <div className="space-y-4">
          <div>
            <label className="label">Story Title *</label>
            <input className="input" value={title} onChange={e => setTitle(e.target.value)}
              placeholder="e.g. The House on the Hill" required />
          </div>
          <div>
            <label className="label">Premise / Idea</label>
            <textarea className="input" rows={4} value={premise} onChange={e => setPremise(e.target.value)}
              placeholder="e.g. A family moves into an old house and discovers it has a dark history..." />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Genre</label>
              <select className="input" value={genre} onChange={e => setGenre(e.target.value)}>
                {cfg?.genres.map(g => <option key={g}>{g}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Language</label>
              <select className="input" value={language} onChange={e => setLanguage(e.target.value)}>
                {cfg?.languages.map(l => <option key={l}>{l}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Duration (min): {duration}</label>
              <input type="range" min={1} max={10} step={0.5} value={duration}
                onChange={e => setDuration(+e.target.value)} className="w-full accent-blue-500" />
            </div>
            <div>
              <label className="label">Segments: {segments}</label>
              <input type="range" min={3} max={12} step={1} value={segments}
                onChange={e => setSegments(+e.target.value)} className="w-full accent-blue-500" />
            </div>
          </div>
          <div>
            <label className="label">Save JSON to</label>
            <input className="input" value={outputPath} onChange={e => setOutputPath(e.target.value)} />
          </div>
          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? "Generating…" : "✨ Generate Story JSON"}
          </button>
        </div>

        <div>
          <LogStream jobId={jobId} onDone={() => setBusy(false)} />
        </div>
      </form>
    </main>
  );
}
