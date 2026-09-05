"""
Per-segment background music for Whispered Confessions.

Mood detection per segment → Pixabay/ccMixter download → composite BG audio
timed to the voice timeline with 2-second crossfades between mood zones.

Pass the returned composite path straight into cfg["bg_music"] — the existing
pipeline handles the final voice/bg ducked mix via bg_percent.
"""

import json
import os
import shutil
import subprocess
import tempfile

from .config import FFMPEG, FFPROBE
from .config import segment_emotion
from .stock_media import download_stock_audio

# ── Mood catalogue ─────────────────────────────────────────────────────────────

MOOD_QUERIES: dict[str, str] = {
    "calm":      "calm dark ambient quiet night",
    "uneasy":    "dark ambient uneasy subtle dread",
    "tension":   "suspense tension thriller ambient",
    "dread":     "horror dread ominous dark",
    "reveal":    "horror dramatic reveal dark sting",
    "aftermath": "somber dark aftermath ambient",
    "end":       "dark cinematic ending quiet ambient",
}

EMOTION_TO_MOOD: dict[str, str] = {
    "neutral":    "calm",
    "calm":       "calm",
    "mysterious": "uneasy",
    "tense":      "tension",
    "fear":       "dread",
    "angry":      "tension",
    "urgent":     "tension",
    "shocked":    "reveal",
    "sad":        "aftermath",
    "ominous":    "dread",
}

_MOOD_KEYS = list(MOOD_QUERIES.keys())

LICENSE_NOTE = (
    "Background music: Pixabay Music (pixabay.com/music) — free for commercial use, "
    "no attribution required. ccMixter fallback tracks (ccmixter.org) are CC BY 3.0."
)


# ── Mood classification ─────────────────────────────────────────────────────────

def _classify_mood(segment: dict, index: int, total: int) -> str:
    """Blend narrative position with per-segment emotion to select a mood key."""
    emotion, _ = segment_emotion(segment, auto_detect=True)
    emotion_mood = EMOTION_TO_MOOD.get(emotion, "calm")

    if index == 0:
        return "calm"
    if index >= total - 1:
        return "end"

    frac = index / max(total - 1, 1)
    if frac < 0.15:
        # Early story: soften strong emotions into uneasy
        return emotion_mood if emotion_mood not in ("calm", "reveal") else "uneasy"
    if frac > 0.85:
        # Late story: resolve into aftermath unless climax
        return emotion_mood if emotion_mood in ("dread", "reveal") else "aftermath"

    return emotion_mood


# ── Per-segment plan ────────────────────────────────────────────────────────────

def build_segment_bg_plan(segments: list[dict], cache_dir: str, log) -> list[dict]:
    """
    Return [{segment_id, mood, audio_path}, ...].

    Downloads one track per unique mood (cached). Adjacent duplicate moods
    reuse the same file — no redundant downloads.
    """
    os.makedirs(cache_dir, exist_ok=True)
    total = len(segments)
    mood_cache: dict[str, str] = {}
    plan: list[dict] = []

    for index, seg in enumerate(segments):
        sid  = int(seg.get("segment_id", index + 1))
        mood = _classify_mood(seg, index, total)

        if mood not in mood_cache:
            query = MOOD_QUERIES[mood]
            pick  = _MOOD_KEYS.index(mood)          # deterministic, varies per mood
            path  = download_stock_audio(query, cache_dir, log, choice_index=pick)
            mood_cache[mood] = path
            if path:
                log(f"  🎵 [{mood}] → {os.path.basename(path)}")
            else:
                log(f"  ⚠️  [{mood}] no track found — silence placeholder")

        plan.append({
            "segment_id": sid,
            "mood": mood,
            "audio_path": mood_cache.get(mood, ""),
        })

    return plan


# ── Composite builder ───────────────────────────────────────────────────────────

