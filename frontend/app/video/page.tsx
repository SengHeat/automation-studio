"use client";
import { useEffect, useRef, useState } from "react";
import { LogStream } from "@/components/LogStream";
import {
  fetchConfig, startVideo, savePreset, loadPreset,
  exportSrt, generateChapters, fetchTestStoryFixture, type AppConfig,
} from "@/lib/api";
import { Clapperboard, Subtitles, Paintbrush, Wrench, Menu } from "lucide-react";
import { useSidebar } from "@/components/ui/Sidebar";
import { useNavigationGuard } from "@/lib/useNavigationGuard";

type Tab = "video" | "subtitles" | "branding" | "tools";
type Ratio = "16:9" | "9:16" | "1:1";

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "video",     label: "Video",     icon: <Clapperboard size={12} /> },
  { id: "subtitles", label: "Subtitles", icon: <Subtitles size={12} /> },
  { id: "branding",  label: "Branding",  icon: <Paintbrush size={12} /> },
  { id: "tools",     label: "Tools",     icon: <Wrench size={12} /> },
];

function Section({ num, title, children }: { num: string; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/40 overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800/60">
        <span className="text-xs font-mono text-gray-600 select-none">{num}</span>
        <span className="text-sm font-semibold text-gray-200">{title}</span>
      </div>
      <div className="p-4 space-y-3">{children}</div>
    </div>
  );
}

function SliderRow({ label, value, display, min, max, step, onChange }: {
  label: string; value: number; display: string;
  min: number; max: number; step: number; onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex justify-between mb-1.5">
        <span className="text-xs text-gray-400">{label}</span>
        <span className="text-xs font-mono text-blue-400">{display}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(+e.target.value)} className="w-full accent-blue-500 h-1" />
    </div>
  );
}

