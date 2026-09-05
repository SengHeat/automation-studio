"use client";
import { useState } from "react";
import { LogStream } from "@/components/LogStream";
import { scanQueue, clearQueue, startQueueRun, stopQueue } from "@/lib/api";

interface QueueJob {
  json_path: string; effect_style: string;
  privacy: string; auto_upload: boolean; status: string;
}

export default function QueuePage() {
  const [folder, setFolder] = useState(".");
  const [jobs, setJobs] = useState<QueueJob[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const [effectStyle, setEffectStyle] = useState("Horror Cinematic");
  const [resolution, setResolution] = useState("1280x720");
  const [fps, setFps] = useState(20);
  const [crf, setCrf] = useState(18);
  const [voicePreset, setVoicePreset] = useState("Balanced Neutral");
  const [autoUpload, setAutoUpload] = useState(false);
  const [secretsPath, setSecretsPath] = useState("");
  const [tokenPath, setTokenPath] = useState("youtube_token.json");

  async function scan() {
    const r = await scanQueue(folder);
    setJobs(r.jobs || []);
    setStatus(`✅ Added ${r.added} file(s). Total: ${r.total}`);
  }

  async function clear() {
    await clearQueue();
    setJobs([]);
    setStatus("Queue cleared.");
  }

  async function run() {
    if (jobs.length === 0) { setStatus("❌ Queue is empty."); return; }
    setBusy(true);
    const jid = await startQueueRun({
      effect_style: effectStyle, resolution, fps, crf,
      voice_preset: voicePreset, auto_upload: autoUpload,
      client_secrets_path: secretsPath, token_path: tokenPath,
    });
    setJobId(jid);
  }

  async function stop() {
    if (!jobId) return;
    const r = await stopQueue(jobId);
    setStatus(r.status);
  }

  return (
    <main className="max-w-5xl mx-auto p-8">
      <h1 className="text-2xl font-bold mb-1">🚀 Batch Queue</h1>
      <p className="text-gray-400 text-sm mb-6">
        Scan a folder, then run all stories sequentially while you sleep.
      </p>

      <div className="flex gap-2 mb-4">
        <input className="input flex-1" value={folder} onChange={e => setFolder(e.target.value)}
          placeholder="./stories" />
        <button onClick={scan} className="btn-secondary">🔍 Scan & Add</button>
        <button onClick={clear} className="btn-danger">🗑 Clear</button>
      </div>
      {status && <p className="text-xs text-gray-400 mb-3">{status}</p>}

      {/* Job table */}
      {jobs.length > 0 && (
        <div className="mb-6 overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-xs text-gray-300">
            <thead className="bg-gray-900 text-gray-500">
              <tr>
                {["File","Effect","Privacy","Upload","Status"].map(h => (
                  <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.map((j, i) => (
                <tr key={i} className="border-t border-gray-800">
                  <td className="px-3 py-2 font-mono truncate max-w-[180px]">{j.json_path.split("/").pop()}</td>
                  <td className="px-3 py-2">{j.effect_style}</td>
                  <td className="px-3 py-2">{j.privacy}</td>
                  <td className="px-3 py-2">{j.auto_upload ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{j.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Settings */}
      <div className="grid md:grid-cols-2 gap-6 mb-6">
        <div className="space-y-3">
          <div>
            <label className="label">Effect style</label>
            <select className="input" value={effectStyle} onChange={e => setEffectStyle(e.target.value)}>
              {["Horror Cinematic","Blood Red","Black & White Dread","Natural Dark"].map(s =>
                <option key={s}>{s}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="label">Resolution</label>
              <select className="input" value={resolution} onChange={e => setResolution(e.target.value)}>
                <option>1280x720</option><option>1920x1080</option>
              </select>
            </div>
            <div>
              <label className="label">FPS: {fps}</label>
              <input type="range" min={12} max={30} step={1} value={fps}
                onChange={e => setFps(+e.target.value)} className="w-full accent-blue-500" />
            </div>
            <div>
              <label className="label">CRF: {crf}</label>
              <input type="range" min={18} max={28} step={1} value={crf}
                onChange={e => setCrf(+e.target.value)} className="w-full accent-blue-500" />
            </div>
          </div>
          <div>
            <label className="label">Voice preset</label>
            <input className="input" value={voicePreset} onChange={e => setVoicePreset(e.target.value)} />
          </div>
          <label className="check"><input type="checkbox" checked={autoUpload}
            onChange={e => setAutoUpload(e.target.checked)} /> Auto-upload to YouTube</label>
        </div>
        <div className="space-y-3">
          <div>
            <label className="label">client_secrets.json (for YouTube)</label>
            <input className="input" value={secretsPath} onChange={e => setSecretsPath(e.target.value)}
              placeholder="/path/to/client_secrets.json" />
          </div>
          <div>
            <label className="label">YouTube token path</label>
            <input className="input" value={tokenPath} onChange={e => setTokenPath(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="flex gap-3 mb-4">
        <button onClick={run} disabled={busy} className="btn-primary">▶ Run Queue</button>
        <button onClick={stop} disabled={!jobId} className="btn-secondary">⏹ Stop</button>
      </div>

      <LogStream jobId={jobId} onDone={() => setBusy(false)} />
    </main>
  );
}
