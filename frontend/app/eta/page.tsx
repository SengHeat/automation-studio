"use client";
import { useState, useEffect, useRef } from "react";
import { Clock, Menu } from "lucide-react";
import { useSidebar } from "@/components/ui/Sidebar";
import { estimateEta } from "@/lib/api";

function extractTextFromStoryJson(data: Record<string, unknown>): string {
  const segs: Array<{ target_text?: string; narration?: string }> =
    (data.segments as Array<{ target_text?: string; narration?: string }>) ??
    (data.stories as Array<{ segments: Array<{ target_text?: string; narration?: string }> }>)
      ?.flatMap(s => s.segments) ?? [];
  return segs.map(s => s.target_text ?? s.narration ?? "").filter(Boolean).join("\n\n");
}

interface ParsedResult {
  mins: number;
  secs: number;
  totalSecs: number;
  words: number;
  chars: number;
  segments: number;
  script: string;
  wpm: number;
  cpm: number;
  isKhmerCjk: boolean;
}

function parseEtaResult(total: string, breakdown: string, rawText: string, wpm: number, cpm: number): ParsedResult | null {
  const tm = total.match(/(\d+)\s*min\s*(\d+)\s*sec/);
  if (!tm) return null;
  const mins = +tm[1], secs = +tm[2];
  const totalSecs = mins * 60 + secs;

  let words = 0, chars = 0, segments = 0;
  for (const line of breakdown.split("\n").filter(l => l.trim())) {
    const m = line.match(/(\d+)w\s*\/\s*(\d+)c/);
    if (m) { words += +m[1]; chars += +m[2]; segments++; }
  }

  // Detect by actual Unicode ranges in the source text — never misfire on English
  const isKhmerCjk = /[\u1780-\u17FF\u3000-\u9FFF\uAC00-\uD7AF]/.test(rawText);
  const script = isKhmerCjk ? "Khmer / CJK" : "Latin / English";

  return { mins, secs, totalSecs, words, chars, segments, script, wpm, cpm, isKhmerCjk };
}

interface FormatCheck { label: string; limit: number; unit: string }
const FORMATS: FormatCheck[] = [
  { label: "YouTube short-form", limit: 180, unit: "3:00" },
  { label: "TikTok / Reels",     limit: 180, unit: "3:00" },
  { label: "Instagram feed (60s)", limit: 60, unit: "1:00" },
];

