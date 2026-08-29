#!/usr/bin/env python3
"""
Horror Voice & Video Studio (Updated Parallel Version)
VoxCPM2 + edge-tts fallback, parallel voice generation, and built-in video rendering.
"""

import os, re, json, math, glob, shutil, subprocess, tempfile, threading, queue, traceback, time, random
import urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext

FFMPEG  = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
PEXELS_KEY = "kqyiphoOwFOqKzdi8kGKKeDOjw0xJa1ou7ubp0d1Sdhc0UOEbNpe9ZgS"
STORY_CARD_BG = "/Users/macbook/DRSB-Workplace/NightFallFiles/story_card_bg.MP3"

TENSE = ["hush","tense","dread","fear","terr","slow","dramatic","whisper","ominous",
         "chilling","shock","horror","unsettl","grave","weight","eerie","somber","deeply"]
FAST  = ["urgent","fast","chaos","intensity","frantic","escalat","rapid","quick","action"]
WARM  = ["warm","welcom","calm","conversational","friendly","gentle"]

# ─── Voice presets ──────────────────────────────────────────────────────────

VOICE_PRESETS = {
    "Balanced Neutral": "Natural, neutral voice with a calm and even tone. Keep the same pitch, volume, vocal identity, and speaking pace throughout. Speak clearly and steadily without emotional extremes.",
    "Gentle Narrator": "A soft, warm voice with a gentle and soothing quality. Calm and reassuring without being overly emotional.",
    "Professional Announcer": "Clear, well-modulated voice with balanced tone. Authoritative but not aggressive.",
    "Calm Storyteller": "Steady, measured voice with natural warmth. Engaging without being dramatic.",
    "Neutral Female": "Natural female voice with balanced pitch and tone. Clear and pleasant without emotional coloring.",
    "Neutral Male": "Natural male voice with even tone. Relaxed and professional without being monotone.",
    "Soft Spoken": "Quiet, gentle voice with a soft quality. Warm but restrained.",
}

VOICE_STYLES = {
    "Balanced": "balanced, natural, even-toned, steady",
    "Calm": "calm, composed, steady, measured",
    "Neutral": "neutral, even, balanced, natural",
    "Warm": "warm, gentle, friendly, pleasant",
    "Clear": "clear, articulate, distinct, well-paced",
    "Professional": "professional, polished, authoritative, confident",
    "Narrative": "narrative, flowing, steady, engaging",
    "Soft": "soft, gentle, quiet, intimate",
}

EMOTION_DIRECTIONS = {
    "neutral": "Remain natural, balanced, and emotionally restrained.",
    "calm": "Speak calmly and gently with an even pace.",
    "mysterious": "Sound mysterious and intimate, with deliberate pauses and quiet suspense.",
    "tense": "Build restrained tension; speak carefully with an uneasy, suspenseful tone.",
    "fear": "Sound genuinely frightened and vulnerable, with controlled urgency.",
    "sad": "Speak softly with grief, heaviness, and subdued emotion.",
    "angry": "Use controlled anger and firm emphasis without shouting.",
    "urgent": "Speak urgently with a quicker pace and clear, forceful emphasis.",
    "shocked": "Sound startled and disbelieving, then regain control naturally.",
    "ominous": "Use a low, grave, foreboding delivery with measured pacing.",
}

EMOTION_HINTS = {
    "fear": ("afraid", "fear", "terrified", "panic", "trembl", "scream"),
    "urgent": ("hurry", "run", "quick", "urgent", "immediately", "escape"),
    "shocked": ("suddenly", "shock", "couldn't believe", "could not believe", "gasp"),
    "sad": ("sad", "grief", "cry", "cried", "tears", "died", "death", "lost", "losing"),
    "angry": ("angry", "rage", "furious", "shouted", "yelled"),
    "ominous": ("dark", "death", "grave", "curse", "blood", "shadow"),
    "tense": ("slowly", "footstep", "behind", "door", "silence", "waiting"),
    "mysterious": ("mystery", "unknown", "whisper", "strange", "secret"),
    "calm": ("calm", "peace", "gentle", "quiet", "safe"),
}


def segment_emotion(seg, auto_detect=True):
    """Return (emotion name, Vox direction), preferring explicit JSON metadata."""
    explicit = next((str(seg.get(k, "")).strip().lower()
                     for k in ("emotion", "feeling", "mood", "voice_emotion")
                     if str(seg.get(k, "")).strip()), "")
    for name, direction in EMOTION_DIRECTIONS.items():
        if name in explicit:
            return name, direction
    if explicit:
        return explicit, f"Express this segment as {explicit}, naturally and without exaggeration."
    if auto_detect:
        sample = " ".join(str(seg.get(k, "")) for k in
                          ("title", "target_text", "control_instruction")).lower()
        for name, hints in EMOTION_HINTS.items():
            if any(hint in sample for hint in hints):
                return name, EMOTION_DIRECTIONS[name]
    return "neutral", EMOTION_DIRECTIONS["neutral"]

# ─── shared helpers ─────────────────────────────────────────────────────────

def audio_dur(p):
    o = subprocess.run([FFPROBE,"-v","error","-show_entries","format=duration","-of","json",p],
                       capture_output=True, text=True)
    return float(json.loads(o.stdout)["format"]["duration"])

def num_key(p):
    d = re.findall(r"\d+", os.path.basename(p)); return int(d[0]) if d else 0


