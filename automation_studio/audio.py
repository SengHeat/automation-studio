"""Audio inspection, normalization, chunking, ambience, and final voice mixing."""

import glob
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading

from .config import FAST, FFMPEG, FFPROBE, TENSE


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
    """Join Vox chunks without MP3 padding gaps or waveform-boundary pops."""
    if len(parts) == 1:
        shutil.move(parts[0], output)
        return True
    try:
        from pydub import AudioSegment
        from pydub.utils import which as _which

        AudioSegment.converter = _which("ffmpeg")
        decoded = []
        for part in parts:
            clip = AudioSegment.from_file(part).set_frame_rate(48000).set_channels(1)
            # Vox chunks can begin/end away from the zero crossing. These tiny
            # fades suppress the resulting impulse without trimming speech.
            edge_ms = min(12, max(1, len(clip) // 20))
            decoded.append(clip.fade_in(edge_ms).fade_out(edge_ms))

        combined = decoded[0]
        for clip in decoded[1:]:
            crossfade_ms = min(18, len(combined), len(clip))
            combined = combined.append(clip, crossfade=crossfade_ms)

        combined.export(output, format="mp3", bitrate="256k")
        return os.path.exists(output) and os.path.getsize(output) > 1500
    except Exception:
        return False


_log_lock = threading.Lock()


def safe_log(log, msg):
    with _log_lock:
        log(msg)


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
            # Large boosts make the Vox/reference noise floor audible between
            # words. Keep correction gentle; final loudness is handled once
            # after every segment has been merged.
            gain = max(-6.0, min(4.0, target_voice_dbfs - clip.dBFS))
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

    log("  cleaning narration noise and normalizing to -16 LUFS...")
    subprocess.run([FFMPEG, "-y", "-i", tmp.name,
                    "-af", (
                        "highpass=f=80,lowpass=f=10000,"
                        "afftdn=nr=40:nf=-38:tn=1:gs=12,"
                        "agate=threshold=0.016:ratio=8:range=0.02:"
                        "attack=4:release=100,"
                        "loudnorm=I=-16:TP=-1.5:LRA=9"
                    ),
                    "-c:a", "libmp3lame", "-b:a", "256k", out_voice],
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