function formatTime(secs: number) {
  return `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
}

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

export default function EtaPage() {
  const { setOpen: setSidebarOpen } = useSidebar();
  const [text, setText] = useState("");
  const [jsonFileName, setJsonFileName] = useState("");
  const [wpm, setWpm] = useState(130);
  const jsonFileRef = useRef<HTMLInputElement>(null);
  const [cpm, setCpm] = useState(280);
  const [result, setResult] = useState<ParsedResult | null>(null);
  const [rawBreakdown, setRawBreakdown] = useState("");
  const [busy, setBusy] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function handleJsonFile(file: File) {
    setJsonFileName(file.name);
    try {
      const raw = await file.text();
      const data = JSON.parse(raw);
      const extracted = extractTextFromStoryJson(data as Record<string, unknown>);
      if (extracted) setText(extracted);
    } catch { /* ignore parse errors */ }
  }

  // Auto-estimate as text changes (debounced)
  useEffect(() => {
    if (!text.trim()) { setResult(null); return; }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setBusy(true);
      try {
        const res = await estimateEta({ text, wpm, cpm });
        setRawBreakdown(res.breakdown);
        setResult(parseEtaResult(res.total, res.breakdown, text, wpm, cpm));
      } catch { /* ignore */ }
      setBusy(false);
    }, 600);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, wpm, cpm]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    const res = await estimateEta({ text, wpm, cpm });
    setRawBreakdown(res.breakdown);
    setResult(parseEtaResult(res.total, res.breakdown, text, wpm, cpm));
    setBusy(false);
  }

  return (
    <div className="flex flex-col md:h-screen md:overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 md:px-6 py-3.5 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={() => setSidebarOpen(true)} className="md:hidden p-1 text-gray-400 hover:text-gray-200">
            <Menu size={18} />
          </button>
          <Clock size={18} className="text-gray-400" />
          <span className="text-sm font-semibold text-gray-100">ETA Duration Estimator</span>
          <span className="text-xs text-gray-500 hidden md:block">Estimate narration time at TTS pace</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-blue-400">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
          Live
        </div>
      </div>

      <div className="flex flex-col md:flex-row md:flex-1 md:overflow-hidden">
        {/* ── Left ─────────────────────────────────── */}
        <div className="flex flex-col w-full md:w-[58%] min-w-0 border-b md:border-b-0 md:border-r border-gray-800 md:overflow-hidden">
          <form onSubmit={submit} className="flex flex-col flex-1 overflow-hidden">
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              <Section num="01" title="Script input">
                <div>
                  <label className="label">Paste plain text</label>
                  <textarea
                    className="input resize-none"
                    rows={8}
                    value={text}
                    onChange={e => setText(e.target.value)}
                    placeholder="The house had been empty for years. No one remembered who lived there, or why they left in such a hurry. Until the night the lights came back on…"
                  />
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex-1 h-px bg-gray-800" />
                  <span className="text-[10px] text-gray-600 font-mono">OR</span>
                  <div className="flex-1 h-px bg-gray-800" />
                </div>
                <div>
                  <label className="label">Story JSON file</label>
                  <input ref={jsonFileRef} type="file" accept=".json" className="sr-only"
                    onChange={e => { if (e.target.files?.[0]) handleJsonFile(e.target.files[0]); }} />
                  <button type="button" onClick={() => jsonFileRef.current?.click()}
                    className="w-full flex items-center gap-3 rounded-lg border-2 border-dashed border-gray-700 hover:border-gray-600 px-4 py-3 text-left transition-colors">
                    <svg className="w-4 h-4 text-gray-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                    </svg>
                    <span className={`text-xs ${jsonFileName ? "text-green-400" : "text-gray-500"}`}>
                      {jsonFileName || "Browse story.json…"}
                    </span>
                  </button>
                </div>
              </Section>

              <Section num="02" title="Pace">
                <div>
                  <div className="flex justify-between mb-1.5">
                    <span className="text-xs text-gray-400">Words/min (Latin)</span>
                    <span className="text-xs font-mono text-blue-400">{wpm}</span>
                  </div>
                  <input type="range" min={80} max={200} step={5} value={wpm}
                    onChange={e => setWpm(+e.target.value)} className="w-full accent-blue-500 h-1" />
                </div>
                <div>
                  <div className="flex justify-between mb-1.5">
                    <span className="text-xs text-gray-400">Chars/min (Khmer/CJK)</span>
                    <span className="text-xs font-mono text-blue-400">{cpm}</span>
                  </div>
                  <input type="range" min={150} max={500} step={10} value={cpm}
                    onChange={e => setCpm(+e.target.value)} className="w-full accent-blue-500 h-1" />
                </div>
              </Section>
            </div>

            {/* Submit button */}
            <div className="p-5 border-t border-gray-800 shrink-0">
              <button type="submit" disabled={busy || !text.trim()}
                className="w-full flex items-center justify-center gap-2 rounded-xl bg-blue-600 py-3 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50 transition-colors shadow-lg">
                <Clock size={14} />
                {busy ? "Estimating…" : "Estimate Duration"}
              </button>
            </div>
          </form>
        </div>

        {/* ── Right: Estimate ─────────────────────── */}
        <div className="flex flex-col w-full md:w-[42%] min-w-0 bg-gray-950 overflow-y-auto">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-800 shrink-0">
            <span className="text-sm font-semibold text-gray-200">Estimate</span>
            <div className="flex items-center gap-1.5 text-xs text-blue-400">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
              Live
            </div>
          </div>

          <div className="p-5 space-y-3 flex-1">
            {result ? (<>
              {/* Big time card */}
              <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-6 text-center">
                <p className="text-[10px] font-mono tracking-widest text-gray-500 mb-3">ESTIMATED NARRATION</p>
                <p className="text-6xl font-bold text-gray-100 tracking-tight">
                  {result.mins}:{String(result.secs).padStart(2, "0")}
                </p>
                <p className="text-xs text-gray-500 mt-2">
                  min : sec · at{" "}
                  {result.isKhmerCjk
                    ? <><span className="text-yellow-400 font-mono">{result.cpm} cpm</span> (Khmer/CJK)</>
                    : <><span className="text-blue-400 font-mono">{result.wpm} wpm</span> (English)</>
                  }
                </p>
              </div>

              {/* Khmer/CJK notice */}
              {result.isKhmerCjk && (
                <div className="rounded-lg border border-yellow-800/50 bg-yellow-950/30 px-4 py-3 flex gap-3 items-start">
                  <span className="text-yellow-400 text-base shrink-0">⚠</span>
                  <div className="space-y-0.5">
                    <p className="text-xs font-medium text-yellow-300">Khmer / CJK Script Detected</p>
                    <p className="text-[11px] text-yellow-500 leading-relaxed">
                      ប្រើ <strong>{result.cpm} chars/min</strong> ជំនួស wpm — ព្រោះ Khmer មិនគណនា​ ដោយ word ។
                    </p>
                    <p className="text-[11px] text-yellow-600">
                      Using character rate ({result.cpm} cpm), not word rate. Adjust the Chars/min slider for accuracy.
                    </p>
                  </div>
                </div>
              )}

              {/* Stats row */}
              <div className="grid grid-cols-3 gap-2">
                <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4 text-center">
                  <p className="text-2xl font-bold text-gray-100">{result.words.toLocaleString()}</p>
                  <p className="text-[10px] text-gray-500 mt-1">Words</p>
                </div>
                <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4 text-center">
                  <p className="text-2xl font-bold text-gray-100">{result.chars.toLocaleString()}</p>
                  <p className="text-[10px] text-gray-500 mt-1">Characters</p>
                </div>
                <div className={`rounded-xl border p-4 text-center ${result.isKhmerCjk ? "border-yellow-800/40 bg-yellow-950/20" : "border-gray-800 bg-gray-900/60"}`}>
                  <p className={`text-sm font-bold ${result.isKhmerCjk ? "text-yellow-400" : "text-gray-100"}`}>
                    {result.isKhmerCjk ? "Khmer / CJK" : "Latin"}
                  </p>
                  <p className="text-[10px] text-gray-500 mt-1">Script detected</p>
                </div>
              </div>

              {/* Format fit */}
              <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4 space-y-2.5">
                <p className="text-xs font-semibold text-gray-200 mb-3">Fits these formats</p>
                {FORMATS.map(fmt => {
                  const over = result.totalSecs - fmt.limit;
                  const fits = over <= 0;
                  return (
                    <div key={fmt.label} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className={`w-4 h-4 rounded-full flex items-center justify-center shrink-0 ${fits ? "bg-green-500/20" : "bg-yellow-500/20"}`}>
                          {fits
                            ? <svg className="w-2.5 h-2.5 text-green-400" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                            : <svg className="w-2.5 h-2.5 text-yellow-400" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" /></svg>}
                        </div>
                        <span className="text-xs text-gray-300">{fmt.label}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-gray-600">≤ {fmt.unit}</span>
                        {!fits && (
                          <span className="text-[10px] font-mono text-yellow-400">over by {formatTime(over)}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {rawBreakdown && (
                <details className="rounded-xl border border-gray-800 overflow-hidden">
                  <summary className="px-4 py-3 text-xs text-gray-400 cursor-pointer hover:text-gray-200 bg-gray-900/40">
                    Segment breakdown
                  </summary>
                  <pre className="p-4 text-[10px] font-mono text-gray-500 overflow-x-auto whitespace-pre">{rawBreakdown}</pre>
                </details>
              )}

              <p className="text-[10px] text-gray-600 flex items-center gap-1.5 pb-2">
                <svg className="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Estimate assumes steady TTS pace with default pauses.
              </p>
            </>) : (
              <div className="flex flex-col items-center justify-center h-full text-gray-700 py-24">
                <Clock size={36} className="mb-3 opacity-30" />
                <p className="text-sm">Paste a script to estimate duration</p>
                <p className="text-xs mt-1 opacity-60">Updates live as you type</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
