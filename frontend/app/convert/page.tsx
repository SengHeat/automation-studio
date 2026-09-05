"use client";
import { useEffect, useState } from "react";
import { LogStream } from "@/components/LogStream";
import { fetchConfig, startConvertText, type AppConfig } from "@/lib/api";

export default function ConvertPage() {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [text, setText] = useState("");
  const [genre, setGenre] = useState("Horror");
  const [language, setLanguage] = useState("English");
  const [segments, setSegments] = useState(5);
  const [outputPath, setOutputPath] = useState("converted_story.json");

  useEffect(() => { fetchConfig().then(setCfg); }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    const jid = await startConvertText({ text, genre, language,
      segment_count: segments, output_path: outputPath });
    setJobId(jid);
  }

  return (
    <main className="max-w-5xl mx-auto p-8">
      <h1 className="text-2xl font-bold mb-1">📝 Plain Text → Story JSON</h1>
      <p className="text-gray-400 text-sm mb-6">Claude structures your written story into the segment JSON format verbatim.</p>

      <form onSubmit={submit} className="grid md:grid-cols-2 gap-6">
        <div className="space-y-4">
          <div>
            <label className="label">Plain text story *</label>
            <textarea className="input" rows={14} value={text} onChange={e => setText(e.target.value)}
              placeholder="Paste your written story here..." required />
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
          <div>
            <label className="label">Target segments: {segments}</label>
            <input type="range" min={3} max={12} step={1} value={segments}
              onChange={e => setSegments(+e.target.value)} className="w-full accent-blue-500" />
          </div>
          <div>
            <label className="label">Save JSON to</label>
            <input className="input" value={outputPath} onChange={e => setOutputPath(e.target.value)} />
          </div>
          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? "Converting…" : "📝 Convert to JSON"}
          </button>
        </div>

        <div>
          <LogStream jobId={jobId} onDone={() => setBusy(false)} />
        </div>
      </form>
    </main>
  );
}
