"use client";
import { useState } from "react";
import Link from "next/link";
import { scanHistory, previewHistoryFile, deleteHistoryFile } from "@/lib/api";

interface FileEntry { path: string; filename: string; title: string; language: string }

export default function HistoryPage() {
  const [folder, setFolder] = useState(".");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [selected, setSelected] = useState<FileEntry | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function scan() {
    setBusy(true);
    const r = await scanHistory(folder);
    setFiles(r.files);
    setStatus(`✅ Found ${r.files.length} file(s).`);
    setBusy(false);
  }

  async function select(file: FileEntry) {
    setSelected(file);
    const r = await previewHistoryFile(file.path);
    setPreview(r);
  }

  async function del() {
    if (!selected) return;
    if (!confirm(`Delete ${selected.filename}?`)) return;
    const r = await deleteHistoryFile(selected.path);
    setStatus(r.status);
    setSelected(null);
    setPreview(null);
    await scan();
  }

  return (
    <main className="max-w-5xl mx-auto p-8">
      <h1 className="text-2xl font-bold mb-1">📂 History & File Manager</h1>
      <p className="text-gray-400 text-sm mb-6">Browse and manage saved Story JSON files.</p>

      <div className="flex gap-2 mb-4">
        <input className="input flex-1" value={folder} onChange={e => setFolder(e.target.value)}
          placeholder="./stories" />
        <button onClick={scan} disabled={busy} className="btn-primary">🔍 Scan</button>
      </div>
      {status && <p className="text-xs text-gray-400 mb-4">{status}</p>}

      <div className="grid md:grid-cols-[280px_1fr] gap-6">
        <div className="space-y-1">
          {files.length === 0 && <p className="text-gray-600 text-sm">No files yet.</p>}
          {files.map(f => (
            <button key={f.path} onClick={() => select(f)}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                selected?.path === f.path
                  ? "bg-blue-700 text-white"
                  : "text-gray-300 hover:bg-gray-800"}`}>
              <span className="font-medium block truncate">{f.title}</span>
              <span className="text-xs text-gray-400">{f.filename} · {f.language}</span>
            </button>
          ))}
        </div>

        <div>
          {preview && (
            <>
              <div className="mb-3 text-sm text-gray-300 space-y-0.5">
                <p><span className="text-gray-500">File:</span> {preview.filename as string}</p>
                <p><span className="text-gray-500">Title:</span> {preview.title as string}</p>
                <p><span className="text-gray-500">Segments:</span> {preview.segment_count as number} · {preview.language as string}</p>
              </div>
              <div className="flex gap-2 mb-3">
                <Link href="/studio" className="btn-primary text-sm">
                  📤 Send to Studio
                </Link>
                <button onClick={del} className="btn-danger text-sm">🗑 Delete</button>
              </div>
              <details open>
                <summary className="text-xs text-gray-400 cursor-pointer mb-1">JSON Preview</summary>
                <pre className="max-h-80 overflow-y-auto rounded-lg border border-gray-800 bg-gray-950
                                p-3 text-xs text-green-300 font-mono">
                  {JSON.stringify(preview.json, null, 2)}
                </pre>
              </details>
            </>
          )}
          {!preview && <p className="text-gray-600 text-sm">Select a file to preview.</p>}
        </div>
      </div>
    </main>
  );
}
