"use client";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { LogStream } from "@/components/LogStream";
import { fetchConfig, startVoice, startVideo, exportSrt, generateChapters,
         startPreviewSegment, savePreset, loadPreset, type AppConfig } from "@/lib/api";

type Tab = "voice" | "advanced" | "audio" | "video" | "subtitles" | "branding" | "tools";

export default function StudioPage() {
  const params = useSearchParams();
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [tab, setTab] = useState<Tab>(() => {
    const t = params.get("tab");
    return (t === "video" ? "video" : "voice") as Tab;
  });
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [toolStatus, setToolStatus] = useState("");
  const [chapters, setChapters] = useState("");
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);

  // Form state
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
  const [storyAuthors, setStoryAuthors] = useState("Anonymous");
  const [storyCardDuration, setStoryCardDuration] = useState(5);
  const [resolution, setResolution] = useState("1280x720");
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
  const [videoOut, setVideoOut] = useState("");
  const [segmentIndex, setSegmentIndex] = useState(0);

  // File refs
  const storyJsonRef = useRef<HTMLInputElement>(null);
  const voiceRefRef = useRef<HTMLInputElement>(null);
  const bgMusicRef = useRef<HTMLInputElement>(null);
  const logoRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchConfig().then(c => {
      setCfg(c);
      const d = c.defaults as Record<string, unknown>;
      setVoicePreset(d.voice_preset as string ?? "Balanced Neutral");
      setVoiceStyle(d.voice_style as string ?? "Balanced");
      setCfgValue(d.cfg_value as number ?? 1.7);
      setResolution(d.resolution as string ?? "1280x720");
      setFps(d.fps as number ?? 20);
      setCrf(d.crf as number ?? 18);
      setTransitionDuration(d.transition_duration as number ?? 1.5);
      setEffectStyle(d.effect_style as string ?? "Horror Cinematic");
      setStoryCardDuration(d.story_card_duration as number ?? 5);
    });
  }, []);

  function buildForm(): FormData {
    const f = new FormData();
    const files = storyJsonRef.current?.files;
    if (files) Array.from(files).forEach(file => f.append("story_json", file));
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

  async function runVideo() {
    if (!storyJsonRef.current?.files?.length) { alert("Choose a Story JSON file."); return; }
    setBusy(true);
    const f = buildForm();
    f.append("story_authors", storyAuthors);
    f.append("story_card_duration", String(storyCardDuration));
    f.append("video_out", videoOut);
    f.append("resolution", resolution);
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
    if (logoRef.current?.files?.[0]) f.append("logo", logoRef.current.files[0]);
    const jid = await startVideo(f);
    setJobId(jid);
  }

  async function doExportSrt() {
    const r = await exportSrt(voiceOut);
    setToolStatus(r.status);
  }

  async function doChapters() {
    const r = await generateChapters(voiceOut);
    setToolStatus(r.status);
    setChapters(r.chapters);
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
    const r = await savePreset({
      preset_path: presetPath, voice_preset: voicePreset, voice_style: voiceStyle,
      cfg_value: cfgValue, do_normalize: doNormalize, denoise, auto_emotion: autoEmotion,
      speaker_lock: speakerLock, max_workers: maxWorkers, bg_percent: bgPercent,
      auto_amb: autoAmb, bg_sound_query: bgSoundQuery, resolution, fps, crf,
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
    if (data.voice_preset) setVoicePreset(data.voice_preset);
    if (data.voice_style) setVoiceStyle(data.voice_style);
    if (data.cfg_value !== undefined) setCfgValue(data.cfg_value);
    if (data.do_normalize !== undefined) setDoNormalize(data.do_normalize);
    if (data.denoise !== undefined) setDenoise(data.denoise);
    if (data.resolution) setResolution(data.resolution);
    if (data.fps) setFps(data.fps);
    if (data.effect_style) setEffectStyle(data.effect_style);
    setToolStatus("✅ Preset loaded.");
  }

  const TABS: { id: Tab; label: string }[] = [
    { id: "voice", label: "🎙 Voice" },
    { id: "advanced", label: "⚙️ Advanced" },
    { id: "audio", label: "🎵 Audio" },
    { id: "video", label: "🎬 Video" },
    { id: "subtitles", label: "💬 Subtitles" },
    { id: "branding", label: "🎨 Branding" },
    { id: "tools", label: "🛠 Tools" },
  ];

  return (
    <main className="max-w-6xl mx-auto p-8">
      <h1 className="text-2xl font-bold mb-6">🎬 Voice & Video Studio</h1>

      <div className="grid md:grid-cols-[220px_1fr] gap-6">
        {/* Sidebar */}
        <div className="space-y-4">
          <div>
            <label className="label">Story JSON files</label>
            <input ref={storyJsonRef} type="file" accept=".json" multiple className="file-input" />
          </div>
          <div>
            <label className="label">Authors</label>
            <input className="input" value={storyAuthors} onChange={e => setStoryAuthors(e.target.value)} />
          </div>
          <div>
            <label className="label">Voice output</label>
            <input className="input" value={voiceOut} onChange={e => setVoiceOut(e.target.value)} />
          </div>
          <div>
            <label className="label">Segments folder</label>
            <input className="input" value={segmentsOutput} onChange={e => setSegmentsOutput(e.target.value)} />
          </div>
          <div>
            <label className="label">Video output (.mp4)</label>
            <input className="input" value={videoOut} onChange={e => setVideoOut(e.target.value)} placeholder="auto" />
          </div>
          <div>
            <label className="label">Card duration (s): {storyCardDuration}</label>
            <input type="range" min={3} max={5} step={0.5} value={storyCardDuration}
              onChange={e => setStoryCardDuration(+e.target.value)} className="w-full accent-blue-500" />
          </div>
          <button onClick={runVoice} disabled={busy} className="btn-secondary w-full text-sm">
            ▶ Generate Voice
          </button>
          <button onClick={runVideo} disabled={busy} className="btn-primary w-full text-sm">
            🎬 Make Video
          </button>
        </div>

        {/* Main panel */}
        <div>
          {/* Tab bar */}
          <div className="flex gap-1 flex-wrap mb-4 border-b border-gray-800 pb-2">
            {TABS.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                  tab === t.id ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white hover:bg-gray-800"}`}>
                {t.label}
              </button>
            ))}
          </div>

          {/* Voice tab */}
          {tab === "voice" && (
            <div className="space-y-4">
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
              <div>
                <label className="label">Reference voice (optional)</label>
                <input ref={voiceRefRef} type="file" accept="audio/*" className="file-input" />
              </div>
            </div>
          )}

          {/* Advanced tab */}
          {tab === "advanced" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">CFG guidance: {cfgValue}</label>
                  <input type="range" min={1} max={3} step={0.1} value={cfgValue}
                    onChange={e => setCfgValue(+e.target.value)} className="w-full accent-blue-500" />
                </div>
                <div>
                  <label className="label">Max workers: {maxWorkers}</label>
                  <input type="range" min={1} max={2} step={1} value={maxWorkers}
                    onChange={e => setMaxWorkers(+e.target.value)} className="w-full accent-blue-500" />
                </div>
              </div>
              <label className="check"><input type="checkbox" checked={doNormalize} onChange={e => setDoNormalize(e.target.checked)} /> Text normalization</label>
              <label className="check"><input type="checkbox" checked={denoise} onChange={e => setDenoise(e.target.checked)} /> Reference denoising</label>
              <label className="check"><input type="checkbox" checked={autoEmotion} onChange={e => setAutoEmotion(e.target.checked)} /> Different feeling per segment</label>
              <label className="check"><input type="checkbox" checked={speakerLock} onChange={e => setSpeakerLock(e.target.checked)} /> Lock narrator voice (prevents gender drift)</label>
            </div>
          )}

          {/* Audio tab */}
          {tab === "audio" && (
            <div className="space-y-4">
              <div>
                <label className="label">Background music file (optional)</label>
                <input ref={bgMusicRef} type="file" accept="audio/*" className="file-input" />
              </div>
              <div>
                <label className="label">Stock music query</label>
                <input className="input" value={bgSoundQuery} onChange={e => setBgSoundQuery(e.target.value)}
                  placeholder="e.g. dark ambient horror" />
              </div>
              <div>
                <label className="label">Music level: {bgPercent.toFixed(2)}</label>
                <input type="range" min={0} max={0.5} step={0.01} value={bgPercent}
                  onChange={e => setBgPercent(+e.target.value)} className="w-full accent-blue-500" />
              </div>
              <label className="check"><input type="checkbox" checked={autoAmb} onChange={e => setAutoAmb(e.target.checked)} /> Generate dark ambience if no music</label>
            </div>
          )}

          {/* Video tab */}
          {tab === "video" && (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="label">Resolution</label>
                  <select className="input" value={resolution} onChange={e => setResolution(e.target.value)}>
                    {cfg?.resolutions.map(r => <option key={r}>{r}</option>)}
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
                <label className="label">Transition speed (s): {transitionDuration}</label>
                <input type="range" min={0.3} max={3} step={0.1} value={transitionDuration}
                  onChange={e => setTransitionDuration(+e.target.value)} className="w-full accent-blue-500" />
              </div>
              <div>
                <label className="label">Effect style</label>
                <select className="input" value={effectStyle} onChange={e => setEffectStyle(e.target.value)}>
                  {cfg?.effect_styles.map(s => <option key={s}>{s}</option>)}
                </select>
              </div>
              <label className="check"><input type="checkbox" checked={makeThumbnail} onChange={e => setMakeThumbnail(e.target.checked)} /> Generate thumbnail</label>
              <label className="check"><input type="checkbox" checked={useAiImages} onChange={e => setUseAiImages(e.target.checked)} /> Generate AI images with DALL-E 3</label>
            </div>
          )}

          {/* Subtitles tab */}
          {tab === "subtitles" && (
            <div className="space-y-4">
              <label className="check"><input type="checkbox" checked={enableSubtitles} onChange={e => setEnableSubtitles(e.target.checked)} /> Burn captions into video</label>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Font size: {subtitleSize}px</label>
                  <input type="range" min={14} max={48} step={2} value={subtitleSize}
                    onChange={e => setSubtitleSize(+e.target.value)} className="w-full accent-blue-500" />
                </div>
                <div>
                  <label className="label">Position</label>
                  <select className="input" value={subtitlePosition} onChange={e => setSubtitlePosition(e.target.value)}>
                    {cfg?.subtitle_positions.map(p => <option key={p}>{p}</option>)}
                  </select>
                </div>
              </div>
            </div>
          )}

          {/* Branding tab */}
          {tab === "branding" && (
            <div className="space-y-4">
              <label className="check"><input type="checkbox" checked={showTitle} onChange={e => setShowTitle(e.target.checked)} /> Show story title card</label>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Channel name</label>
                  <input className="input" value={channel} onChange={e => setChannel(e.target.value)} placeholder="Mr.Midnight" />
                </div>
                <div>
                  <label className="label">Channel corner</label>
                  <select className="input" value={channelCorner} onChange={e => setChannelCorner(e.target.value)}>
                    {cfg?.logo_corners.map(c => <option key={c}>{c}</option>)}
                  </select>
                </div>
              </div>
              <label className="check"><input type="checkbox" checked={useLogo} onChange={e => setUseLogo(e.target.checked)} /> Overlay logo image</label>
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
            </div>
          )}

          {/* Tools tab */}
          {tab === "tools" && (
            <div className="space-y-6">
              <div>
                <p className="text-xs text-gray-400 mb-2">Export SRT subtitles from last voice timeline</p>
                <button onClick={doExportSrt} className="btn-secondary text-sm">📝 Export SRT</button>
              </div>
              <div>
                <p className="text-xs text-gray-400 mb-2">Generate YouTube chapter markers</p>
                <button onClick={doChapters} className="btn-secondary text-sm">📋 Generate Chapters</button>
                {chapters && (
                  <textarea readOnly value={chapters} rows={6}
                    className="mt-2 w-full input text-xs font-mono" />
                )}
              </div>
              <div>
                <p className="text-xs text-gray-400 mb-2">Preview one segment</p>
                <div className="flex gap-2 items-center">
                  <input type="number" min={0} value={segmentIndex}
                    onChange={e => setSegmentIndex(+e.target.value)}
                    className="input w-20 text-sm" />
                  <button onClick={doPreview} className="btn-secondary text-sm">▶ Preview</button>
                </div>
                <LogStream jobId={previewJobId} />
              </div>
              <div>
                <p className="text-xs text-gray-400 mb-2">Settings presets</p>
                <div className="flex gap-2">
                  <input className="input flex-1 text-sm" value={presetPath}
                    onChange={e => setPresetPath(e.target.value)} />
                  <button onClick={doSavePreset} className="btn-secondary text-sm">💾 Save</button>
                  <button onClick={doLoadPreset} className="btn-secondary text-sm">📂 Load</button>
                </div>
              </div>
              {toolStatus && <p className="text-xs text-gray-300">{toolStatus}</p>}
            </div>
          )}

          {/* Log output */}
          <LogStream jobId={jobId} onDone={() => setBusy(false)} />
        </div>
      </div>
    </main>
  );
}
