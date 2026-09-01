"use client";
import { useState } from "react";
import { BackButton } from "@/components/BackButton";
import { LogStream } from "@/components/LogStream";
import { startYoutubeAuth, startYoutubeUpload } from "@/lib/api";

export default function YoutubePage() {
  const [authJobId, setAuthJobId] = useState<string | null>(null);
  const [uploadJobId, setUploadJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [secretsPath, setSecretsPath] = useState("");
  const [tokenPath, setTokenPath] = useState("youtube_token.json");
  const [videoPath, setVideoPath] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [privacy, setPrivacy] = useState("private");

  async function authorize() {
    if (!secretsPath) { alert("Enter path to client_secrets.json"); return; }
    setBusy(true);
    const jid = await startYoutubeAuth(secretsPath, tokenPath);
    setAuthJobId(jid);
  }

  async function upload() {
    if (!videoPath || !secretsPath) { alert("Fill in video path and secrets path."); return; }
    setBusy(true);
    const jid = await startYoutubeUpload({
      video_path: videoPath, title, description, tags, privacy,
      client_secrets_path: secretsPath, token_path: tokenPath,
    });
    setUploadJobId(jid);
  }

  return (
    <main className="max-w-5xl mx-auto p-8">
      <BackButton />
      <h1 className="text-2xl font-bold mb-1">📺 YouTube Upload</h1>
      <p className="text-gray-400 text-sm mb-6">
        Requires a <strong>client_secrets.json</strong> from Google Cloud Console (YouTube Data API v3).
      </p>

      <div className="grid md:grid-cols-2 gap-8">
        {/* Left: form */}
        <div className="space-y-4">
          <div>
            <label className="label">client_secrets.json path</label>
            <input className="input" value={secretsPath} onChange={e => setSecretsPath(e.target.value)}
              placeholder="/path/to/client_secrets.json" />
          </div>
          <div>
            <label className="label">Token save path</label>
            <input className="input" value={tokenPath} onChange={e => setTokenPath(e.target.value)} />
          </div>
          <button onClick={authorize} disabled={busy} className="btn-secondary w-full">
            🔐 Authorize YouTube
          </button>

          <hr className="border-gray-800" />

          <div>
            <label className="label">Video file path</label>
            <input className="input" value={videoPath} onChange={e => setVideoPath(e.target.value)}
              placeholder="/path/to/output.mp4" />
          </div>
          <div>
            <label className="label">Title</label>
            <input className="input" value={title} onChange={e => setTitle(e.target.value)}
              placeholder="My Horror Story" />
          </div>
          <div>
            <label className="label">Description</label>
            <textarea className="input" rows={4} value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Generated with Automation Studio..." />
          </div>
          <div>
            <label className="label">Tags (comma-separated)</label>
            <input className="input" value={tags} onChange={e => setTags(e.target.value)}
              placeholder="horror, narration, creepy" />
          </div>
          <div>
            <label className="label">Privacy</label>
            <select className="input" value={privacy} onChange={e => setPrivacy(e.target.value)}>
              <option>private</option>
              <option>unlisted</option>
              <option>public</option>
            </select>
          </div>
          <button onClick={upload} disabled={busy} className="btn-primary w-full">
            📤 Upload to YouTube
          </button>
        </div>

        {/* Right: logs */}
        <div className="space-y-4">
          {authJobId && (
            <>
              <p className="text-xs text-gray-400 font-semibold">Authorization log</p>
              <LogStream jobId={authJobId} onDone={() => setBusy(false)} />
            </>
          )}
          {uploadJobId && (
            <>
              <p className="text-xs text-gray-400 font-semibold mt-4">Upload log</p>
              <LogStream jobId={uploadJobId} onDone={() => setBusy(false)} />
            </>
          )}
        </div>
      </div>
    </main>
  );
}