export default function VideoPage() {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [tab, setTab] = useState<Tab>("video");
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [toolStatus, setToolStatus] = useState("");
  const [chapters, setChapters] = useState("");
  const [ratio, setRatio] = useState<Ratio>("16:9");
  const [activeSegment, setActiveSegment] = useState(0);
  const [loadedFiles, setLoadedFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);

  const [voiceSource, setVoiceSource] = useState<"existing" | "generate" | "test">("generate");
  const [fixtureLoading, setFixtureLoading] = useState(false);
  const [jsonPath, setJsonPath] = useState("");
  const [storyAuthors, setStoryAuthors] = useState("Anonymous");
  const [storyCardDuration, setStoryCardDuration] = useState(5);
  const [voiceOut, setVoiceOut] = useState("voice_final.mp3");
  const [segmentsOutput, setSegmentsOutput] = useState("segments_audio");
  const [videoOut, setVideoOut] = useState("");
  const [resolution, setResolution] = useState("1280×720");
  const [fps, setFps] = useState(20);
  const [crf, setCrf] = useState(18);
  const [transitionDuration, setTransitionDuration] = useState(1.5);
  const [effectStyle, setEffectStyle] = useState("Horror Cinematic");
  const [makeThumbnail, setMakeThumbnail] = useState(true);
  const [useAiImages, setUseAiImages] = useState(false);
  const [enableSubtitles, setEnableSubtitles] = useState(false);
  const [subtitleSize, setSubtitleSize] = useState(28);
  const [subtitlePosition, setSubtitlePosition] = useState("bottom");
  const [showTitle, setShowTitle] = useState(false);
  const [channel, setChannel] = useState("");
  const [channelCorner, setChannelCorner] = useState("top-right");
  const [useLogo, setUseLogo] = useState(false);
  const [logoCorner, setLogoCorner] = useState("bottom-right");
  const [presetPath, setPresetPath] = useState("studio_preset.json");

  const storyJsonRef = useRef<HTMLInputElement>(null);
  const bgMusicRef = useRef<HTMLInputElement>(null);
  const logoRef = useRef<HTMLInputElement>(null);

  const { setOpen: setSidebarOpen } = useSidebar();
  useNavigationGuard(busy);
  const segCount = loadedFiles.length > 0 ? 9 : 0;
  const estSecs = segCount * storyCardDuration;
  const strips = Array.from({ length: Math.max(segCount, 5) }, (_, i) => i);
  const progressPct = segCount > 1 ? (activeSegment / (segCount - 1)) * 100 : 0;
  const timeStr = `${Math.floor(estSecs / 60)}:${String(estSecs % 60).padStart(2, "0")}`;

  useEffect(() => {
    fetchConfig().then(c => {
      setCfg(c);
      const d = c.defaults as Record<string, unknown>;
      setResolution(d.resolution as string ?? "1280×720");
      setFps(d.fps as number ?? 20);
      setCrf(d.crf as number ?? 18);
      setTransitionDuration(d.transition_duration as number ?? 1.5);
      setEffectStyle(d.effect_style as string ?? "Horror Cinematic");
      setStoryCardDuration(d.story_card_duration as number ?? 5);
    });
  }, []);

  async function handleVoiceSourceChange(v: "existing" | "generate" | "test") {
    setVoiceSource(v);
    if (v !== "test") return;
    setFixtureLoading(true);
    try {
      const file = await fetchTestStoryFixture();
      const dt = new DataTransfer();
      dt.items.add(file);
      if (storyJsonRef.current) {
        storyJsonRef.current.files = dt.files;
      }
      setLoadedFiles([file]);
    } catch {
      alert("Could not load test fixture from server. Is the backend running?");
      setVoiceSource("generate");
    } finally {
      setFixtureLoading(false);
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith(".json"));
    if (files.length && storyJsonRef.current) {
      const dt = new DataTransfer();
      files.forEach(f => dt.items.add(f));
      storyJsonRef.current.files = dt.files;
      setLoadedFiles(files);
    }
  }

  async function runVideo() {
    const hasFile = (storyJsonRef.current?.files?.length ?? 0) > 0;
    const hasPath = jsonPath.trim().length > 0;
    if (!hasFile && !hasPath) { alert("Choose a Story JSON file or enter a server-side JSON path."); return; }
    setBusy(true);
    const f = new FormData();
    if (hasFile) Array.from(storyJsonRef.current!.files!).forEach(file => f.append("story_json", file));
    if (hasPath) f.append("json_path", jsonPath.trim());
    if (bgMusicRef.current?.files?.[0]) f.append("bg_music", bgMusicRef.current.files[0]);
    if (logoRef.current?.files?.[0]) f.append("logo", logoRef.current.files[0]);
    const effectiveVoiceSource = voiceSource === "test" ? "generate" : voiceSource;
    f.append("voice_source", effectiveVoiceSource);
    f.append("video_only", String(voiceSource === "test"));
    f.append("voice_out", voiceOut);
    f.append("segments_output", segmentsOutput);
    f.append("story_authors", storyAuthors);
    f.append("story_card_duration", String(storyCardDuration));
    f.append("video_out", videoOut);
    f.append("resolution", resolution.replace("×", "x"));
    f.append("fps", String(fps));
    f.append("crf", String(crf));
    f.append("transition_duration", String(transitionDuration));
    f.append("effect_style", effectStyle);
    f.append("enable_subtitles", String(enableSubtitles));
    f.append("subtitle_size", String(subtitleSize));
    f.append("subtitle_position", subtitlePosition);
    f.append("make_thumbnail", String(makeThumbnail));
    f.append("use_ai_images", String(useAiImages));
    f.append("show_title", String(showTitle));
    f.append("use_logo", String(useLogo));
    f.append("logo_corner", logoCorner);
    f.append("channel", channel);
    f.append("channel_corner", channelCorner);
    const jid = await startVideo(f);
    setJobId(jid);
  }

  async function doSavePreset() {
    const r = await savePreset({
      preset_path: presetPath, resolution, fps, crf,
      transition_duration: transitionDuration, effect_style: effectStyle,
      enable_subtitles: enableSubtitles, subtitle_size: subtitleSize,
      subtitle_position: subtitlePosition, make_thumbnail: makeThumbnail,
      use_ai_images: useAiImages, show_title: showTitle, use_logo: useLogo,
      logo_corner: logoCorner, channel, channel_corner: channelCorner,
    });
    setToolStatus(r.status);
  }

  async function doLoadPreset() {
    const data = await loadPreset(presetPath);
    if (!data) { setToolStatus("❌ Preset not found."); return; }
    if (data.resolution) setResolution(data.resolution);
    if (data.fps) setFps(data.fps);
    if (data.crf) setCrf(data.crf);
    if (data.effect_style) setEffectStyle(data.effect_style);
    if (data.enable_subtitles !== undefined) setEnableSubtitles(data.enable_subtitles);
    if (data.subtitle_size) setSubtitleSize(data.subtitle_size);
    if (data.subtitle_position) setSubtitlePosition(data.subtitle_position);
    if (data.show_title !== undefined) setShowTitle(data.show_title);
    if (data.use_logo !== undefined) setUseLogo(data.use_logo);
    if (data.channel) setChannel(data.channel);
    setToolStatus("✅ Preset loaded.");
  }

  async function doExportSrt() { const r = await exportSrt(voiceOut); setToolStatus(r.status); }
  async function doChapters() { const r = await generateChapters(voiceOut); setToolStatus(r.status); setChapters(r.chapters); }

  return (
    <div className="flex flex-col md:h-screen md:overflow-hidden">
      {/* Full-width header */}
      <div className="flex items-center justify-between px-4 md:px-6 py-3.5 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={() => setSidebarOpen(true)} className="md:hidden p-1 text-gray-400 hover:text-gray-200">
            <Menu size={18} />
          </button>
          <Clapperboard size={18} className="text-gray-400" />
          <span className="text-sm font-semibold text-gray-100">Make Video</span>
          <span className="text-xs text-gray-500 hidden md:block">Assemble story cards into a rendered video</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-green-400">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
          Ready
        </div>
      </div>

      <div className="flex flex-col md:flex-row md:flex-1 md:overflow-hidden">
        {/* ── Left ─────────────────────────────────── */}
        <div className="flex flex-col w-full md:w-[58%] min-w-0 border-b md:border-b-0 md:border-r border-gray-800 md:overflow-hidden">
          {/* Tab bar */}
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
            {tab === "video" && (<>
              <Section num="01" title="Source">
                {/* Server-side path input */}
                <div>
                  <label className="label">Server JSON path</label>
                  <input
                    className="input font-mono text-xs"
                    value={jsonPath}
                    onChange={e => setJsonPath(e.target.value)}
                    placeholder="e.g. fixtures/test_story_home_invasion.json"
                    spellCheck={false}
                  />
                  {jsonPath.trim() && (
                    <p className="text-[11px] text-green-400 mt-1">
                      ✓ Will use server path — no upload needed
                    </p>
                  )}
                </div>
                <p className="text-[11px] text-gray-600 -mt-1">— or upload a file —</p>
                <div
                  onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => storyJsonRef.current?.click()}
                  className={`flex flex-col items-center justify-center gap-1.5 rounded-lg border-2 border-dashed cursor-pointer py-5 transition-colors
                    ${dragOver ? "border-blue-500 bg-blue-500/10" : "border-gray-700 hover:border-gray-600"}`}>
                  <input ref={storyJsonRef} type="file" accept=".json" multiple className="sr-only"
                    onChange={e => setLoadedFiles(Array.from(e.target.files ?? []))} />
                  <svg className="w-5 h-5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                  </svg>
                  <p className="text-xs text-gray-400">
                    <span className="text-blue-400">Drop</span> Story JSON files
                  </p>
                  <p className="text-[10px] text-gray-600">or click to browse · .json</p>
                  {loadedFiles.length > 0 && (
                    <p className="text-[10px] text-green-400 mt-0.5">{loadedFiles.map(f => f.name).join(", ")}</p>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="label">Voice MP3</label>
                    <input className="input" value={voiceOut} onChange={e => setVoiceOut(e.target.value)} />
                  </div>
                  <div>
                    <label className="label">Segments</label>
                    <input className="input" value={segmentsOutput} onChange={e => setSegmentsOutput(e.target.value)} />
                  </div>
                </div>
                <div>
                  <label className="label">Voice source</label>
                  <select
                    className="input"
                    value={voiceSource}
                    onChange={e => handleVoiceSourceChange(e.target.value as "existing" | "generate" | "test")}
                    disabled={fixtureLoading}
                  >
                    <option value="generate">Generate voice</option>
                    <option value="existing">Use existing voice file</option>
                    <option value="test">🧪 Test render (no voice)</option>
                  </select>
                  {fixtureLoading && (
                    <p className="text-[11px] text-blue-400 mt-1">Loading test story…</p>
                  )}
                  {voiceSource === "test" && !fixtureLoading && (
                    <p className="text-[11px] text-yellow-500 mt-1">
                      ⚡ Auto-loaded: 3 True Home Invasion Horror Stories · silent placeholder audio
                    </p>
                  )}
                </div>
              </Section>

              <Section num="02" title="Output & timing">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="label">Resolution</label>
                    <select className="input" value={resolution} onChange={e => setResolution(e.target.value)}>
                      {cfg?.resolutions.map(r => <option key={r}>{r}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="label">Output (.mp4)</label>
                    <input className="input" value={videoOut} onChange={e => setVideoOut(e.target.value)} placeholder="auto" />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <SliderRow label="FPS" value={fps} display={String(fps)} min={12} max={30} step={1} onChange={setFps} />
                  <SliderRow label="CRF" value={crf} display={String(crf)} min={18} max={28} step={1} onChange={setCrf} />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <SliderRow label="Card duration" value={storyCardDuration} display={`${storyCardDuration}s`} min={3} max={8} step={0.5} onChange={setStoryCardDuration} />
                  <SliderRow label="Transition" value={transitionDuration} display={`${transitionDuration}s`} min={0.3} max={3} step={0.1} onChange={setTransitionDuration} />
                </div>
              </Section>

              <Section num="03" title="Style & extras">
                <div>
                  <label className="label">Effect style</label>
                  <select className="input" value={effectStyle} onChange={e => setEffectStyle(e.target.value)}>
                    {cfg?.effect_styles.map(s => <option key={s}>{s}</option>)}
                  </select>
                </div>
                <label className="check">
                  <input type="checkbox" checked={makeThumbnail} onChange={e => setMakeThumbnail(e.target.checked)} />
                  Generate thumbnail
                </label>
                <label className="check">
                  <input type="checkbox" checked={useAiImages} onChange={e => setUseAiImages(e.target.checked)} />
                  Generate AI images (DALL-E 3)
                </label>
              </Section>
            </>)}

            {tab === "subtitles" && (
              <Section num="" title="Subtitles">
                <label className="check">
                  <input type="checkbox" checked={enableSubtitles} onChange={e => setEnableSubtitles(e.target.checked)} />
                  Burn captions into video
                </label>
                <div className="grid grid-cols-2 gap-4">
                  <SliderRow label="Font size" value={subtitleSize} display={`${subtitleSize}px`} min={14} max={48} step={2} onChange={setSubtitleSize} />
                  <div>
                    <label className="label">Position</label>
                    <select className="input" value={subtitlePosition} onChange={e => setSubtitlePosition(e.target.value)}>
                      {cfg?.subtitle_positions.map(p => <option key={p}>{p}</option>)}
                    </select>
                  </div>
                </div>
              </Section>
            )}

            {tab === "branding" && (
              <Section num="" title="Branding">
                <label className="check">
                  <input type="checkbox" checked={showTitle} onChange={e => setShowTitle(e.target.checked)} />
                  Show story title card
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="label">Channel name</label>
                    <input className="input" value={channel} onChange={e => setChannel(e.target.value)} placeholder="Whispered Confessions" />
                  </div>
                  <div>
                    <label className="label">Channel corner</label>
                    <select className="input" value={channelCorner} onChange={e => setChannelCorner(e.target.value)}>
                      {cfg?.logo_corners.map(c => <option key={c}>{c}</option>)}
                    </select>
                  </div>
                </div>
                <label className="check">
                  <input type="checkbox" checked={useLogo} onChange={e => setUseLogo(e.target.checked)} />
                  Overlay logo image
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="label">Logo file</label>
                    <input ref={logoRef} type="file" accept="image/*" className="file-input" />
                  </div>
                  <div>
                    <label className="label">Logo corner</label>
                    <select className="input" value={logoCorner} onChange={e => setLogoCorner(e.target.value)}>
                      {cfg?.logo_corners.map(c => <option key={c}>{c}</option>)}
                    </select>
                  </div>
                </div>
                <div>
                  <label className="label">Authors</label>
                  <input className="input" value={storyAuthors} onChange={e => setStoryAuthors(e.target.value)} />
                </div>
              </Section>
            )}

            {tab === "tools" && (
              <Section num="" title="Tools">
                <div>
                  <p className="text-xs text-gray-400 mb-2">Background music (optional)</p>
                  <input ref={bgMusicRef} type="file" accept="audio/*" className="file-input" />
                </div>
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
            <div className="flex rounded-lg border border-gray-700 overflow-hidden text-xs">
              {(["16:9", "9:16", "1:1"] as Ratio[]).map(r => (
                <button key={r} onClick={() => setRatio(r)}
                  className={`px-2.5 py-1 transition-colors ${ratio === r ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"}`}>
                  {r}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 flex flex-col p-5 gap-4 overflow-hidden">
            {/* Video frame */}
            <div className={`relative w-full bg-gray-900 rounded-xl border border-gray-800 flex items-center justify-center overflow-hidden
              ${ratio === "16:9" ? "aspect-video" : ratio === "9:16" ? "aspect-[9/16] max-h-52 mx-auto" : "aspect-square"}`}>
              <div className="absolute top-3 left-3 text-[10px] font-mono tracking-widest text-gray-500 bg-black/50 px-2 py-0.5 rounded">
                CARD {activeSegment + 1} / {segCount || "—"}
              </div>
              <div className="absolute inset-0 opacity-[0.03]"
                style={{ backgroundImage: "linear-gradient(#fff 1px,transparent 1px),linear-gradient(90deg,#fff 1px,transparent 1px)", backgroundSize: "40px 40px" }} />
              <div className="w-12 h-12 rounded-full bg-blue-600/90 flex items-center justify-center shadow-xl cursor-pointer hover:bg-blue-500 transition-colors">
                <svg className="w-5 h-5 text-white ml-0.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
              </div>
            </div>

            {/* Timeline */}
            <div className="space-y-1.5">
              <div className="relative h-1.5 bg-gray-800 rounded-full cursor-pointer">
                <div className="h-full bg-blue-600 rounded-full" style={{ width: `${progressPct}%` }} />
                <div className="absolute top-1/2 w-3 h-3 rounded-full bg-white shadow-md -translate-y-1/2 -translate-x-1/2"
                  style={{ left: `${progressPct}%` }} />
              </div>
              <div className="flex justify-between text-[10px] font-mono text-gray-600">
                <span>0:00</span>
                <span>{timeStr}</span>
              </div>
            </div>

            {/* Segment strip */}
            <div className="flex gap-2 overflow-x-auto pb-1">
              {strips.slice(0, 5).map((_, i) => (
                <button key={i} onClick={() => setActiveSegment(i)}
                  className={`flex-shrink-0 w-14 h-10 rounded-lg text-xs font-mono transition-colors border ${
                    i === activeSegment ? "bg-blue-600 border-blue-500 text-white" : "bg-gray-800 border-gray-700 text-gray-500 hover:border-gray-600"}`}>
                  {String(i + 1).padStart(2, "0")}
                </button>
              ))}
              {strips.length > 5 && (
                <div className="flex-shrink-0 w-14 h-10 rounded-lg text-xs font-mono bg-gray-800 border border-gray-700 text-gray-600 flex items-center justify-center">
                  +{strips.length - 5}
                </div>
              )}
            </div>
          </div>

          {/* Stats + CTA */}
          <div className="border-t border-gray-800 p-4 space-y-3 shrink-0">
            <div className="flex flex-wrap gap-x-2 gap-y-1.5">
              {[resolution, `${fps} fps`, `CRF ${crf}`, effectStyle, makeThumbnail ? "Thumbnail on" : "Thumbnail off"].map(s => (
                <span key={s} className="text-[10px] text-gray-500 bg-gray-800 px-2 py-0.5 rounded-md">{s}</span>
              ))}
            </div>
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-200">
                  {segCount > 0 ? `${segCount} cards · ~${estSecs}s output` : "No files loaded"}
                </p>
                <p className="text-xs text-gray-500">
                  {segCount > 0 ? "Estimated render 2–3 min" : "Drop a Story JSON to begin"}
                </p>
              </div>
              <button onClick={runVideo} disabled={busy}
                className="flex items-center gap-2 shrink-0 rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50 transition-colors shadow-lg">
                <Clapperboard size={14} />
                Make Video
              </button>
            </div>
            <LogStream jobId={jobId} onDone={() => setBusy(false)} />
          </div>
        </div>
      </div>
    </div>
  );
}
