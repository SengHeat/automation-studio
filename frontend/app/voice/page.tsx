"use client";
import { useEffect, useRef, useState } from "react";
import { LogStream } from "@/components/LogStream";
import {
  fetchConfig, startVoice, exportSrt, generateChapters,
  startPreviewSegment, savePreset, loadPreset, type AppConfig,
} from "@/lib/api";
import { Mic, Settings2, Music, Wrench, Menu } from "lucide-react";
import { useSidebar } from "@/components/ui/Sidebar";
import { useNavigationGuard } from "@/lib/useNavigationGuard";

type Tab = "voice" | "advanced" | "audio" | "tools";

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "voice",    label: "Voice",    icon: <Mic size={12} /> },
  { id: "advanced", label: "Advanced", icon: <Settings2 size={12} /> },
  { id: "audio",    label: "Audio",    icon: <Music size={12} /> },
  { id: "tools",    label: "Tools",    icon: <Wrench size={12} /> },
];

function Section({ num, title, children }: { num: string; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/40 overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800/60">
        {num && <span className="text-xs font-mono text-gray-600 select-none">{num}</span>}
        <span className="text-sm font-semibold text-gray-200">{title}</span>
      </div>
      <div className="p-4 space-y-3">{children}</div>
    </div>
  );
}

// Fake waveform bars for visual preview
function Waveform({ playing }: { playing: boolean }) {
  const heights = [40, 65, 80, 55, 90, 70, 45, 85, 60, 75, 50, 88, 65, 72, 48, 82, 58, 68, 45, 78, 62, 55, 85, 70, 42];
  return (
    <div className="flex items-center gap-0.5 h-16">
      {heights.map((h, i) => (
        <div key={i}
          className={`flex-1 rounded-sm transition-opacity ${playing ? "opacity-100" : "opacity-60"}`}
          style={{
            height: `${h}%`,
            background: i < 8 ? "#3b82f6" : "#1e3a5f",
            animationDelay: `${i * 40}ms`,
          }}
        />
      ))}
    </div>
  );
}

interface SegmentRow { id: number; text: string; estSecs: number }