def _probe_dur(path: str) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def build_bg_composite(
    voice_path: str,
    bg_plan: list[dict],
    output_path: str,
    log,
    crossfade_sec: float = 2.0,
) -> str:
    """
    Stitch per-segment mood tracks into one composite BG audio file.

    Reads <voice_path>.timeline.json for accurate per-segment timing.
    Falls back to equal slices when the timeline is absent.
    Segments crossfade into each other; each track is pre-normalised to
    -28 LUFS so it sits well under the voice after bg_percent ducking.

    Returns output_path on success, "" on failure.
    """
    if not bg_plan:
        return ""

    # ── Load timing from voice timeline ─────────────────────────────────────
    timeline_path = voice_path + ".timeline.json"
    timing: dict[int, tuple[float, float]] = {}   # sid → (start_sec, duration_sec)
    if os.path.exists(timeline_path):
        try:
            with open(timeline_path, encoding="utf-8") as fh:
                for entry in json.load(fh):
                    sid   = entry.get("segment_id")
                    start = entry.get("start_ms", 0) / 1000.0
                    end   = entry.get("end_ms",   0) / 1000.0
                    if sid is not None and end > start:
                        timing[sid] = (start, end - start)
        except Exception:
            pass

    if not timing:
        total_voice = _probe_dur(voice_path) if os.path.exists(voice_path) else 60.0
        slice_dur   = total_voice / max(len(bg_plan), 1)
        for i, entry in enumerate(bg_plan):
            timing[entry["segment_id"]] = (i * slice_dur, slice_dur)

    # ── Render one looped+faded clip per segment ─────────────────────────────
    work = tempfile.mkdtemp(prefix="bgcomp_")
    clips: list[str] = []

    try:
        ordered = [e for e in bg_plan if e["segment_id"] in timing]
        for i, entry in enumerate(ordered):
            sid     = entry["segment_id"]
            src     = entry.get("audio_path", "")
            _, dur  = timing[sid]
            is_last = (i == len(ordered) - 1)
            # Extend each clip by crossfade amount so acrossfade has material
            render_dur = dur + (0.0 if is_last else crossfade_sec)

            out = os.path.join(work, f"bgseg_{i:04d}.mp3")

            if src and os.path.exists(src):
                fade_out_st = max(0.0, render_dur - 1.2)
                cmd = [
                    FFMPEG, "-y",
                    "-stream_loop", "-1", "-i", src,
                    "-t", f"{render_dur:.3f}",
                    "-af", (
                        f"afade=t=in:st=0:d=0.8,"
                        f"afade=t=out:st={fade_out_st:.3f}:d=1.2,"
                        "loudnorm=I=-28:TP=-3:LRA=7"
                    ),
                    "-c:a", "libmp3lame", "-b:a", "192k",
                    "-ar", "44100", "-ac", "2", out,
                ]
            else:
                cmd = [
                    FFMPEG, "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", f"{render_dur:.3f}",
                    "-c:a", "libmp3lame", "-b:a", "32k",
                    "-ar", "44100", "-ac", "2", out,
                ]

            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
                clips.append(out)

        if not clips:
            return ""

        if len(clips) == 1:
            shutil.copy2(clips[0], output_path)
            log("  🎵 bg composite: 1 segment (no crossfade needed)")
            return output_path

        # ── Crossfade all clips ──────────────────────────────────────────────
        cmd = [FFMPEG, "-y"]
        for c in clips:
            cmd += ["-i", c]

        filters: list[str] = []
        prev = "0:a"
        for idx in range(1, len(clips)):
            label = f"cf{idx}"
            filters.append(
                f"[{prev}][{idx}:a]acrossfade=d={crossfade_sec:.1f}:c1=tri:c2=tri[{label}]"
            )
            prev = label

        cmd += [
            "-filter_complex", ";".join(filters),
            "-map", f"[{prev}]",
            "-c:a", "libmp3lame", "-b:a", "192k",
            "-ar", "44100", "-ac", "2", output_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            log(f"  🎵 bg composite ready: {len(clips)} mood zones, {crossfade_sec:.1f}s crossfades")
            return output_path

        log("  ⚠️  bg composite crossfade failed:\n" +
            "\n".join(r.stderr.splitlines()[-5:]))
        return ""

    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── Attribution ─────────────────────────────────────────────────────────────────

def attribution_text(bg_plan: list[dict]) -> str:
    """Plain-text attribution block suitable for a YouTube description."""
    moods = sorted({e["mood"] for e in bg_plan if e.get("audio_path")})
    if not moods:
        return ""
    return "\n".join([
        "🎵 Background Music",
        LICENSE_NOTE,
        "Mood zones: " + ", ".join(moods),
    ])