def normalize_audio_lufs(source, output=None):
    """Normalize audio without ever overwriting the source in place."""
    if not FFMPEG or not source or not os.path.exists(source):
        return False
    destination = output or source
    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp.close()
    try:
        result = subprocess.run(
            [FFMPEG, "-y", "-i", source,
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=7",
             "-c:a", "libmp3lame", "-b:a", "192k", tmp.name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
        if result.returncode != 0 or os.path.getsize(tmp.name) <= 1500:
            return False
        shutil.move(tmp.name, destination)
        return True
    finally:
        if os.path.exists(tmp.name):
            try: os.unlink(tmp.name)
            except OSError: pass


def split_voice_text(text, max_words=30, max_chars=220):
    """Sentence-aware chunks of roughly 15 seconds of narration."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?។៕])\s+", text)
    chunks, current = [], ""

    def fits(value):
        return len(value.split()) <= max_words and len(value) <= max_chars

    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and not fits(candidate):
            chunks.append(current)
            current = ""
        if fits(sentence):
            current = f"{current} {sentence}".strip()
            continue

        # Long sentences: split by words; Khmer/unspaced text.txt falls back to chars.
        words = sentence.split()
        if len(words) > 1:
            buf = []
            for word in words:
                candidate = " ".join(buf + [word])
                if buf and not fits(candidate):
                    chunks.append(" ".join(buf))
                    buf = [word]
                else:
                    buf.append(word)
            current = " ".join(buf)
        else:
            pieces = [sentence[i:i + max_chars] for i in range(0, len(sentence), max_chars)]
            chunks.extend(pieces[:-1])
            current = pieces[-1] if pieces else ""
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def merge_voice_chunks(parts, output):
    """Join Vox chunks into one clean MP3 without gaps from mixed encodings."""
    if len(parts) == 1:
        shutil.move(parts[0], output)
        return True
    manifest = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
    try:
        for part in parts:
            manifest.write("file '" + os.path.abspath(part).replace("'", "'\\''") + "'\n")
        manifest.close()
        result = subprocess.run(
            [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", manifest.name,
             "-c:a", "libmp3lame", "-b:a", "192k", output],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
        return result.returncode == 0 and os.path.exists(output) and os.path.getsize(output) > 1500
    finally:
        if not manifest.closed:
            manifest.close()
        try:
            os.unlink(manifest.name)
        except OSError:
            pass

# Thread-safe logging
_log_lock = threading.Lock()
def safe_log(log, msg):
    with _log_lock:
        log(msg)

# ─── STEP 1: voice generation (PARALLEL) ────────────────────────────────────

VOXCPM2_URLS = [
    "https://openbmb-voxcpm-demo.hf.space",
    "openbmb/VoxCPM-Demo",
]

def generate_single_segment_retry(client, has_ref, seg, full_ci, out_mp3, voice_ref,
                                  cfg_value, do_normalize, denoise, log, max_retries=4,
                                  text_override=None, label=None):
    """Generate a single segment with retries (thread-safe)"""
    sid = int(seg.get("segment_id", 0))
    text = (text_override if text_override is not None else seg.get("target_text") or "").strip()
    display = label or f"seg {sid:02d}"

    if not text:
        return False

    # Avoid a retry stampede against the public Space. Each worker begins at a
    # slightly different time and transient failures receive exponential backoff.
    time.sleep(random.uniform(0.0, 0.8))
    for attempt in range(1, max_retries + 1):
        try:
            from gradio_client import handle_file

            kwargs = {
                "text_input": text,
                "control_instruction": full_ci,
                "reference_wav_path_input": None,
                "use_prompt_text": False,
                "prompt_text_input": "",
                "cfg_value_input": float(cfg_value),
                "do_normalize": bool(do_normalize),
                "denoise": bool(denoise),
                "api_name": "/generate",
            }

            if has_ref:
                kwargs["reference_wav_path_input"] = handle_file(voice_ref)

            result = client.predict(**kwargs)

            if not result:
                raise RuntimeError("Empty result from API")

            # Extract audio path
            audio_path = None
            if isinstance(result, (list, tuple)) and result:
                audio_path = result[0]
            elif isinstance(result, dict):
                audio_path = result.get("audio") or result.get("output") or result.get("path")
            else:
                audio_path = str(result)

            if not audio_path or not os.path.exists(str(audio_path)):
                raise RuntimeError(f"No valid audio: {audio_path}")

            subprocess.run(
                [FFMPEG, "-y", "-i", str(audio_path),
                 "-af", "loudnorm=I=-16:TP=-1.5:LRA=7",
                 "-c:a", "libmp3lame", "-b:a", "192k", out_mp3],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=45
            )

            if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1500:
                safe_log(log, f"    ✅ {display} (attempt {attempt})")
                return True
            else:
                raise RuntimeError("Output too small / missing")

        except Exception as e:
            error = str(e)
            if attempt < max_retries:
                delay = min(20.0, (2 ** attempt) + random.uniform(0.5, 2.0))
                safe_log(log, f"    ⚠️ {display} attempt {attempt}: {error[:45]} → retry in {delay:.1f}s")
                time.sleep(delay)
            else:
                safe_log(log, f"   ❌ {display}: {error[:70]}")

    return False


def generate_voice_voxcpm2(segments, voice_ref, out_folder, log, voice_cfg, max_workers=2):
    """Generate voice using VoxCPM2 — PARALLEL"""
    try:
        from gradio_client import Client
    except ImportError:
        log("❌ gradio_client not installed. Run: pip install gradio_client")
        return []
    except Exception as e:
        log(f"❌ gradio_client import error: {e}")
        return []

    os.makedirs(out_folder, exist_ok=True)

    client = None
    for url in VOXCPM2_URLS:
        try:
            log(f"  Connecting to {url} ...")
            client = Client(url, verbose=False)
            log(f"  ✅ Connected to {url}")
            break
        except Exception as e:
            log(f"  ⚠️ Failed: {str(e)[:80]}")
            continue

    if client is None:
        log("❌ Could not connect to VoxCPM2. Will try fallback.")
        return []

    has_ref = bool(voice_ref and os.path.exists(voice_ref))
    if has_ref:
        log(f"  Mode: Cloning (ref: {os.path.basename(voice_ref)})")
    else:
        log("  Mode: Voice Design")

    voice_preset = voice_cfg.get("voice_preset", "")
    voice_style  = voice_cfg.get("voice_style", "")
    cfg_value    = float(voice_cfg.get("cfg_value", 2.0))
    do_normalize = voice_cfg.get("do_normalize", False)
    denoise      = voice_cfg.get("denoise", False)
    auto_emotion = voice_cfg.get("auto_emotion", True)
    speaker_lock = voice_cfg.get("speaker_lock", True)

    if voice_preset and voice_preset in VOICE_PRESETS:
        control_desc = VOICE_PRESETS[voice_preset]
        if voice_style and voice_style in VOICE_STYLES:
            control_desc = f"{control_desc} Also {VOICE_STYLES[voice_style]}."
    elif voice_style and voice_style in VOICE_STYLES:
        control_desc = VOICE_STYLES[voice_style]
    else:
        control_desc = "Natural, balanced, conversational voice."

    log(f"  Control: {control_desc[:60]}...")
    # Public HF Spaces are queue-backed and become unreliable under a burst of
    # concurrent uploads. Two requests still give parallelism without flooding it.
    requested_workers = max(1, int(max_workers))
    max_workers = min(requested_workers, 2)
    if requested_workers != max_workers:
        log(f"  ℹ️ Workers capped at {max_workers} for VoxCPM2 public-space stability")
    log(f"  CFG: {cfg_value:.1f} | Parallel workers: {max_workers}")

    # Prepare jobs
    jobs = []
    existing = []
    for seg in segments:
        sid = int(seg.get("segment_id", 0))
        text = (seg.get("target_text") or "").strip()
        if not text:
            continue
        seg_ci = (seg.get("control_instruction") or "").strip()
        emotion, emotion_ci = segment_emotion(seg, auto_emotion)
        consistency_ci = ("Use exactly one narrator identity for the entire production. Never act as "
                          "another character. Never change gender, age, accent, vocal identity, pitch range, "
                          "or vocal weight for dialogue. Read quoted speech in the same narrator voice. "
                          "Express emotion only through subtle pacing and emphasis.")
        # A JSON control_instruction may request character acting or a different
        # age/gender. Under speaker lock it must not override narrator identity.
        instruction_parts = (control_desc, emotion_ci, consistency_ci) if speaker_lock else (
            control_desc, emotion_ci, seg_ci, consistency_ci)
        full_ci = " ".join(p for p in instruction_parts if p).strip()
        log(f"    🎭 seg {sid:02d} feeling: {emotion}")
        out_mp3 = os.path.join(out_folder, f"{sid:02d}.mp3")
        if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1500:
            log(f"    ⏭️ seg {sid:02d} already exists")
            existing.append(sid)
            continue
        jobs.append((sid, seg, full_ci, out_mp3))

    total = len(jobs)
    if total == 0:
        log("  All segments already exist." if existing else "  No text.txt segments to generate.")
        return existing

    log(f"  🚀 Launching {total} segments in parallel (max {max_workers} workers)...")

    generated = list(existing)
    completed = 0

    active_ref = [voice_ref]
    active_has_ref = [has_ref]

    def _generate_job(item, retries=3):
        sid, seg, full_ci, out_mp3 = item
        chunks = split_voice_text(seg.get("target_text", ""))
        if len(chunks) > 1:
            safe_log(log, f"    ✂️ seg {sid:02d}: {len(chunks)} chunks (~15s maximum each)")
        parts = []
        for index, chunk in enumerate(chunks, 1):
            part = out_mp3 + f".part{index:02d}.mp3"
            label = f"seg {sid:02d} chunk {index}/{len(chunks)}"
            if not generate_single_segment_retry(
                    client, active_has_ref[0], seg, full_ci, part, active_ref[0],
                    cfg_value, do_normalize, denoise, log, max_retries=retries,
                    text_override=chunk, label=label):
                for made in parts:
                    try: os.unlink(made)
                    except OSError: pass
                return sid, False
            parts.append(part)
        success = bool(parts) and merge_voice_chunks(parts, out_mp3)
        for part in parts:
            if os.path.exists(part):
                try: os.unlink(part)
                except OSError: pass
        return sid, success

    def _worker(item):
        return _generate_job(item, retries=3)

    # With no user reference, create one anchor segment first and clone it for
    # every other request. This prevents VoxCPM from redesigning a new speaker.
    if speaker_lock and not has_ref and jobs:
        anchor_job = jobs.pop(0)
        anchor_sid, anchor_ok = _generate_job(anchor_job, retries=4)
        completed += 1
        if anchor_ok:
            generated.append(anchor_sid)
            active_ref[0] = anchor_job[3]
            active_has_ref[0] = True
            log(f"  🔒 Narrator locked from seg {anchor_sid:02d}; cloning this voice for all remaining segments")
        else:
            log("❌ Could not create narrator anchor; stopped to prevent mixed voices.")
            return generated

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_worker, job): job[0] for job in jobs}
        for future in as_completed(futures):
            sid, success = future.result()
            completed += 1
            if success:
                generated.append(sid)
            safe_log(log, f"  Progress: {completed}/{total}  (new ok: {len(generated) - len(existing)})")

    # A quiet, single-worker recovery pass is much more successful than falling
    # back immediately after the Space has just been saturated.
    failed_jobs = [job for job in jobs if job[0] not in generated]
    if failed_jobs:
        log(f"  🩹 Recovery pass: {len(failed_jobs)} failed segment(s), one at a time...")
        time.sleep(3)
        for job in failed_jobs:
            sid, success = _generate_job(job, retries=2)
            if success:
                generated.append(sid)

    log(f"  VoxCPM2 done: {len(generated)}/{total + len(existing)} segments")
    return generated


def generate_voice_edge(segments, out_folder, log, missing_ids=None):
    """Generate voice using edge-tts (fallback)"""
    try:
        import edge_tts
        import asyncio
    except ImportError:
        log("⚠️ edge-tts not installed. Try: pip install edge-tts")
        return []

    os.makedirs(out_folder, exist_ok=True)
    log("  Using edge-tts fallback...")

    voice = "en-US-JennyNeural"
    generated = []

    targets = missing_ids if missing_ids else [int(s.get("segment_id", 0)) for s in segments]

    for seg in segments:
        sid = int(seg.get("segment_id", 0))
        if sid not in targets:
            continue

        text = (seg.get("target_text") or "").strip()
        if not text:
            continue

        out_mp3 = os.path.join(out_folder, f"{sid:02d}.mp3")
        log(f"  edge-tts seg {sid:02d}")

        success = False
        for attempt in range(1, 4):
            try:
                async def generate():
                    comm = edge_tts.Communicate(text, voice, rate="+0%", pitch="+0Hz")
                    await comm.save(out_mp3)

                asyncio.run(generate())

                if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1500:
                    if not normalize_audio_lufs(out_mp3):
                        raise RuntimeError("Edge-TTS loudness normalization failed")
                    generated.append(sid)
                    success = True
                    log(f"    ✅ seg {sid:02d} (edge-tts attempt {attempt}, -16 LUFS)")
                    break

            except Exception as e:
                if attempt < 3:
                    log(f"    ⚠️ edge-tts attempt {attempt} failed, retrying...")
                    time.sleep(1.5)
                else:
                    log(f"   ❌ seg {sid:02d}: {str(e)[:60]}")

        if not success:
            try:
                subprocess.run([
                    FFMPEG, "-y", "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=22050",
                    "-t", "4", "-c:a", "libmp3lame", "-b:a", "192k", out_mp3
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if os.path.exists(out_mp3):
                    log(f"    🔇 Created silent placeholder for seg {sid:02d}")
            except Exception:
                pass

        time.sleep(0.2)

    log(f"  edge-tts: {len(generated)}/{len(targets)} segments")
    return generated


def generate_voice(segments, voice_ref, out_folder, log, voice_cfg, max_workers=2):
    """Generate voice - try VoxCPM2 parallel first, then edge-tts for missing ones"""
    log("  Attempting VoxCPM2 (parallel)...")
    generated = generate_voice_voxcpm2(segments, voice_ref, out_folder, log, voice_cfg, max_workers)

    all_ids = [int(s.get("segment_id", 0)) for s in segments if s.get("target_text", "").strip()]
    missing = [sid for sid in all_ids if sid not in generated]

    if missing:
        log(f"  ⚠️ {len(missing)} segments failed in VoxCPM2 → edge-tts fallback...")
        edge_generated = generate_voice_edge(segments, out_folder, log, missing)
        generated.extend(edge_generated)

    final_missing = [sid for sid in all_ids if sid not in generated]
    if final_missing:
        log(f"  ⚠️ {len(final_missing)} segments still missing → creating silence: {final_missing}")
        for sid in final_missing:
            out_mp3 = os.path.join(out_folder, f"{sid:02d}.mp3")
            try:
                subprocess.run([
                    FFMPEG, "-y", "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=22050",
                    "-t", "5", "-c:a", "libmp3lame", "-b:a", "192k", out_mp3
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if os.path.exists(out_mp3):
                    log(f"    🔇 silence for seg {sid:02d}")
                    generated.append(sid)
            except Exception:
                pass

    return len(generated) > 0


# ─── STEP 2: merge with feeling + bg music ──────────────────────────────────

def mood_pause(ci, base, longx, short):
    c = (ci or "").lower()
    if any(w in c for w in FAST): return short
    if any(w in c for w in TENSE): return base + longx
    return base

def build_ambience(total_ms):
    """Synthesize a dark ambient drone bed"""
    import numpy as np
    from pydub import AudioSegment
    fr = 22050
    loop = 24
    n = loop * fr
    t = np.arange(n) / fr
    drone = (0.5 * np.sin(2 * np.pi * 55 * t) +
             0.4 * np.sin(2 * np.pi * 82.41 * t) +
             0.3 * np.sin(2 * np.pi * 110 * t))
    lfo = 0.6 + 0.4 * np.sin(2 * np.pi * (1.0 / loop) * t)
    drone *= lfo
    ln = loop * 40
    nz = np.random.normal(0, 1, ln)
    wind = 0.15 * np.interp(np.linspace(0, ln - 1, n), np.arange(ln), nz)
    mix = drone + wind
    mix /= (np.max(np.abs(mix)) + 1e-6)
    data = (mix * 0.5 * 32767).astype(np.int16)
    seg = AudioSegment(data.tobytes(), frame_rate=fr, sample_width=2, channels=1)
    full = seg
    while len(full) < total_ms:
        full = full.append(seg, crossfade=1000)
    return full[:total_ms]

def merge_voice(clips_folder, segments, out_voice, bg_music, bg_percent, log,
                auto_amb=False, save_segments_to=None):
    from pydub import AudioSegment
    from pydub.effects import compress_dynamic_range
    from pydub.utils import which as _w
    AudioSegment.converter = _w("ffmpeg")

    # Keep narration centered and give every generated segment a similar
    # perceived level before the final program-wide LUFS normalization.
    target_voice_dbfs = -20.0

    def balance_voice_clip(clip):
        clip = clip.set_channels(1)
        clip = compress_dynamic_range(
            clip, threshold=-24.0, ratio=3.0, attack=8.0, release=100.0)
        if math.isfinite(clip.dBFS):
            # Avoid excessively boosting a very quiet/noisy recording.
            gain = max(-8.0, min(8.0, target_voice_dbfs - clip.dBFS))
            clip = clip.apply_gain(gain)
        return clip.fade_in(40).fade_out(40)

    clips = sorted(glob.glob(os.path.join(clips_folder, "*.mp3")), key=num_key)
    if bg_music:
        clips = [c for c in clips if os.path.abspath(c) != os.path.abspath(bg_music)]

    if not clips:
        log("❌ no voice clips to merge.")
        return None

    if save_segments_to:
        os.makedirs(save_segments_to, exist_ok=True)
        log(f"  📁 Saving individual segments to: {save_segments_to}")
        for cp in clips:
            try:
                dest = os.path.join(save_segments_to, os.path.basename(cp))
                shutil.copy2(cp, dest)
                log(f"    📁 Saved: {os.path.basename(cp)}")
            except Exception as e:
                log(f"    ⚠️ Could not save {os.path.basename(cp)}: {e}")

    voice = AudioSegment.empty()
    timeline = []
    cursor = 0
    seg_by_id = {int(s.get("segment_id", i + 1)): s for i, s in enumerate(segments)}
    used = 0
    first = True
    total_segments = len(seg_by_id)

    log(f"  Merging {len(clips)} voice clips for {total_segments} segments...")

    expected_ids = sorted(list(seg_by_id.keys()))

    for sid in expected_ids:
        seg = seg_by_id.get(sid, {})
        ci = seg.get("control_instruction", "")

        clip_path = None
        for cp in clips:
            if num_key(cp) == sid:
                clip_path = cp
                break

        has_valid_clip = False
        if clip_path and os.path.exists(clip_path) and os.path.getsize(clip_path) > 1500:
            try:
                clip = AudioSegment.from_mp3(clip_path)
                if clip.dBFS > -40:
                    has_valid_clip = True
                else:
                    log(f"    🔇 seg {sid:02d} is silent placeholder (skipping)")
            except Exception as e:
                log(f"    ⚠️ seg {sid:02d} clip error: {e}")

        if has_valid_clip:
            if not first:
                pause = mood_pause(ci, 450, 800, 220)
                voice += AudioSegment.silent(duration=pause)
                cursor += pause

            clip = balance_voice_clip(clip)

            start = cursor
            voice += clip
            cursor += len(clip)
            used += 1
            first = False
            timeline.append({"segment_id": sid, "start_ms": start, "end_ms": cursor})
            log(f"    ✅ seg {sid:02d} added to final mix")
        else:
            log(f"    🔇 seg {sid:02d} missing/silent - adding pause")
            pause = mood_pause(ci, 800, 1200, 400)
            if not first:
                voice += AudioSegment.silent(duration=pause)
                cursor += pause
            else:
                first = False

    if used == 0 and len(voice) == 0:
        log("❌ No usable voice clips.")
        return None

    if len(voice) == 0:
        log("❌ Voice is empty after processing.")
        return None

    log(f"  merged voice: {len(voice)/60000:.1f} min  ({used} clips, {len(expected_ids)} total segments)")

    if bg_music and os.path.exists(bg_music):
        log("  adding background music...")
        music = AudioSegment.from_file(bg_music).set_channels(1)
        while len(music) < len(voice):
            music += music
        music = music[:len(voice)]
        music_ratio = max(0.0, min(1.0, float(bg_percent)))
        if music_ratio > 0 and math.isfinite(music.dBFS) and math.isfinite(voice.dBFS):
            # bg_percent is relative to the measured narration level, so music
            # remains balanced even when the source files have different gains.
            music_target = voice.dBFS + 20 * math.log10(music_ratio)
            music = music.apply_gain(music_target - music.dBFS)
            music = music.fade_in(2500).fade_out(2500)
            voice = voice.overlay(music)
        else:
            log("  background music is silent or its level is set to zero")
    elif auto_amb:
        log("  adding auto background ambience...")
        amb = build_ambience(len(voice))
        amb = amb.set_channels(voice.channels).set_frame_rate(voice.frame_rate)
        amb = amb.apply_gain(voice.dBFS - amb.dBFS - 18).fade_in(2500).fade_out(2500)
        voice = voice.overlay(amb)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()
    voice.export(tmp.name, format="wav")

    log("  normalizing to -14 LUFS...")
    subprocess.run([FFMPEG, "-y", "-i", tmp.name,
                    "-af", "loudnorm=I=-14:TP=-1.0:LRA=11",
                    "-c:a", "libmp3lame", "-b:a", "192k", out_voice],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.unlink(tmp.name)

    json.dump(timeline, open(out_voice + ".timeline.json", "w"))

    if save_segments_to:
        summary_path = os.path.join(save_segments_to, "segments_summary.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"Segments generated for: {os.path.basename(out_voice)}\n")
            f.write(f"Total segments: {len(expected_ids)}\n")
            f.write(f"Successfully generated: {used}\n")
            f.write(f"Timeline: {out_voice}.timeline.json\n\n")
            f.write("Segment files:\n")
            for sid in expected_ids:
                f.write(f"  {sid:02d}.mp3\n")

    return out_voice


# ─── STORY TOOLS ────────────────────────────────────────────────────────────

def export_prompts(data, out_path, log):
    segs = data.get("segments", [])
    if not segs:
        log("❌ No segments in JSON."); return
    STYLE = ("cinematic horror, dark, fog, moonlight, eerie atmosphere, "
             "photorealistic, highly detailed, moody lighting, 16:9, no text.txt, no watermark")
    NEG = "Negative: text.txt, watermark, blurry, gore, cartoon, bright happy colors, deformed"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Image prompts for: {data.get('title','')}\n")
        f.write(f"# Paste each into a free AI image tool (Bing/DALL-E, Leonardo, etc.)\n")
        f.write(f"# Save the results as 01.jpg, 02.jpg ... in one folder.\n\n")
        for seg in segs:
            sid = int(seg.get("segment_id", 0))
            title = seg.get("title", "")
            desc = (seg.get("video_feed_description") or "").strip()
            if desc:
                prompt = f"{desc}. {STYLE}"
            else:
                txt = (seg.get("target_text") or "").strip().replace("\n", " ")
                snippet = txt.split(".")[0][:120] if txt else ""
                prompt = f"{title}. {snippet}. {STYLE}"
            f.write(f"=== {sid:02d}  {title} ===\n{prompt}\n{NEG}\n\n")
    log(f"✅ Wrote {len(segs)} image prompts → {out_path}")

def check_segments(data, log):
    segs = data.get("segments", [])
    if not segs:
        log("❌ No segments in JSON."); return
    log(f"— Checking {len(segs)} segments —")
    prev_end = None
    issues = 0
    for seg in segs:
        sid = seg.get("segment_id", "?")
        media = [m for m in (seg.get("image_or_video") or []) if m]
        mm = re.findall(r"[\d.]+", str(seg.get("duration", "")))
        if len(mm) >= 2:
            a, b = float(mm[0]), float(mm[1])
            length = b - a
            note = ""
            if length <= 0:
                note += "  ⚠️ duration is zero/negative"; issues += 1
            if prev_end is not None and abs(a - prev_end) > 0.05:
                d = a - prev_end
                note += f"  ⚠️ {'gap' if d > 0 else 'overlap'} {d:+.1f}s vs previous"; issues += 1
            log(f"  seg {sid}: {a:.0f}-{b:.0f}s  ({length:.0f}s)  media={len(media)}{note}")
            prev_end = b
        else:
            log(f"  seg {sid}: (no 'duration')  media={len(media)}"); issues += 1
        if not media:
            log(f"     ⚠️ seg {sid} has no image_or_video"); issues += 1
    if prev_end is not None:
        log(f"  total timeline: {prev_end:.0f}s  (~{prev_end/60:.1f} min)")
    log("✅ All good." if issues == 0 else f"⚠️ {issues} issue(s) found above.")


# ─── PIPELINE ───────────────────────────────────────────────────────────────

def _make_voice(cfg, segments, log):
    if cfg["voice_source"] == "existing":
        v = cfg["voice_file"]
        if not v or not os.path.exists(v):
            log("❌ pick your existing voice file."); return None
        out_voice = os.path.abspath(cfg.get("voice_out") or "voice_final.mp3")
        if os.path.abspath(v) == out_voice:
            log("❌ Existing voice and output must be different files."); return None
        log("  Normalizing existing voice copy to -16 LUFS...")
        if not normalize_audio_lufs(v, out_voice):
            log("❌ Existing voice normalization failed."); return None
        return out_voice

    out_voice = cfg.get("voice_out") or "voice_final.mp3"
    tmp = tempfile.mkdtemp(prefix="oneclick_clips_")
    try:
        voice_cfg = {
            "voice_preset": cfg.get("voice_preset", ""),
            "voice_style": cfg.get("voice_style", ""),
            "cfg_value": float(cfg.get("cfg_value", 2.0)),
            "do_normalize": cfg.get("do_normalize", False),
            "denoise": cfg.get("denoise", False),
            "auto_emotion": cfg.get("auto_emotion", True),
            "speaker_lock": cfg.get("speaker_lock", True),
        }
        max_workers = int(cfg.get("max_workers", 2))

        log("STEP 1  generating voice (parallel)...")
        if not generate_voice(segments, cfg.get("voice_ref", ""), tmp, log, voice_cfg, max_workers):
            log("⚠️ Voice generation had issues, but continuing...")

        log("STEP 2  merging voice + pauses + music...")

        segments_output = cfg.get("segments_output", "")
        if segments_output:
            log(f"  📁 Individual segments will be saved to: {segments_output}")

        result = merge_voice(tmp, segments, out_voice, cfg["bg_music"], cfg["bg_percent"], log,
                             auto_amb=cfg.get("auto_amb", False),
                             save_segments_to=segments_output)
        if not result:
            log("❌ Voice merge failed completely.")
            return None
        return result
    finally:
        log(f"  📁 Temporary clips kept at: {tmp}")
        log(f"  📁 Individual segments saved to: {cfg.get('segments_output', 'Not specified')}")

def run_voice_only(cfg, log, progress):
    if not FFMPEG or not FFPROBE:
        log("❌ ffmpeg not found."); return
    data = json.load(open(cfg["json"], encoding="utf-8"))
    segments = data.get("segments", [])
    voice = _make_voice(cfg, segments, log)
    if voice:
        log(f"\n✅ VOICE READY → {voice}")


VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")


def _time_value(value):
    parts = str(value).strip().split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


def _segment_time_range(segment):
    """Parse 0-45, 0:00-0:45, and similar JSON duration formats."""
    value = str(segment.get("duration", "")).strip()
    match = re.match(r"^\s*([\d:.]+)\s*[-–—]\s*([\d:.]+)\s*$", value)
    if match:
        return _time_value(match.group(1)), _time_value(match.group(2))
    seconds = segment.get("duration_seconds")
    try:
        return 0.0, float(seconds)
    except (TypeError, ValueError):
        return None


def _stock_slug(value):
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_") or "stock"


def _pexels_video_url(query, api_key, per_page=8, minimum_duration=0.0, choice_index=0):
    """Find a landscape Pexels clip, preferring one long enough for its segment."""
    url = ("https://api.pexels.com/videos/search?query=" + urllib.parse.quote(query) +
           f"&per_page={per_page}&orientation=landscape&size=medium")
    request = urllib.request.Request(
        url, headers={"Authorization": api_key, "User-Agent": "jruy-video-studio/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    candidates = []
    for video in payload.get("videos", []):
        clip_duration = float(video.get("duration") or 0)
        files = []
        for item in video.get("video_files", []):
            link = item.get("link")
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            if link and width >= 960 and width >= height:
                files.append((abs(width - 1280), link))
        if files:
            long_enough = clip_duration >= minimum_duration
            candidates.append((not long_enough, -clip_duration, min(files)[1]))
    candidates.sort(key=lambda row: row[:2])
    return candidates[choice_index % len(candidates)][2] if candidates else ""


def _pexels_photo_url(query, api_key, per_page=8, choice_index=0):
    """Return a large landscape Pexels photo URL for a slow-zoom fallback."""
    url = ("https://api.pexels.com/v1/search?query=" + urllib.parse.quote(query) +
           f"&per_page={per_page}&orientation=landscape&size=large")
    request = urllib.request.Request(
        url, headers={"Authorization": api_key, "User-Agent": "jruy-video-studio/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    candidates = []
    for photo in payload.get("photos", []):
        sources = photo.get("src", {})
        link = sources.get("large2x") or sources.get("large") or sources.get("original")
        if link:
            candidates.append(link)
    return candidates[choice_index % len(candidates)] if candidates else ""


def _media_duration(path):
    try:
        probe = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=30)
        return float(probe.stdout.strip()) if probe.returncode == 0 else 0.0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _video_duration(path):
    try:
        probe = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=duration", "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30)
        return float(probe.stdout.strip()) if probe.returncode == 0 else 0.0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _download_stock_video(url, destination):
    partial = destination + ".part"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response, open(partial, "wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if os.path.getsize(partial) < 10000:
            raise RuntimeError("downloaded file is too small")
        os.replace(partial, destination)
    finally:
        if os.path.exists(partial):
            try: os.unlink(partial)
            except OSError: pass


def download_missing_stock(json_path, segments, clips_folder, log, api_key=PEXELS_KEY):
    """Fill missing media in memory with one downloaded stock clip per two segments."""
    if not api_key:
        log("⚠️ Pexels API key is empty; missing media will remain black.")
        return 0
    os.makedirs(clips_folder, exist_ok=True)
    json_base = os.path.dirname(os.path.abspath(json_path))
    downloaded, last_media = 0, ""
    index = 0
    while index < len(segments):
        segment = segments[index]
        existing = next((str(p) for p in (segment.get("image_or_video") or []) if p), "")
        resolved = existing if os.path.isabs(existing) else os.path.join(json_base, existing)
        if existing and os.path.exists(resolved):
            last_media = resolved
            index += 1
            continue

        query = (segment.get("stock_query") or segment.get("title") or
                 segment.get("video_feed_description") or "dark cinematic night").strip()
        sid = int(segment.get("segment_id") or index + 1)
        time_range = _segment_time_range(segment)
        needed_duration = max(0.1, time_range[1] - time_range[0]) if time_range else 15.0
        destination = os.path.abspath(os.path.join(
            clips_folder, f"{_stock_slug(query)[:50]}_{sid:03d}_pick{sid % 8}.mp4"))
        try:
            if os.path.exists(destination) and os.path.getsize(destination) > 10000:
                log(f"  stock seg {sid}: using cached {os.path.basename(destination)}")
            else:
                log(f"  stock seg {sid}: searching Pexels for '{query}'...")
                link = _pexels_video_url(
                    query, api_key, minimum_duration=needed_duration, choice_index=sid)
                if not link and query != "dark cinematic night":
                    link = _pexels_video_url(
                        "dark cinematic night", api_key,
                        minimum_duration=needed_duration, choice_index=sid)
                if not link:
                    if last_media:
                        segment["image_or_video"] = [last_media]
                        log(f"  ⚠️ stock seg {sid}: no result; carrying previous clip")
                    else:
                        log(f"  ⚠️ stock seg {sid}: no video result")
                    index += 1
                    continue
                _download_stock_video(link, destination)
                log(f"  ✅ stock seg {sid}: downloaded {os.path.basename(destination)}")
                downloaded += 1
            segment["image_or_video"] = [destination]
            last_media = destination
            index += 1
        except Exception as error:
            if last_media:
                segment["image_or_video"] = [last_media]
                log(f"  ⚠️ stock seg {sid}: download failed; carrying previous clip")
            else:
                log(f"  ⚠️ stock seg {sid}: {str(error)[:120]}")
            index += 1
    return downloaded


def replace_short_videos_with_images(json_path, segments, clips_folder, log,
                                     api_key=PEXELS_KEY):
    """Replace too-short video assignments with downloaded slow-zoom images."""
    if not api_key:
        return 0
    os.makedirs(clips_folder, exist_ok=True)
    json_base = os.path.dirname(os.path.abspath(json_path))
    replaced = 0
    for index, segment in enumerate(segments):
        media = next((str(p) for p in (segment.get("image_or_video") or []) if p), "")
        resolved = media if os.path.isabs(media) else os.path.join(json_base, media)
        if not resolved.lower().endswith(VIDEO_EXT) or not os.path.exists(resolved):
            continue
        time_range = _segment_time_range(segment)
        needed = max(0.1, time_range[1] - time_range[0]) if time_range else 15.0
        available = _media_duration(resolved)
        if available <= 0 or available + 0.5 >= needed:
            continue
        query = (segment.get("stock_query") or segment.get("title") or
                 segment.get("video_feed_description") or "dark cinematic night").strip()
        sid = int(segment.get("segment_id") or index + 1)
        image_path = os.path.abspath(os.path.join(
            clips_folder, f"{_stock_slug(query)[:50]}_{sid:03d}_pick{sid % 8}_fallback.jpg"))
        try:
            if not os.path.exists(image_path) or os.path.getsize(image_path) < 10000:
                log(f"  short seg {sid}: video {available:.1f}s < {needed:.1f}s; downloading image...")
                link = _pexels_photo_url(query, api_key, choice_index=sid)
                if not link and query != "dark cinematic night":
                    link = _pexels_photo_url("dark cinematic night", api_key, choice_index=sid)
                if not link:
                    log(f"  ⚠️ short seg {sid}: no fallback image found")
                    continue
                _download_stock_video(link, image_path)
            segment["image_or_video"] = [image_path]
            replaced += 1
            log(f"  ✅ short seg {sid}: using slow-zoom image {os.path.basename(image_path)}")
        except Exception as error:
            log(f"  ⚠️ short seg {sid}: image fallback failed: {str(error)[:100]}")
    return replaced


def _video_windows(voice_path, segments):
    """Return narration-aligned (start, end) windows for every JSON segment."""
    duration = audio_dur(voice_path)
    timeline_path = voice_path + ".timeline.json"
    if os.path.exists(timeline_path):
        try:
            timeline = json.load(open(timeline_path, encoding="utf-8"))
            if len(timeline) == len(segments) and timeline:
                source_duration = timeline[-1]["end_ms"] / 1000.0
                scale = duration / source_duration if source_duration else 1.0
                starts = [row["start_ms"] / 1000.0 * scale for row in timeline]
                return [(starts[i], starts[i + 1] if i + 1 < len(starts) else duration)
                        for i in range(len(starts))]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    json_windows = []
    for segment in segments:
        time_range = _segment_time_range(segment)
        if not time_range:
            json_windows = []
            break
        json_windows.append(time_range)
    if json_windows and json_windows[-1][1] > 0:
        scale = duration / json_windows[-1][1]
        return [(start * scale, end * scale) for start, end in json_windows]
    each = duration / max(1, len(segments))
    return [(i * each, (i + 1) * each) for i in range(len(segments))]


def _story_video_duration(segments, fallback=20.0):
    """Read the largest end time from JSON duration fields, when available."""
    largest = 0.0
    for segment in segments:
        time_range = _segment_time_range(segment)
        if time_range:
            largest = max(largest, time_range[1])
    return largest or float(fallback)


def _video_holds(json_path, segments, windows, max_hold=40.0):
    """Group narration into long, slow image holds like the original renderer."""
    base = os.path.dirname(os.path.abspath(json_path))
    raw = []
    for segment, (start, end) in zip(segments, windows):
        media = next((str(p) for p in (segment.get("image_or_video") or []) if p), "")
        if media and not os.path.isabs(media):
            media = os.path.join(base, media)
        if not os.path.exists(media):
            media = ""
        raw.append((media, start, end))

    holds, index = [], 0
    while index < len(raw):
        media, start, end = raw[index]
        is_video = media.lower().endswith(VIDEO_EXT)
        if is_video or not media:
            holds.append((media, start, end))
            index += 1
            continue
        next_index = index + 1
        while next_index < len(raw) and end - start < max_hold:
            next_media, _, next_end = raw[next_index]
            # Only merge when JSON really assigns the exact same image.
            # A different image must appear at its own segment boundary.
            if next_media != media or next_media.lower().endswith(VIDEO_EXT) or not next_media:
                break
            end = next_end
            next_index += 1
            if end >= start + max_hold:
                break
        holds.append((media, start, end))
        index = next_index
    return holds


def render_json_video(cfg, voice_path, segments, log, progress):
    """Self-contained FFmpeg renderer for JSON-assigned images and videos."""
    width, height = cfg["width"], cfg["height"]
    fps, crf = int(cfg["fps"]), int(cfg["crf"])
    # Shots are encoded once before xfade and once afterward. Keep the first
    # pass near-lossless so transitions do not expose block artifacts.
    intermediate_crf = min(crf, 12)
    effect_style = cfg.get("effect_style", "Horror Cinematic")
    if effect_style == "Blood Red":
        effect_filter = (
            "eq=brightness=-0.10:contrast=1.20:saturation=0.72:gamma=0.94,"
            "colorchannelmixer=rr=1.08:gg=0.88:bb=0.82,vignette=PI/5.2,"
            "noise=alls=1.6:allf=u")
    elif effect_style == "Black & White Dread":
        effect_filter = (
            "eq=brightness=-0.08:contrast=1.24:saturation=0.05:gamma=0.95,"
            "vignette=PI/5.0,noise=alls=1.8:allf=u")
    elif effect_style == "Natural Dark":
        effect_filter = "eq=brightness=-0.04:contrast=1.08:saturation=0.90,vignette=PI/6.5"
    else:
        effect_filter = (
            "eq=brightness=-0.08:contrast=1.16:saturation=0.68:gamma=0.96,"
            "colorchannelmixer=rr=0.94:gg=0.97:bb=1.06,vignette=PI/5.5,"
            "noise=alls=1.5:allf=u")
    log(f"  horror effect: {effect_style}")
    windows = _video_windows(voice_path, segments)
    if cfg.get("preview"):
        limit = min(20.0, audio_dur(voice_path))
        windows = [(a, min(b, limit)) for a, b in windows if a < limit]
        segments = segments[:len(windows)]
        log("⏱ PREVIEW: first 20 seconds")
    holds = _video_holds(cfg["json"], segments, windows)
    log(f"  image groups: {len(holds)} holds from {len(segments)} segments")
    shortest_hold = min((max(0.05, end - start) for _, start, end in holds), default=1.0)
    transition_duration = min(float(cfg.get("transition_duration", 1.5)),
                              max(0.1, shortest_hold * 0.4)) if len(holds) > 1 else 0.0

    work = tempfile.mkdtemp(prefix="jruy_video_")
    clip_paths = []
    logical_durations = []
    try:
        for number, (media, start, end) in enumerate(holds, 1):
            logical_duration = max(0.05, end - start)
            # Extra tail is consumed by xfade, preserving the exact story length.
            duration = logical_duration + (transition_duration if number < len(holds) else 0.0)
            logical_durations.append(logical_duration)
            total_frames = max(1, int(duration * fps))
            zoom_step = max(0.00004, min(0.0005, 0.08 / total_frames))
            clip_path = os.path.join(work, f"clip_{number:04d}.mp4")
            common_filter = (
                    f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},setsar=1,"
                    + effect_filter
            )
            if not media:
                cmd = [FFMPEG, "-y", "-f", "lavfi", "-i",
                       f"color=c=0x1b1f2a:s={width}x{height}:r={fps}:d={duration}"]
                video_filter = "noise=alls=6:allf=t,format=yuv420p"
            elif media.lower().endswith(VIDEO_EXT):
                # Pexels selection prefers a source long enough for this hold.
                # Never replay a short source: extend its final frame and keep
                # visual motion with a slow Ken Burns zoom until the next shot.
                cmd = [FFMPEG, "-y", "-fflags", "+genpts", "-i", media,
                       "-t", str(duration)]
                video_filter = (
                        f"fps={fps},setpts=N/({fps}*TB),"
                        f"tpad=stop_mode=clone:stop_duration={duration}," + common_filter +
                        f",zoompan=z='min(zoom+0.00025,1.08)':d=1:"
                        f"s={width}x{height}:fps={fps},trim=duration={duration},"
                        "setpts=N/FRAME_RATE/TB,format=yuv420p"
                )
            else:
                cmd = [FFMPEG, "-y", "-loop", "1", "-framerate", str(fps),
                       "-i", media, "-t", str(duration)]
                # Animate at 2x resolution, then downsample. Zoompan otherwise
                # rounds crop movement to full output pixels and visibly jerks.
                motion_width, motion_height = width * 2, height * 2
                video_filter = (
                        f"scale={motion_width}:{motion_height}:force_original_aspect_ratio=increase:"
                        "flags=lanczos,"
                        f"crop={motion_width}:{motion_height},setsar=1,"
                        f"zoompan=z='min(max(pzoom,1.0)+{zoom_step:.7f},1.08)':"
                        "x='trunc(iw/2-iw/zoom/2)':y='trunc(ih/2-ih/zoom/2)':d=1:"
                        f"s={width}x{height}:fps={fps},"
                        + effect_filter + ",unsharp=5:5:0.25:3:3:0.10,"
                                          "format=yuv420p")
                log(f"  image hold {number}: sub-pixel 8% zoom + {effect_style} effect")
            cmd += ["-vf", video_filter, "-an", "-r", str(fps), "-c:v", "libx264",
                    "-preset", "fast", "-crf", str(intermediate_crf),
                    "-pix_fmt", "yuv420p", clip_path]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                log(f"❌ clip {number} failed:\n" + "\n".join(result.stderr.splitlines()[-6:]))
                return None
            clip_paths.append(clip_path)
            percent = int(number / max(1, len(holds)) * 85)
            progress(percent)
            log(f"  rendered hold {number}/{len(holds)} ({percent}%)")

        joined = os.path.join(work, "joined.mp4")
        if len(clip_paths) == 1:
            concat_cmd = [FFMPEG, "-y", "-i", clip_paths[0], "-c", "copy", joined]
        else:
            concat_cmd = [FFMPEG, "-y"]
            for path in clip_paths:
                concat_cmd += ["-i", path]
            filters = []
            previous = "0:v"
            elapsed = logical_durations[0]
            transitions = ("fade", "smoothleft", "fade", "smoothup")
            for index in range(1, len(clip_paths)):
                output_label = f"x{index}"
                transition = transitions[(index - 1) % len(transitions)]
                filters.append(
                    f"[{previous}][{index}:v]xfade=transition={transition}:"
                    f"duration={transition_duration:.3f}:offset={elapsed:.3f}[{output_label}]")
                previous = output_label
                elapsed += logical_durations[index]
            concat_cmd += ["-filter_complex", ";".join(filters), "-map", f"[{previous}]",
                           "-an", "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", str(crf), "-pix_fmt", "yuv420p", joined]
            log(f"  adding {len(clip_paths) - 1} smooth high-quality transitions "
                f"({transition_duration:.1f}s, intermediate CRF {intermediate_crf})")
        concat = subprocess.run(concat_cmd, capture_output=True, text=True)
        if concat.returncode != 0:
            log("❌ Could not join rendered video holds:\n" +
                "\n".join(concat.stderr.splitlines()[-6:]))
            return None

        output = cfg["out"]
        voice_duration = min(20.0, audio_dur(voice_path)) if cfg.get("preview") else audio_dur(voice_path)
        background_music = cfg.get("bg_music", "")
        if cfg.get("mute_audio") and background_music and os.path.exists(background_music):
            music_level = max(0.0, min(1.0, float(cfg.get("bg_percent", 0.18))))
            fade_out_start = max(0.0, voice_duration - 2.5)
            audio_filter = (
                f"volume={music_level:.3f},afade=t=in:st=0:d=2.0,"
                f"afade=t=out:st={fade_out_start:.3f}:d=2.5")
            mux_cmd = [FFMPEG, "-y", "-i", joined, "-stream_loop", "-1",
                       "-i", background_music, "-map", "0:v:0", "-map", "1:a:0",
                       "-t", str(voice_duration), "-c:v", "copy", "-af", audio_filter,
                       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", output]
            log(f"  adding background sound at {music_level:.0%} volume")
        elif cfg.get("mute_audio"):
            mux_cmd = [FFMPEG, "-y", "-i", joined, "-map", "0:v:0", "-t", str(voice_duration),
                       "-c:v", "copy", "-an", "-movflags", "+faststart", output]
        else:
            mux_cmd = [FFMPEG, "-y", "-i", joined, "-i", voice_path,
                       "-map", "0:v:0", "-map", "1:a:0", "-t", str(voice_duration),
                       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                       "-movflags", "+faststart", output]
        mux = subprocess.run(mux_cmd, capture_output=True, text=True)
        if mux.returncode != 0:
            log("❌ Final audio/video merge failed:\n" + "\n".join(mux.stderr.splitlines()[-6:]))
            return None
        progress(100)
        return output
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_make_video(cfg, log, progress):
    """Generate/prepare narration, then render video with the engine in 1.py."""
    if not FFMPEG or not FFPROBE:
        log("❌ ffmpeg/ffprobe not found.")
        return None
    data = json.load(open(cfg["json"], encoding="utf-8"))
    segments = data.get("segments", [])
    if not segments:
        log("❌ Story JSON has no segments.")
        return None

    silent_voice = ""
    if cfg.get("video_only"):
        if cfg.get("full_json_video"):
            test_duration = _story_video_duration(
                segments, fallback=max(1, len(segments)) * 15.0)
            log(f"  full JSON mode: {len(segments)} segments, {test_duration / 60:.1f} min")
        else:
            test_duration = max(1.0, float(cfg.get("video_test_duration", 20.0)))
            timed_segments = []
            for segment in segments:
                time_range = _segment_time_range(segment)
                if time_range and time_range[0] < test_duration:
                    timed_segments.append(segment)
            if timed_segments:
                segments = timed_segments
            else:
                test_count = max(1, int(math.ceil(test_duration / 15.0)))
                segments = segments[:test_count]
        silent = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        silent.close()
        silent_voice = silent.name
        make_silence = subprocess.run(
            [FFMPEG, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
             "-t", str(test_duration), "-c:a", "libmp3lame", "-b:a", "64k", silent_voice],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if make_silence.returncode != 0:
            log("❌ Could not create the silent test timeline.")
            return None
        voice = silent_voice
        log(f"STEP 1  video-only test: skipped voice generation ({test_duration:.1f}s)")
    else:
        voice = _make_voice(cfg, segments, log)
        if not voice:
            return None

    clips_folder = cfg.get("clips_folder") or (
            os.path.splitext(os.path.abspath(cfg["json"]))[0] + "_stock_clips")
    missing = 0
    json_base = os.path.dirname(os.path.abspath(cfg["json"]))
    for segment in segments:
        media = next((str(p) for p in (segment.get("image_or_video") or []) if p), "")
        resolved = media if os.path.isabs(media) else os.path.join(json_base, media)
        if not media or not os.path.exists(resolved):
            missing += 1
    if missing:
        log(f"STEP 3  downloading stock video for {missing} missing segments...")
        count = download_missing_stock(cfg["json"], segments, clips_folder, log)
        log(f"  stock download complete: {count} new clips saved in {clips_folder}")
    image_fallbacks = replace_short_videos_with_images(
        cfg["json"], segments, clips_folder, log)
    if image_fallbacks:
        log(f"  short-video fallback: {image_fallbacks} segment(s) changed to slow-zoom images")

    width, height = (int(v) for v in cfg.get("resolution", "1280x720").split("x"))
    output = os.path.abspath(cfg.get("video_out") or
                             (os.path.splitext(cfg["json"])[0] + ".mp4"))
    os.makedirs(os.path.dirname(output), exist_ok=True)
    render_cfg = {
        "width": width, "height": height, "fps": int(cfg.get("fps", 20)),
        "crf": int(cfg.get("crf", 18)),
        "preview": bool(cfg.get("preview", False)) and not bool(cfg.get("video_only", False)),
        "out": output, "title": data.get("title", ""),
        "subtitle": data.get("subtitle", ""), "show_title": bool(cfg.get("show_title", True)),
        "logo": cfg.get("logo", ""), "use_logo": bool(cfg.get("use_logo", False)),
        "logo_corner": cfg.get("logo_corner", "bottom-right"),
        "channel": cfg.get("channel", ""),
        "channel_corner": cfg.get("channel_corner", "top-right"),
        "mute_audio": bool(cfg.get("video_only", False)),
        "effect_style": cfg.get("effect_style", "Horror Cinematic"),
        "bg_music": cfg.get("bg_music", ""),
        "bg_percent": float(cfg.get("bg_percent", 0.18)),
    }
    render_cfg["json"] = cfg["json"]
    log("STEP 4  rendering video with jruy.py built-in engine...")
    try:
        render_json_video(render_cfg, voice, segments, log, progress)
    finally:
        if silent_voice and os.path.exists(silent_voice):
            try: os.unlink(silent_voice)
            except OSError: pass
    if os.path.exists(output) and os.path.getsize(output) > 0:
        log(f"\n✅ VIDEO READY → {output}")
        return output
    log("❌ Video render did not produce an output file.")
    return None


def _make_story_card(width, height, fps, duration, story_number, author, output, log,
                     background_sound=""):
    """Create a horror-style Story N / By card with optional background sound."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (width, height), (5, 6, 9))
    draw = ImageDraw.Draw(image)
    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    def font(size):
        for path in font_paths:
            if os.path.exists(path):
                try: return ImageFont.truetype(path, size)
                except OSError: pass
        return ImageFont.load_default()

    title = f"STORY: {story_number}"
    byline = f"BY: {author or 'Anonymous'}"
    title_font, by_font = font(max(28, int(height * 0.085))), font(max(20, int(height * 0.045)))
    title_box = draw.textbbox((0, 0), title, font=title_font)
    by_box = draw.textbbox((0, 0), byline, font=by_font)
    title_w, title_h = title_box[2] - title_box[0], title_box[3] - title_box[1]
    by_w, by_h = by_box[2] - by_box[0], by_box[3] - by_box[1]
    center_y = height // 2
    draw.text(((width - title_w) // 2 + 3, center_y - title_h - 17), title,
              font=title_font, fill=(45, 0, 0))
    draw.text(((width - title_w) // 2, center_y - title_h - 20), title,
              font=title_font, fill=(205, 205, 210))
    draw.text(((width - by_w) // 2, center_y + 30), byline,
              font=by_font, fill=(135, 135, 145))
    image_path = output + ".jpg"
    image.save(image_path, quality=95)
    try:
        has_sound = bool(background_sound and os.path.exists(background_sound))
        audio_input = (["-stream_loop", "-1", "-i", background_sound] if has_sound else
                       ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"])
        command = [FFMPEG, "-y", "-loop", "1", "-framerate", str(fps), "-i", image_path]
        command += audio_input + ["-t", str(duration),
                                  "-vf", "fade=t=in:st=0:d=0.8,fade=t=out:st=" +
                                  str(max(0.0, duration - 0.7)) + ":d=0.7"]
        if has_sound:
            command += ["-af", "volume=0.42,afade=t=in:st=0:d=0.5,afade=t=out:st=" +
                        str(max(0.0, duration - 0.8)) + ":d=0.8"]
        command += ["-c:v", "libx264", "-preset", "fast", "-crf", "12",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", output]
        result = subprocess.run(
            command,
            capture_output=True, text=True)
        if result.returncode != 0:
            log("❌ Story card failed: " + "\n".join(result.stderr.splitlines()[-5:]))
            return None
        sound_note = f" + {os.path.basename(background_sound)}" if has_sound else " + silence"
        log(f"  ✅ card: Story {story_number} — By: {author or 'Anonymous'}{sound_note}")
        return output
    finally:
        try: os.unlink(image_path)
        except OSError: pass


def _ensure_video_audio(source, output, duration):
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", source], capture_output=True, text=True)
    if probe.stdout.strip():
        shutil.copy2(source, output)
        return output
    result = subprocess.run(
        [FFMPEG, "-y", "-i", source, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", str(duration), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-shortest", output],
        capture_output=True, text=True)
    return output if result.returncode == 0 else None


def expand_compilation_json(json_paths, supplied_authors, output_folder, log):
    """Expand JSON files containing a top-level stories[] compilation."""
    expanded, authors = [], []
    for source_path in json_paths:
        data = json.load(open(source_path, encoding="utf-8"))
        embedded = data.get("stories") if isinstance(data, dict) else None
        if not isinstance(embedded, list) or not embedded:
            expanded.append(source_path)
            authors.append(supplied_authors[len(authors)] if len(authors) < len(supplied_authors)
                           else "Anonymous")
            continue
        log(f"  detected compilation JSON: {len(embedded)} embedded stories")
        for story_index, story in enumerate(embedded, 1):
            story_doc = dict(story)
            project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
            story_doc.setdefault("channel", data.get("channel", project.get("channel", "")))
            story_doc.setdefault("language", data.get("language", project.get("language", "")))
            story_doc.setdefault("subtitle", data.get("title", project.get("title", "")))
            supplied = supplied_authors[len(authors)] if len(authors) < len(supplied_authors) else ""
            inferred = str(story.get("author") or story.get("by") or story.get("byline") or supplied or "").strip()
            if inferred.lower() in ("", "...", "..", ".", "none", "null", "unknown", "n/a"):
                inferred = "Anonymous"
            authors.append(inferred)

            # Normalize the newer compact segment schema:
            # segment/narration/visual_prompt -> renderer/voice field names.
            normalized_segments = []
            narration_note = project.get("narration_notes", "Slow, restrained horror narration.")
            for position, original in enumerate(story.get("segments", []), 1):
                segment = dict(original)
                sid = int(segment.get("segment_id") or segment.get("segment") or position)
                prompt = str(segment.get("video_feed_description") or
                             segment.get("visual_prompt") or "").strip()
                segment["segment_id"] = sid
                segment.setdefault("title", f"seg{sid}")
                segment.setdefault("target_text", segment.get("narration", ""))
                segment.setdefault("video_feed_description", prompt)
                segment.setdefault("stock_query", " ".join(prompt.split()[:10]) or "dark forest night")
                segment.setdefault("control_instruction", narration_note)
                normalized_segments.append(segment)
            story_doc["segments"] = normalized_segments
            # Preserve the compilation closing as the final narration segment.
            closing_data = data.get("compilation_closing") or data.get("ending")
            if story_index == len(embedded) and isinstance(closing_data, dict):
                segments = [dict(segment) for segment in story_doc.get("segments", [])]
                closing = closing_data
                closing_text = closing.get("target_text") or closing.get("narration")
                if closing_text:
                    last_end = _story_video_duration(segments, fallback=len(segments) * 45.0)
                    closing_prompt = closing.get("visual_prompt", "A dark forest fading into the night.")
                    segments.append({
                        "segment_id": max([int(s.get("segment_id", 0)) for s in segments] or [0]) + 1,
                        "title": closing.get("title", "Compilation Closing"),
                        "duration": f"{last_end:.1f}-{last_end + 15.0:.1f}",
                        "duration_seconds": 15,
                        "stock_query": "dark forest night end screen",
                        "video_feed_description": closing_prompt,
                        "control_instruction": "Slow, ominous closing narration.",
                        "target_text": closing_text,
                    })
                story_doc["segments"] = segments
            extracted = os.path.join(output_folder, f"embedded_story_{len(expanded) + 1:02d}.json")
            with open(extracted, "w", encoding="utf-8") as handle:
                json.dump(story_doc, handle, ensure_ascii=False, indent=2)
            expanded.append(extracted)
    return expanded, authors


def run_make_multi_story_video(cfg, json_paths, authors, log, progress):
    """Render independent JSON stories with cards and join them into one upload."""
    selected_script = os.path.abspath(json_paths[0])
    expansion_work = tempfile.mkdtemp(prefix="jruy_compilation_")
    json_paths, authors = expand_compilation_json(
        json_paths, authors, expansion_work, log)
    if len(json_paths) < 2:
        try:
            single_cfg = dict(cfg); single_cfg["json"] = json_paths[0]
            return run_make_video(single_cfg, log, progress)
        finally:
            shutil.rmtree(expansion_work, ignore_errors=True)
    if cfg.get("voice_source") == "existing" and not cfg.get("video_only"):
        shutil.rmtree(expansion_work, ignore_errors=True)
        raise ValueError("Multi-story voice mode requires generated voice, not one existing voice file.")

    width, height = (int(value) for value in cfg.get("resolution", "1280x720").split("x"))
    fps = int(cfg.get("fps", 20))
    card_duration = max(3.0, min(5.0, float(cfg.get("story_card_duration", 4.0))))
    story_card_bg = cfg.get("story_card_bg", STORY_CARD_BG)
    final_output = os.path.abspath(
        cfg.get("video_out") or (os.path.splitext(selected_script)[0] + "_video.mp4"))
    os.makedirs(os.path.dirname(final_output), exist_ok=True)
    log(f"  final output folder: {os.path.dirname(final_output)}")
    work = tempfile.mkdtemp(prefix="jruy_multi_story_")
    pieces = []
    shared_narrator_ref = cfg.get("voice_ref", "")
    try:
        for index, json_path in enumerate(json_paths, 1):
            author = authors[index - 1] if index - 1 < len(authors) and authors[index - 1] else "Anonymous"
            log(f"\n===== STORY {index}/{len(json_paths)}: {os.path.basename(json_path)} =====")
            card = _make_story_card(width, height, fps, card_duration, index, author,
                                    os.path.join(work, f"card_{index:02d}.mp4"), log,
                                    background_sound=story_card_bg)
            if not card:
                return None
            pieces.append(card)
            story_cfg = dict(cfg)
            segment_folder = os.path.join(work, f"segments_{index:02d}")
            story_cfg.update({
                "json": json_path,
                "video_out": os.path.join(work, f"story_{index:02d}.mp4"),
                "voice_out": os.path.join(work, f"story_{index:02d}_voice.mp3"),
                "segments_output": segment_folder,
                "preview": False,
            })
            if shared_narrator_ref and os.path.exists(shared_narrator_ref):
                story_cfg["voice_ref"] = shared_narrator_ref
            story_video = run_make_video(
                story_cfg, log,
                lambda value, i=index: progress(int(((i - 1) + value / 100) / len(json_paths) * 90)))
            if not story_video:
                return None
            if not shared_narrator_ref and not cfg.get("video_only"):
                first_segment = next(iter(sorted(glob.glob(os.path.join(segment_folder, "*.mp3")))), "")
                if first_segment:
                    shared_narrator_ref = first_segment
                    log(f"  🔒 Reusing Story 1 narrator for all following stories: "
                        f"{os.path.basename(first_segment)}")
            normalized = os.path.join(work, f"story_{index:02d}_audio.mp4")
            if not _ensure_video_audio(story_video, normalized, _media_duration(story_video)):
                log(f"❌ Could not prepare audio track for Story {index}")
                return None
            pieces.append(normalized)

        manifest = os.path.join(work, "multi_story.txt")
        with open(manifest, "w", encoding="utf-8") as handle:
            for piece in pieces:
                handle.write("file '" + piece.replace("'", "'\\''") + "'\n")
        expected_video_duration = sum(_video_duration(piece) for piece in pieces)
        log("\nJoining story cards and stories into one YouTube video...")
        join = subprocess.run(
            [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", manifest,
             "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
             "-af", "aresample=async=1:first_pts=0", "-c:a", "aac",
             "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-t", f"{expected_video_duration:.3f}",
             "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", final_output],
            capture_output=True, text=True)
        if join.returncode != 0:
            log("❌ Multi-story join failed: " + "\n".join(join.stderr.splitlines()[-6:]))
            return None
        progress(100)
        log(f"\n✅ MULTI-STORY VIDEO READY → {final_output}")
        return final_output
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(expansion_work, ignore_errors=True)


# ─── GUI ────────────────────────────────────────────────────────────────────

class ScrollableFrame(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.win, width=e.width))
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
    def _wheel(self, e):
        d = e.delta
        if abs(d) >= 120: d = int(d / 120)
        self.canvas.yview_scroll(-d, "units")


class App:
    def __init__(self, root):
        self.root = root
        root.title("🎙 Horror Voice Studio - Parallel Mode")
        root.geometry("760x820")
        self.q = queue.Queue()

        bottom = ttk.Frame(root)
        bottom.pack(side="bottom", fill="both")
        self.bar = ttk.Progressbar(bottom, mode="determinate")
        self.bar.pack(fill="x", padx=8, pady=(6, 2))
        self.log_box = scrolledtext.ScrolledText(bottom, height=10, font=("Menlo", 9))
        self.log_box.pack(fill="both", padx=8, pady=(0, 8))

        self.sf = ScrollableFrame(root)
        self.sf.pack(side="top", fill="both", expand=True)
        host = self.sf.body
        host.columnconfigure(1, weight=1)
        pad = {"padx": 8, "pady": 3}
        r = 0

        def head(t):
            nonlocal r
            ttk.Label(host, text=t, font=("Helvetica", 11, "bold")).grid(
                row=r, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 2))
            r += 1

        def filerow(label, var, kind):
            nonlocal r
            ttk.Label(host, text=label).grid(row=r, column=0, sticky="w", **pad)
            ttk.Entry(host, textvariable=var).grid(row=r, column=1, sticky="ew", **pad)
            ttk.Button(host, text="Browse", command=lambda: self.browse(var, kind)).grid(row=r, column=2, **pad)
            r += 1

        def entryrow(label, var, w=12):
            nonlocal r
            ttk.Label(host, text=label).grid(row=r, column=0, sticky="w", **pad)
            ttk.Entry(host, textvariable=var, width=w).grid(row=r, column=1, sticky="w", **pad)
            r += 1

        def checkrow(label, var):
            nonlocal r
            ttk.Checkbutton(host, text=label, variable=var).grid(
                row=r, column=0, columnspan=3, sticky="w", **pad)
            r += 1

        def combo(label, var, vals):
            nonlocal r
            ttk.Label(host, text=label).grid(row=r, column=0, sticky="w", **pad)
            ttk.Combobox(host, textvariable=var, width=25, state="readonly", values=vals).grid(
                row=r, column=1, sticky="w", **pad)
            r += 1

        head("Story")
        self.json = tk.StringVar()
        filerow("Story JSON", self.json, "json")
        self.prompts_out = tk.StringVar(value="scene_prompts.txt")
        filerow("Image-prompts output (.txt)", self.prompts_out, "savetxt")
        ttk.Button(host, text="Export scene image prompts (for AI tools)",
                   command=self.do_prompts).grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
        r += 1
        ttk.Button(host, text="Check segments (duration & media)",
                   command=self.do_check).grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
        r += 1

        head("Voice [VoxCPM2 Parallel + edge-tts Fallback]")
        self.voice_source = tk.StringVar(value="generate")
        combo("Voice source", self.voice_source, ["generate", "existing"])

        self.voice_preset = tk.StringVar(value="Balanced Neutral")
        combo("Voice Preset", self.voice_preset, list(VOICE_PRESETS.keys()))

        self.voice_style = tk.StringVar(value="Balanced")
        combo("Voice Style", self.voice_style, list(VOICE_STYLES.keys()))

        self.voice_ref = tk.StringVar()
        filerow("Reference voice (wav/mp3 — optional)", self.voice_ref, "audio")
        self.voice_file = tk.StringVar()
        filerow("...or existing voice mp3/wav (source=existing)", self.voice_file, "audio")

        head("VoxCPM2 Advanced Settings")
        self.cfg_value = tk.StringVar(value="1.7")
        entryrow("CFG Guidance Scale (1.6-1.8 recommended for Khmer)", self.cfg_value, 8)
        self.do_normalize = tk.BooleanVar(value=False)
        checkrow("Text Normalization", self.do_normalize)
        self.denoise = tk.BooleanVar(value=True)
        checkrow("Reference Audio Enhancement (denoising)", self.denoise)

        self.max_workers = tk.StringVar(value="2")
        entryrow("Parallel workers (1–2 recommended)", self.max_workers, 6)

        head("Background Audio")
        self.bg_music = tk.StringVar()
        filerow("Background music (optional)", self.bg_music, "audio")
        self.bg_percent = tk.StringVar(value="0.18")
        entryrow("Music level (0.18)", self.bg_percent, 8)
        self.auto_amb = tk.BooleanVar(value=False)
        checkrow("Auto background ambience (generated, if no music file)", self.auto_amb)
        self.voice_out = tk.StringVar(value="voice_final.mp3")
        filerow("Voice output (.mp3)", self.voice_out, "savemp3")

        self.segments_output = tk.StringVar(value="segments_audio")
        filerow("Segments output folder (save individual MP3s)", self.segments_output, "folder")

        ttk.Button(host, text="🎙  Generate voice (.mp3) only  — PARALLEL",
                   command=self.start_voice).grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=6)
        r += 1
        ttk.Label(host, text="").grid(row=r, column=0, pady=4)
        self.root.after(100, self.drain)

    def browse(self, var, kind):
        if kind == "json":
            p = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All", "*.*")])
        elif kind == "audio":
            p = filedialog.askopenfilename(filetypes=[("Audio", "*.mp3 *.wav *.m4a"), ("All", "*.*")])
        elif kind == "folder":
            p = filedialog.askdirectory()
        elif kind == "savetxt":
            p = filedialog.asksaveasfilename(defaultextension=".txt")
        elif kind == "savemp3":
            p = filedialog.asksaveasfilename(defaultextension=".mp3")
        else:
            p = filedialog.asksaveasfilename()
        if p:
            var.set(p)

    def do_check(self):
        if not self.json.get():
            self.log("❌ Choose a Story JSON first.")
            return
        try:
            data = json.load(open(self.json.get(), encoding="utf-8"))
            self.log_box.delete("1.0", tk.END)
            check_segments(data, self.log)
        except Exception as e:
            self.log("❌ " + str(e))

    def do_prompts(self):
        if not self.json.get():
            self.log("❌ Choose a Story JSON first.")
            return
        def run():
            try:
                data = json.load(open(self.json.get(), encoding="utf-8"))
                export_prompts(data, self.prompts_out.get() or "scene_prompts.txt", self.log)
            except Exception as e:
                self.log("❌ " + str(e))
        threading.Thread(target=run, daemon=True).start()

    def log(self, m):
        self.q.put(str(m))

    def progress(self, v):
        self.q.put(("P", v))

    def drain(self):
        while not self.q.empty():
            it = self.q.get()
            if isinstance(it, tuple):
                self.bar["value"] = it[1]
            else:
                self.log_box.insert(tk.END, it + "\n")
                self.log_box.see(tk.END)
        self.root.after(100, self.drain)

    def f(self, v, d):
        try:
            return float(v.get())
        except ValueError:
            return d

    def _cfg(self):
        return {
            "json": self.json.get(),
            "voice_source": self.voice_source.get(),
            "voice_preset": self.voice_preset.get(),
            "voice_style": self.voice_style.get(),
            "voice_ref": self.voice_ref.get(),
            "voice_file": self.voice_file.get(),
            "cfg_value": self.f(self.cfg_value, 2.0),
            "do_normalize": self.do_normalize.get(),
            "denoise": self.denoise.get(),
            "max_workers": int(self.f(self.max_workers, 4)),
            "bg_music": self.bg_music.get(),
            "bg_percent": self.f(self.bg_percent, 0.18),
            "voice_out": self.voice_out.get() or "voice_final.mp3",
            "segments_output": self.segments_output.get() or "segments_audio",
            "auto_amb": self.auto_amb.get(),
        }

    def start_voice(self):
        if not self.json.get():
            self.log("❌ Choose a Story JSON.")
            return
        cfg = self._cfg()
        self.bar["value"] = 0
        self.log_box.delete("1.0", tk.END)
        def run():
            try:
                run_voice_only(cfg, self.log, self.progress)
            except Exception:
                self.log("❌ ERROR:\n" + traceback.format_exc())
        threading.Thread(target=run, daemon=True).start()


def _gradio_run_voice(json_path, voice_source, voice_preset, voice_style, voice_ref,
                      voice_file, cfg_value, do_normalize, denoise, auto_emotion, speaker_lock, max_workers,
                      bg_music, bg_percent, auto_amb, voice_out, segments_output):
    """Stream pipeline logs to Gradio while the blocking work runs in a thread."""
    messages = []
    updates = queue.Queue()
    finished = threading.Event()
    result = {"path": None}

    def ui_log(message):
        updates.put(str(message))

    def work():
        try:
            story_path = json_path[0] if isinstance(json_path, (list, tuple)) and json_path else json_path
            if not story_path or not os.path.exists(story_path):
                raise ValueError("Choose a valid Story JSON file.")
            output = os.path.abspath(voice_out or "voice_final.mp3")
            segment_dir = os.path.abspath(segments_output or "segments_audio")
            os.makedirs(os.path.dirname(output), exist_ok=True)
            cfg = {
                "json": story_path, "voice_source": voice_source,
                "voice_preset": voice_preset, "voice_style": voice_style,
                "voice_ref": voice_ref or "", "voice_file": voice_file or "",
                "cfg_value": float(cfg_value), "do_normalize": bool(do_normalize),
                "denoise": bool(denoise), "auto_emotion": bool(auto_emotion),
                "speaker_lock": bool(speaker_lock),
                "max_workers": int(max_workers),
                "bg_music": bg_music or "", "bg_percent": float(bg_percent),
                "auto_amb": bool(auto_amb), "voice_out": output,
                "segments_output": segment_dir,
            }
            data = json.load(open(story_path, encoding="utf-8"))
            result["path"] = _make_voice(cfg, data.get("segments", []), ui_log)
            if result["path"]:
                ui_log(f"\n✅ VOICE READY → {result['path']}")
        except Exception:
            ui_log("❌ ERROR:\n" + traceback.format_exc())
        finally:
            finished.set()

    threading.Thread(target=work, daemon=True).start()
    while not finished.is_set() or not updates.empty():
        try:
            while True:
                messages.append(updates.get_nowait())
        except queue.Empty:
            pass
        yield "\n".join(messages), result["path"]
        time.sleep(0.25)

    yield "\n".join(messages), result["path"]


def _gradio_run_video(json_path, voice_source, voice_preset, voice_style, voice_ref,
                      voice_file, cfg_value, do_normalize, denoise, auto_emotion, speaker_lock, max_workers,
                      bg_music, bg_percent, auto_amb, voice_out, segments_output,
                      story_authors, story_card_duration, story_card_bg,
                      video_out, video_only, full_json_video, video_test_duration,
                      resolution, fps, crf, transition_duration, effect_style, preview, show_title,
                      channel, logo, use_logo):
    """Stream the voice + built-in video-rendering pipeline to Gradio."""
    messages, updates = [], queue.Queue()
    finished = threading.Event()
    result = {"path": None}

    def ui_log(message):
        updates.put(str(message))

    def work():
        try:
            json_paths = list(json_path) if isinstance(json_path, (list, tuple)) else [json_path]
            json_paths = [path for path in json_paths if path]
            if not json_paths or any(not os.path.exists(path) for path in json_paths):
                raise ValueError("Choose valid Story JSON files.")
            authors = [name.strip() or "Anonymous" for name in (story_authors or "").split(",")]
            cfg = {
                "json": json_paths[0], "voice_source": voice_source,
                "voice_preset": voice_preset, "voice_style": voice_style,
                "voice_ref": voice_ref or "", "voice_file": voice_file or "",
                "cfg_value": float(cfg_value), "do_normalize": bool(do_normalize),
                "denoise": bool(denoise), "auto_emotion": bool(auto_emotion),
                "speaker_lock": bool(speaker_lock),
                "max_workers": int(max_workers), "bg_music": bg_music or "",
                "bg_percent": float(bg_percent), "auto_amb": bool(auto_amb),
                "voice_out": os.path.abspath(voice_out or "voice_final.mp3"),
                "segments_output": os.path.abspath(segments_output or "segments_audio"),
                "video_out": video_out or "", "video_only": bool(video_only),
                "full_json_video": bool(full_json_video),
                "video_test_duration": float(video_test_duration), "resolution": resolution,
                "fps": int(fps), "crf": int(crf),
                "transition_duration": float(transition_duration),
                "effect_style": effect_style, "preview": bool(preview),
                "show_title": bool(show_title), "channel": channel or "",
                "logo": logo or "", "use_logo": bool(use_logo),
                "story_card_duration": float(story_card_duration),
                "story_card_bg": story_card_bg or "",
            }
            result["path"] = run_make_multi_story_video(
                cfg, json_paths, authors, ui_log, lambda value: None)
        except Exception:
            ui_log("❌ ERROR:\n" + traceback.format_exc())
        finally:
            finished.set()

    threading.Thread(target=work, daemon=True).start()
    while not finished.is_set() or not updates.empty():
        try:
            while True:
                messages.append(updates.get_nowait())
        except queue.Empty:
            pass
        yield "\n".join(messages), result["path"]
        time.sleep(0.25)
    yield "\n".join(messages), result["path"]


def build_gradio_ui():
    """Automation-Studio-style web UI for voice and video generation."""
    import gradio as gr

    css = """
    #run-log textarea { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    .studio-title { margin-bottom: 0 !important; }
    """
    with gr.Blocks(title="Horror Voice Studio") as demo:
        gr.Markdown("# 🎙 FilesAtNightfall — Voice & Video Studio", elem_classes="studio-title")
        gr.Markdown("VoxCPM2 cloning · resilient parallel generation · built-in cinematic video renderer")

        with gr.Row():
            with gr.Column(scale=2):
                gr.Markdown("### 📖 Story")
                story_json = gr.File(label="Story JSON files (upload in Story 1, 2, 3 order)",
                                     file_types=[".json"], type="filepath", file_count="multiple")
                story_authors = gr.Textbox(
                    value="Anonymous", label="Authors in order (comma-separated)",
                    placeholder="Anonymous, Ranger P., John")
                story_card_duration = gr.Slider(
                    3, 5, value=4, step=0.5,
                    label="Story-card duration (3–5 seconds)")
                story_card_bg = gr.Textbox(
                    value=STORY_CARD_BG, label="Story-card background sound")
                voice_source = gr.Radio(["generate", "existing"], value="generate", label="Voice source")
                voice_out = gr.Textbox(value="voice_final.mp3", label="Final voice output")
                segments_output = gr.Textbox(value="segments_audio", label="Individual segment folder")

            with gr.Column(scale=5):
                with gr.Accordion("🎙 Voice settings", open=True):
                    with gr.Row():
                        voice_preset = gr.Dropdown(list(VOICE_PRESETS), value="Balanced Neutral", label="Preset")
                        voice_style = gr.Dropdown(list(VOICE_STYLES), value="Balanced", label="Style")
                    voice_ref = gr.File(label="Reference voice (optional)", file_types=["audio"], type="filepath")
                    voice_file = gr.File(label="Existing voice (when source = existing)", file_types=["audio"], type="filepath")

                with gr.Accordion("⚙️ VoxCPM2 advanced", open=False):
                    with gr.Row():
                        cfg_value = gr.Slider(1.0, 3.0, value=1.7, step=0.1, label="CFG guidance (1.6–1.8 for Khmer)")
                        max_workers = gr.Slider(1, 2, value=2, step=1, label="Parallel workers")
                    with gr.Row():
                        do_normalize = gr.Checkbox(value=False, label="Text normalization")
                        denoise = gr.Checkbox(value=True, label="Reference denoising")
                    auto_emotion = gr.Checkbox(
                        value=False, label="Different feeling for every segment",
                        info="Uses emotion/feeling/mood from JSON, or detects it from English segment text.txt.")
                    speaker_lock = gr.Checkbox(
                        value=True, label="Lock one narrator voice for all segments",
                        info="Creates one anchor voice, then clones it to prevent gender/age changes.")

                with gr.Accordion("🎵 Background audio", open=False):
                    bg_music = gr.File(label="Music (optional)", file_types=["audio"], type="filepath")
                    bg_percent = gr.Slider(0.0, 0.5, value=0.18, step=0.01, label="Music level")
                    auto_amb = gr.Checkbox(value=False, label="Generate dark ambience when no music is selected")

                with gr.Accordion("🎬 Video settings (built into jruy.py)", open=True):
                    video_out = gr.Textbox(value="", label="Video output (.mp4; blank = beside JSON)")
                    with gr.Row():
                        video_only = gr.Checkbox(
                            value=False, label="Skip voice generation (silent video)")
                        full_json_video = gr.Checkbox(
                            value=True, label="Render full JSON story without voice")
                        video_test_duration = gr.Slider(
                            5, 120, value=20, step=5, label="Silent test duration (seconds)")
                    with gr.Row():
                        resolution = gr.Dropdown(["1920x1080", "1280x720"], value="1280x720", label="Resolution")
                        fps = gr.Slider(12, 30, value=20, step=1, label="FPS")
                        crf = gr.Slider(18, 28, value=18, step=1, label="Quality CRF")
                    transition_duration = gr.Slider(
                        0.3, 3.0, value=1.5, step=0.1,
                        label="Transition speed (seconds; higher = slower)")
                    effect_style = gr.Dropdown(
                        ["Horror Cinematic", "Blood Red", "Black & White Dread", "Natural Dark"],
                        value="Horror Cinematic", label="Horror visual effect")
                    with gr.Row():
                        preview = gr.Checkbox(value=True, label="Preview first 20 seconds")
                        show_title = gr.Checkbox(value=True, label="Title card from JSON")
                        use_logo = gr.Checkbox(value=False, label="Show logo")
                    channel = gr.Textbox(value="Mr. Midnight", label="Channel name")
                    logo = gr.File(label="Logo (optional)", file_types=["image"], type="filepath")

        with gr.Row():
            run_btn = gr.Button("▶ Generate Voice")
            video_btn = gr.Button("🎬 Make Video", variant="primary")
        with gr.Row():
            run_log = gr.Textbox(label="Live log", lines=18, interactive=False, elem_id="run-log", scale=4)
            output_audio = gr.Audio(label="Final voice", type="filepath", interactive=False, scale=2)
            output_video = gr.Video(label="Final video", interactive=False, scale=3)

        inputs = [story_json, voice_source, voice_preset, voice_style, voice_ref,
                  voice_file, cfg_value, do_normalize, denoise, auto_emotion, speaker_lock, max_workers,
                  bg_music, bg_percent, auto_amb, voice_out, segments_output]
        run_btn.click(_gradio_run_voice, inputs=inputs, outputs=[run_log, output_audio])
        video_inputs = inputs + [story_authors, story_card_duration, story_card_bg,
                                 video_out, video_only, full_json_video, video_test_duration,
                                 resolution, fps, crf, transition_duration, effect_style,
                                 preview, show_title,
                                 channel, logo, use_logo]
        video_btn.click(_gradio_run_video, inputs=video_inputs, outputs=[run_log, output_video])

    return demo, css


if __name__ == "__main__":
    demo, ui_css = build_gradio_ui()
    demo.launch(inbrowser=True, share=False, css=ui_css,
                theme=__import__("gradio").themes.Base(primary_hue="blue", neutral_hue="slate"))
