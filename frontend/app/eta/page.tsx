"use client";
import { useState } from "react";
import { BackButton } from "@/components/BackButton";
import { estimateEta } from "@/lib/api";

export default function EtaPage() {
  const [text, setText] = useState("");
  const [jsonPath, setJsonPath] = useState("");
  const [wpm, setWpm] = useState(130);
  const [cpm, setCpm] = useState(280);
  const [breakdown, setBreakdown] = useState("");
  const [total, setTotal] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const res = await estimateEta({ text, json_path: jsonPath || undefined, wpm, cpm });
    setBreakdown(res.breakdown);
    setTotal(res.total);
    setBusy(false);
  }

  return (
    <main className="max-w-5xl mx-auto p-8">
      <BackButton />
      <h1 className="text-2xl font-bold mb-1">⏱ ETA Duration Estimator</h1>
      <p className="text-gray-400 text-sm mb-6">Estimate how long a script will take to narrate at TTS pace.</p>

      <form onSubmit={submit} className="grid md:grid-cols-2 gap-6">
        <div className="space-y-4">
          <div>
            <label className="label">Paste plain text</label>
            <textarea className="input" rows={10} value={text} onChange={e => setText(e.target.value)}
              placeholder="Paste your script here..." />
          </div>
          <div>
            <label className="label">Or enter Story JSON path</label>
            <input className="input" value={jsonPath} onChange={e => setJsonPath(e.target.value)}
              placeholder="/path/to/story.json" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Words/min (Latin): {wpm}</label>
              <input type="range" min={80} max={200} step={5} value={wpm}
                onChange={e => setWpm(+e.target.value)} className="w-full accent-blue-500" />
            </div>
            <div>
              <label className="label">Chars/min (Khmer/CJK): {cpm}</label>
              <input type="range" min={150} max={500} step={10} value={cpm}
                onChange={e => setCpm(+e.target.value)} className="w-full accent-blue-500" />
            </div>
          </div>
          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? "Estimating…" : "⏱ Estimate Duration"}
          </button>
        </div>

        <div className="space-y-3">
          {total && (
            <div className="rounded-lg border border-blue-700 bg-blue-950/40 px-4 py-3 text-blue-200 font-semibold text-sm">
              {total}
            </div>
          )}
          {breakdown && (
            <pre className="h-96 overflow-y-auto rounded-lg border border-gray-800 bg-gray-950
                            p-3 text-xs text-gray-300 font-mono whitespace-pre">
              {breakdown}
            </pre>
          )}
          {!breakdown && !busy && (
            <div className="text-gray-600 text-sm mt-8">Results will appear here.</div>
          )}
        </div>
      </form>
    </main>
  );
}