export default function VoicePage() {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [tab, setTab] = useState<Tab>("voice");
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [toolStatus, setToolStatus] = useState("");
  const [chapters, setChapters] = useState("");
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loadedFiles, setLoadedFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [segments, setSegments] = useState<SegmentRow[]>([]);

  const [voicePreset, setVoicePreset] = useState("Balanced Neutral");
  const [voiceStyle, setVoiceStyle] = useState("Balanced");
  const [cfgValue, setCfgValue] = useState(1.7);
  const [doNormalize, setDoNormalize] = useState(false);
  const [denoise, setDenoise] = useState(true);
  const [autoEmotion, setAutoEmotion] = useState(false);
  const [speakerLock, setSpeakerLock] = useState(true);
  const [maxWorkers, setMaxWorkers] = useState(2);
  const [bgSoundQuery, setBgSoundQuery] = useState("");
  const [bgPercent, setBgPercent] = useState(0.18);
  const [autoAmb, setAutoAmb] = useState(false);
  const [voiceOut, setVoiceOut] = useState("voice_final.mp3");
  const [segmentsOutput, setSegmentsOutput] = useState("segments_audio");
  const [segmentIndex, setSegmentIndex] = useState(0);
  const [presetPath, setPresetPath] = useState("studio_preset.json");
  const [voiceRefDrag, setVoiceRefDrag] = useState(false);

  const storyJsonRef = useRef<HTMLInputElement>(null);
  const voiceRefRef = useRef<HTMLInputElement>(null);
  const bgMusicRef = useRef<HTMLInputElement>(null);

  const { setOpen: setSidebarOpen } = useSidebar();
  useNavigationGuard(busy);
  const totalSecs = segments.reduce((a, s) => a + s.estSecs, 0);
  const totalStr = totalSecs > 0
    ? `${Math.floor(totalSecs / 60)}:${String(Math.round(totalSecs % 60)).padStart(2, "0")}`
    : "—";
  const estGenSecs = Math.round(totalSecs * 0.6);

  useEffect(() => {
    fetchConfig().then(c => {
      setCfg(c);
      const d = c.defaults as Record<string, unknown>;
      setVoicePreset(d.voice_preset as string ?? "Balanced Neutral");
      setVoiceStyle(d.voice_style as string ?? "Balanced");
      setCfgValue(d.cfg_value as number ?? 1.7);
    });
  }, []);

  async function handleFileLoad(files: File[]) {
    setLoadedFiles(files);
    if (!files[0]) return;
    try {
      const text = await files[0].text();
      const data = JSON.parse(text);
      const rawSegs: Array<{ segment_id?: number; segment?: number; target_text?: string; narration?: string; title?: string; duration?: string }> =
        data.segments ?? data.stories?.flatMap((s: { segments: unknown[] }) => s.segments) ?? [];
      const parsed = rawSegs.slice(0, 20).map((s, i) => {
        const txt = s.target_text ?? s.narration ?? "";
        const words = txt.split(/\s+/).filter(Boolean).length;
        return { id: s.segment_id ?? s.segment ?? i + 1, text: txt.slice(0, 80) + (txt.length > 80 ? "..." : ""), estSecs: Math.round((words / 130) * 60) };
      });
      setSegments(parsed);
    } catch { setSegments([]); }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith(".json"));
    if (files.length && storyJsonRef.current) {
      const dt = new DataTransfer();
      files.forEach(f => dt.items.add(f));
      storyJsonRef.current.files = dt.files;
      handleFileLoad(files);
    }
  }

  function buildForm(): FormData {
    const f = new FormData();
    if (storyJsonRef.current?.files) Array.from(storyJsonRef.current.files).forEach(file => f.append("story_json", file));
    if (voiceRefRef.current?.files?.[0]) f.append("voice_ref", voiceRefRef.current.files[0]);
    if (bgMusicRef.current?.files?.[0]) f.append("bg_music", bgMusicRef.current.files[0]);
    f.append("voice_source", "generate");
    f.append("voice_preset", voicePreset);
    f.append("voice_style", voiceStyle);
    f.append("cfg_value", String(cfgValue));
    f.append("do_normalize", String(doNormalize));
    f.append("denoise", String(denoise));
    f.append("auto_emotion", String(autoEmotion));
    f.append("speaker_lock", String(speakerLock));
    f.append("max_workers", String(maxWorkers));
    f.append("bg_sound_query", bgSoundQuery);
    f.append("bg_percent", String(bgPercent));
    f.append("auto_amb", String(autoAmb));
    f.append("voice_out", voiceOut);
    f.append("segments_output", segmentsOutput);
    return f;
  }

  async function runVoice() {
    if (!storyJsonRef.current?.files?.length) { alert("Choose a Story JSON file."); return; }
    setBusy(true);
    const jid = await startVoice(buildForm());
    setJobId(jid);
  }

  async function doPreview() {
    if (!storyJsonRef.current?.files?.[0]) { alert("Load a Story JSON first."); return; }
    const f = new FormData();
    f.append("story_json", storyJsonRef.current.files[0]);
    f.append("segment_index", String(segmentIndex));
    f.append("voice_preset", voicePreset);
    f.append("voice_style", voiceStyle);
    f.append("cfg_value", String(cfgValue));
    f.append("do_normalize", String(doNormalize));
    f.append("denoise", String(denoise));
    f.append("speaker_lock", String(speakerLock));
    if (voiceRefRef.current?.files?.[0]) f.append("voice_ref", voiceRefRef.current.files[0]);
    const jid = await startPreviewSegment(f);
    setPreviewJobId(jid);
  }

  async function doSavePreset() {
    const r = await savePreset({ preset_path: presetPath, voice_preset: voicePreset, voice_style: voiceStyle, cfg_value: cfgValue, do_normalize: doNormalize, denoise, auto_emotion: autoEmotion, speaker_lock: speakerLock, max_workers: maxWorkers, bg_percent: bgPercent, auto_amb: autoAmb, bg_sound_query: bgSoundQuery });
    setToolStatus(r.status);
  }
  async function doLoadPreset() {
    const data = await loadPreset(presetPath);
    if (!data) { setToolStatus("❌ Preset not found."); return; }
    if (data.voice_preset) setVoicePreset(data.voice_preset);
    if (data.voice_style) setVoiceStyle(data.voice_style);
    if (data.cfg_value !== undefined) setCfgValue(data.cfg_value);
    if (data.do_normalize !== undefined) setDoNormalize(data.do_normalize);
    if (data.denoise !== undefined) setDenoise(data.denoise);
    setToolStatus("✅ Preset loaded.");
  }
  async function doExportSrt() { const r = await exportSrt(voiceOut); setToolStatus(r.status); }
  async function doChapters() { const r = await generateChapters(voiceOut); setToolStatus(r.status); setChapters(r.chapters); }

  return (
    <div className="flex flex-col md:h-screen md:overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 md:px-6 py-3.5 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={() => setSidebarOpen(true)} className="md:hidden p-1 text-gray-400 hover:text-gray-200">
            <Menu size={18} />
          </button>
          <Mic size={18} className="text-gray-400" />
          <span className="text-sm font-semibold text-gray-100">Generate Voice</span>
          <span className="text-xs text-gray-500 hidden md:block">Narrate story segments into a single MP3</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-green-400">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
          Ready
        </div>
      </div>

      <div className="flex flex-col md:flex-row md:flex-1 md:overflow-hidden">
        {/* ── Left ─────────────────────────────────── */}
        <div className="flex flex-col w-full md:w-[58%] min-w-0 border-b md:border-b-0 md:border-r border-gray-800 md:overflow-hidden">
          {/* Tabs */}
          <div className="flex gap-1 px-4 py-3 border-b border-gray-800 shrink-0">
            {TABS.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  tab === t.id ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"}`}>
                {t.icon}{t.label}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {tab === "voice" && (<>
              <Section num="01" title="Source">
                {/* Drop zone */}
                <div
                  onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => storyJsonRef.current?.click()}
                  className={`flex flex-col items-center justify-center gap-1.5 rounded-lg border-2 border-dashed cursor-pointer py-5 transition-colors
                    ${dragOver ? "border-blue-500 bg-blue-500/10" : "border-gray-700 hover:border-gray-600"}`}>
                  <input ref={storyJsonRef} type="file" accept=".json" multiple className="sr-only"
                    onChange={e => handleFileLoad(Array.from(e.target.files ?? []))} />
                  <svg className="w-5 h-5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                  </svg>
                  <p className="text-xs text-gray-400"><span className="text-blue-400">Drop</span> Story JSON files</p>
                  <p className="text-[10px] text-gray-600">or click to browse · .json</p>
                  {loadedFiles.length > 0 && (
                    <p className="text-[10px] text-green-400 mt-0.5">{loadedFiles.map(f => f.name).join(", ")}</p>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="label">Voice output</label>
                    <input className="input" value={voiceOut} onChange={e => setVoiceOut(e.target.value)} />
                  </div>
                  <div>
                    <label className="label">Segments</label>
                    <input className="input" value={segmentsOutput} onChange={e => setSegmentsOutput(e.target.value)} />
                  </div>
                </div>
              </Section>

              <Section num="02" title="Voice character">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="label">Preset</label>
                    <select className="input" value={voicePreset} onChange={e => setVoicePreset(e.target.value)}>
                      {cfg?.voice_presets.map(p => <option key={p}>{p}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="label">Style</label>
                    <select className="input" value={voiceStyle} onChange={e => setVoiceStyle(e.target.value)}>
                      {cfg?.voice_styles.map(s => <option key={s}>{s}</option>)}
                    </select>
                  </div>
                </div>
                {/* Reference voice drop zone */}
                <div>
                  <label className="label">Reference voice (optional)</label>
                  <div
                    onDragOver={e => { e.preventDefault(); setVoiceRefDrag(true); }}
                    onDragLeave={() => setVoiceRefDrag(false)}
                    onDrop={e => { e.preventDefault(); setVoiceRefDrag(false); if (voiceRefRef.current && e.dataTransfer.files[0]) { const dt = new DataTransfer(); dt.items.add(e.dataTransfer.files[0]); voiceRefRef.current.files = dt.files; } }}
                    onClick={() => voiceRefRef.current?.click()}
                    className={`flex items-center gap-3 rounded-lg border-2 border-dashed cursor-pointer px-4 py-3 transition-colors
                      ${voiceRefDrag ? "border-blue-500 bg-blue-500/10" : "border-gray-700 hover:border-gray-600"}`}>
                    <input ref={voiceRefRef} type="file" accept="audio/*" className="sr-only" />
                    <Mic size={16} className="text-gray-500 shrink-0" />
                    <div>
                      <p className="text-xs text-gray-300 font-medium">Clone from a sample</p>
                      <p className="text-[10px] text-gray-600">Drop a .wav / .mp3</p>
                    </div>
                  </div>
                </div>
              </Section>

              <p className="text-xs text-gray-600 flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Advanced, Audio and Tools tabs carry the same grouped-card layout.
              </p>
            </>)}

            {tab === "advanced" && (
              <Section num="" title="Advanced">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="flex justify-between mb-1.5">
                      <span className="text-xs text-gray-400">CFG guidance</span>
                      <span className="text-xs font-mono text-blue-400">{cfgValue}</span>
                    </div>
                    <input type="range" min={1} max={3} step={0.1} value={cfgValue} onChange={e => setCfgValue(+e.target.value)} className="w-full accent-blue-500 h-1" />
                  </div>
                  <div>
                    <div className="flex justify-between mb-1.5">
                      <span className="text-xs text-gray-400">Max workers</span>
                      <span className="text-xs font-mono text-blue-400">{maxWorkers}</span>
                    </div>
                    <input type="range" min={1} max={4} step={1} value={maxWorkers} onChange={e => setMaxWorkers(+e.target.value)} className="w-full accent-blue-500 h-1" />
                  </div>
                </div>
                <label className="check"><input type="checkbox" checked={doNormalize} onChange={e => setDoNormalize(e.target.checked)} /> Text normalization</label>
                <label className="check"><input type="checkbox" checked={denoise} onChange={e => setDenoise(e.target.checked)} /> Reference denoising</label>
                <label className="check"><input type="checkbox" checked={autoEmotion} onChange={e => setAutoEmotion(e.target.checked)} /> Different feeling per segment</label>
                <label className="check"><input type="checkbox" checked={speakerLock} onChange={e => setSpeakerLock(e.target.checked)} /> Lock narrator voice (prevents gender drift)</label>
              </Section>
            )}

            {tab === "audio" && (
              <Section num="" title="Audio">
                <div>
                  <label className="label">Background music file (optional)</label>
                  <input ref={bgMusicRef} type="file" accept="audio/*" className="file-input" />
                </div>
                <div>
                  <label className="label">Stock music query</label>
                  <input className="input" value={bgSoundQuery} onChange={e => setBgSoundQuery(e.target.value)} placeholder="e.g. dark ambient horror" />
                </div>
                <div>
                  <div className="flex justify-between mb-1.5">
                    <span className="text-xs text-gray-400">Music level</span>
                    <span className="text-xs font-mono text-blue-400">{bgPercent.toFixed(2)}</span>
                  </div>
                  <input type="range" min={0} max={0.5} step={0.01} value={bgPercent} onChange={e => setBgPercent(+e.target.value)} className="w-full accent-blue-500 h-1" />
                </div>
                <label className="check"><input type="checkbox" checked={autoAmb} onChange={e => setAutoAmb(e.target.checked)} /> Generate dark ambience if no music</label>
              </Section>
            )}

            {tab === "tools" && (
              <Section num="" title="Tools">
                <div>
                  <p className="text-xs text-gray-400 mb-2">Export SRT subtitles from last voice timeline</p>
                  <button onClick={doExportSrt} className="btn-secondary text-xs">Export SRT</button>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-2">Generate YouTube chapter markers</p>
                  <button onClick={doChapters} className="btn-secondary text-xs">Generate Chapters</button>
                  {chapters && <textarea readOnly value={chapters} rows={5} className="mt-2 w-full input text-xs font-mono" />}
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-2">Preview one segment</p>
                  <div className="flex gap-2 items-center">
                    <input type="number" min={0} value={segmentIndex} onChange={e => setSegmentIndex(+e.target.value)} className="input w-20 text-sm" />
                    <button onClick={doPreview} className="btn-secondary text-xs">Preview</button>
                  </div>
                  <LogStream jobId={previewJobId} />
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-2">Settings preset</p>
                  <div className="flex gap-2">
                    <input className="input flex-1 text-xs" value={presetPath} onChange={e => setPresetPath(e.target.value)} />
                    <button onClick={doSavePreset} className="btn-secondary text-xs">Save</button>
                    <button onClick={doLoadPreset} className="btn-secondary text-xs">Load</button>
                  </div>
                </div>
                {toolStatus && <p className="text-xs text-gray-300">{toolStatus}</p>}
              </Section>
            )}
          </div>
        </div>

        {/* ── Right: Preview ──────────────────────── */}
        <div className="flex flex-col w-full md:w-[42%] min-w-0 bg-gray-950">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-800 shrink-0">
            <span className="text-sm font-semibold text-gray-200">Preview</span>
            <span className="text-xs text-gray-500">{voicePreset} · {voiceStyle}</span>
          </div>

          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Waveform player */}
            <div className="p-5 border-b border-gray-800">
              <div className="bg-gray-900 rounded-xl p-4 flex items-center gap-4">
                <button onClick={() => setPlaying(p => !p)}
                  className="w-10 h-10 rounded-full bg-blue-600 flex items-center justify-center shrink-0 hover:bg-blue-500 transition-colors">
                  {playing
                    ? <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
                    : <svg className="w-4 h-4 text-white ml-0.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>}
                </button>
                <div className="flex-1 min-w-0">
                  <Waveform playing={playing} />
                  <div className="flex justify-between text-[10px] font-mono text-gray-600 mt-1">
                    <span>0:00</span>
                    <span>{totalStr}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Segments list */}
            <div className="flex-1 overflow-y-auto">
              <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800">
                <span className="text-xs font-semibold text-gray-200">Segments</span>
                <span className="text-xs text-gray-500">
                  {segments.length > 0 ? `${segments.length} · ${totalStr} total` : "load a JSON to preview"}
                </span>
              </div>
              {segments.length > 0 ? (
                <div className="divide-y divide-gray-800/60">
                  {segments.map(seg => (
                    <div key={seg.id} className="flex items-center gap-3 px-5 py-3 hover:bg-gray-900/40 transition-colors group">
                      <span className="text-xs font-mono text-blue-400 w-5 shrink-0">
                        {String(seg.id).padStart(2, "0")}
                      </span>
                      <button className="w-5 h-5 rounded-full border border-gray-700 flex items-center justify-center shrink-0 group-hover:border-blue-500 transition-colors">
                        <svg className="w-2.5 h-2.5 text-gray-500 ml-0.5 group-hover:text-blue-400" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M8 5v14l11-7z" />
                        </svg>
                      </button>
                      <p className="text-xs text-gray-400 flex-1 truncate">{seg.text || "—"}</p>
                      <span className="text-[10px] font-mono text-gray-600 shrink-0">
                        {Math.floor(seg.estSecs / 60)}:{String(seg.estSecs % 60).padStart(2, "0")}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-16 text-gray-700">
                  <Mic size={28} className="mb-2 opacity-40" />
                  <p className="text-xs">No segments loaded</p>
                </div>
              )}
            </div>
          </div>

          {/* CTA */}
          <div className="border-t border-gray-800 p-4 shrink-0">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-200">
                  {segments.length > 0 ? `${segments.length} segments · ~${totalStr} narration` : "No files loaded"}
                </p>
                <p className="text-xs text-gray-500">
                  {segments.length > 0 ? `Est. generate ${estGenSecs}–${estGenSecs + 20} sec · ${maxWorkers} workers` : "Drop a Story JSON to begin"}
                </p>
              </div>
              <button onClick={runVoice} disabled={busy}
                className="flex items-center gap-2 shrink-0 rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50 transition-colors shadow-lg">
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
                Generate Voice
              </button>
            </div>
            <LogStream jobId={jobId} onDone={() => setBusy(false)} />
          </div>
        </div>
      </div>
    </div>
  );
}
