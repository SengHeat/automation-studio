/** Typed helpers for all FastAPI endpoints. */

const BASE = typeof window !== "undefined" ? "" : "http://localhost:8000";

export type SseEvent =
  | { log: string; done?: false }
  | { done: true; result?: Record<string, unknown> }
  | { error: string };

// ── Config ────────────────────────────────────────────────────────────────────

export interface AppConfig {
  voice_presets: string[];
  voice_styles: string[];
  genres: string[];
  emotions: string[];
  languages: string[];
  resolutions: string[];
  effect_styles: string[];
  subtitle_positions: string[];
  logo_corners: string[];
  defaults: Record<string, unknown>;
}

export async function fetchConfig(): Promise<AppConfig> {
  const r = await fetch(`${BASE}/api/config`);
  if (!r.ok) throw new Error("Failed to fetch config");
  return r.json();
}

// ── Jobs / SSE ────────────────────────────────────────────────────────────────

export function streamJob(
  jobId: string,
  onLog: (msg: string) => void,
  onDone: (result?: Record<string, unknown>) => void,
  onError?: (msg: string) => void,
) {
  const es = new EventSource(`${BASE}/api/jobs/${jobId}/stream`);
  es.onmessage = (e) => {
    const data: SseEvent = JSON.parse(e.data);
    if ("error" in data) {
      onError?.(data.error);
      es.close();
    } else if ("done" in data && data.done) {
      onDone(data.result);
      es.close();
    } else if ("log" in data) {
      onLog(data.log);
    }
  };
  es.onerror = () => {
    onError?.("Connection lost");
    es.close();
  };
  return () => es.close();
}

// ── Story ─────────────────────────────────────────────────────────────────────

export async function startGenerateStory(body: {
  title: string; premise?: string; genre?: string;
  duration_minutes?: number; segment_count?: number;
  language?: string; output_path?: string;
}): Promise<string> {
  const r = await fetch(`${BASE}/api/story/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  return d.job_id;
}

export async function startConvertText(body: {
  text: string; genre?: string; language?: string;
  segment_count?: number; output_path?: string;
}): Promise<string> {
  const r = await fetch(`${BASE}/api/story/convert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  return d.job_id;
}

// ── Voice / Video ─────────────────────────────────────────────────────────────

export async function startVoice(form: FormData): Promise<string> {
  const r = await fetch(`${BASE}/api/voice`, { method: "POST", body: form });
  const d = await r.json();
  return d.job_id;
}

export async function startVideo(form: FormData): Promise<string> {
  const r = await fetch(`${BASE}/api/video`, { method: "POST", body: form });
  const d = await r.json();
  return d.job_id;
}

export async function fetchTestStoryFixture(): Promise<File> {
  const r = await fetch(`${BASE}/api/fixture/test-story`);
  if (!r.ok) throw new Error("Test fixture not found on server");
  const blob = await r.blob();
  return new File([blob], "test_story_home_invasion.json", { type: "application/json" });
}

// ── ETA ───────────────────────────────────────────────────────────────────────

export async function estimateEta(body: {
  text?: string; json_path?: string; wpm?: number; cpm?: number;
}): Promise<{ breakdown: string; total: string }> {
  const r = await fetch(`${BASE}/api/eta`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

// ── SRT / Chapters ────────────────────────────────────────────────────────────

export async function exportSrt(voice_out: string, json_path?: string) {
  const r = await fetch(`${BASE}/api/srt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voice_out, json_path }),
  });
  return r.json() as Promise<{ status: string; file_url: string | null }>;
}

export async function generateChapters(voice_out: string, json_path?: string) {
  const r = await fetch(`${BASE}/api/chapters`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voice_out, json_path }),
  });
  return r.json() as Promise<{ status: string; chapters: string }>;
}

// ── Preview Segment ───────────────────────────────────────────────────────────

export async function startPreviewSegment(form: FormData): Promise<string> {
  const r = await fetch(`${BASE}/api/preview-segment`, { method: "POST", body: form });
  const d = await r.json();
  return d.job_id;
}

// ── Presets ───────────────────────────────────────────────────────────────────

export async function savePreset(data: Record<string, unknown>) {
  const r = await fetch(`${BASE}/api/preset/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return r.json() as Promise<{ status: string }>;
}

export async function loadPreset(path: string) {
  const r = await fetch(`${BASE}/api/preset/load?path=${encodeURIComponent(path)}`);
  if (!r.ok) return null;
  return r.json();
}

// ── History ───────────────────────────────────────────────────────────────────

export async function scanHistory(folder: string) {
  const r = await fetch(`${BASE}/api/history/scan?folder=${encodeURIComponent(folder)}`);
  return r.json() as Promise<{ files: Array<{ path: string; filename: string; title: string; language: string }> }>;
}

export async function previewHistoryFile(path: string) {
  const r = await fetch(`${BASE}/api/history/preview?path=${encodeURIComponent(path)}`);
  return r.json();
}

export async function deleteHistoryFile(path: string) {
  const r = await fetch(`${BASE}/api/history/file?path=${encodeURIComponent(path)}`, { method: "DELETE" });
  return r.json() as Promise<{ status: string }>;
}

// ── YouTube ───────────────────────────────────────────────────────────────────

export async function startYoutubeAuth(client_secrets_path: string, token_path: string): Promise<string> {
  const r = await fetch(`${BASE}/api/youtube/authorize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_secrets_path, token_path }),
  });
  const d = await r.json();
  return d.job_id;
}

export async function startYoutubeUpload(body: {
  video_path: string; title?: string; description?: string;
  tags?: string; privacy?: string; client_secrets_path: string; token_path?: string;
}): Promise<string> {
  const r = await fetch(`${BASE}/api/youtube/upload`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  return d.job_id;
}

// ── Queue ─────────────────────────────────────────────────────────────────────

export async function scanQueue(folder: string) {
  const r = await fetch(`${BASE}/api/queue/scan?folder=${encodeURIComponent(folder)}`);
  return r.json();
}

export async function clearQueue() {
  const r = await fetch(`${BASE}/api/queue/clear`, { method: "POST" });
  return r.json();
}

export async function startQueueRun(body: Record<string, unknown>): Promise<string> {
  const r = await fetch(`${BASE}/api/queue/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  return d.job_id;
}

export async function stopQueue(jobId: string) {
  const r = await fetch(`${BASE}/api/queue/stop/${jobId}`, { method: "POST" });
  return r.json();
}

// ── Files ─────────────────────────────────────────────────────────────────────

export function fileDownloadUrl(path: string) {
  return `${BASE}/api/files/download?path=${encodeURIComponent(path)}`;
}
