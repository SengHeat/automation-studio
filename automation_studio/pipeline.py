"""Top-level voice and video workflow orchestration."""

import json
import math
import os
import shutil
import subprocess
import tempfile

from .audio import merge_voice, normalize_audio_lufs
from .config import FFMPEG, FFPROBE, PEXELS_KEY
from .image_generator import generate_ai_images
from .stock_media import (_segment_time_range, _story_video_duration,
                          download_missing_stock, replace_short_videos_with_images,
                          download_stock_audio)
from .video import render_json_video
from .voice import generate_voice


def _flatten_segments(data):
    """Return a normalized flat segment list from either a simple or compilation JSON."""
    if data.get("segments"):
        return data["segments"]
    stories = data.get("stories", [])
    if not stories:
        return []
    project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
    narration_note = project.get("narration_notes", "Slow, restrained horror narration.")
    flat = []
    global_id = 1
    for story in stories:
        for seg in story.get("segments", []):
            segment = dict(seg)
            segment["segment_id"] = global_id
            segment.setdefault("target_text", segment.get("narration", ""))
            segment.setdefault("title", f"seg{global_id}")
            segment.setdefault("control_instruction", narration_note)
            flat.append(segment)
            global_id += 1
    return flat


def _resolve_bg_music(cfg, clips_folder, log):
    """Return the final bg_music path: uploaded file > stock query > empty string."""
    uploaded = (cfg.get("bg_music") or "").strip()
    if uploaded and os.path.exists(uploaded):
        log(f"  Using uploaded background music: {os.path.basename(uploaded)}")
        return uploaded
    query = (cfg.get("bg_sound_query") or "").strip()
    if query:
        audio_cache = os.path.join(clips_folder, "_bg_audio_cache")
        downloaded = download_stock_audio(query, audio_cache, log)
        if downloaded:
            return downloaded
        log("  stock audio download failed; continuing without background music.")
    return ""


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

        voice_ref = cfg.get("voice_ref", "")
        if voice_ref and os.path.exists(voice_ref):
            clean_ref = os.path.join(tmp, "reference_clean.wav")
            cleaned = subprocess.run(
                [FFMPEG, "-y", "-i", voice_ref,
                 "-af", "highpass=f=80,lowpass=f=10000,afftdn=nr=40:nf=-38:tn=1:gs=12",
                 "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", clean_ref],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=90,
            )
            if (cleaned.returncode == 0 and os.path.exists(clean_ref)
                    and os.path.getsize(clean_ref) > 1500):
                voice_ref = clean_ref
                log("  🧹 Cleaned reference voice before VoxCPM cloning")
            else:
                log("  ⚠️ Reference cleanup failed; using the original reference")

        log("STEP 1  generating voice (parallel)...")
        if not generate_voice(segments, voice_ref, tmp, log, voice_cfg, max_workers):
            log("⚠️ Voice generation had issues, but continuing...")

        log("STEP 2  merging voice + pauses + music...")

        segments_output = cfg.get("segments_output", "")
        if segments_output:
            log(f"  📁 Individual segments will be saved to: {segments_output}")

        _voice_clips_folder = cfg.get("clips_folder") or (
            os.path.splitext(os.path.abspath(cfg.get("json") or "voice.mp3"))[0] + "_stock_clips"
            if cfg.get("json") else os.path.join(tmp, "_bg_audio_cache"))
        effective_bg = _resolve_bg_music(cfg, _voice_clips_folder, log)
        result = merge_voice(tmp, segments, out_voice, effective_bg, cfg["bg_percent"], log,
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
    with open(cfg["json"], encoding="utf-8") as f:
        data = json.load(f)
    segments = _flatten_segments(data)
    voice = _make_voice(cfg, segments, log)
    if voice:
        log(f"\n✅ VOICE READY → {voice}")


def run_make_video(cfg, log, progress):
    """Generate/prepare narration, then render video with the engine in 1.py."""
    if not FFMPEG or not FFPROBE:
        log("❌ ffmpeg/ffprobe not found.")
        return None
    with open(cfg["json"], encoding="utf-8") as f:
        data = json.load(f)
    segments = _flatten_segments(data)
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
    cfg["bg_music"] = _resolve_bg_music(cfg, clips_folder, log)
    missing = 0
    json_base = os.path.dirname(os.path.abspath(cfg["json"]))
    for segment in segments:
        media = next((str(p) for p in (segment.get("image_or_video") or []) if p), "")
        resolved = media if os.path.isabs(media) else os.path.join(json_base, media)
        if not media or not os.path.exists(resolved):
            missing += 1
    if missing:
        if cfg.get("use_ai_images"):
            log(f"STEP 3  generating AI images (DALL-E 3) for {missing} missing segments...")
            count = generate_ai_images(cfg["json"], segments, clips_folder, log,
                                       max_workers=int(cfg.get("max_workers", 2)))
            log(f"  AI image generation complete: {count} image(s) saved in {clips_folder}")
            # Fall back to Pexels for any still-missing segments
            still_missing = sum(
                1 for seg in segments
                if not next((str(p) for p in (seg.get("image_or_video") or []) if p), ""))
            if still_missing:
                log(f"  {still_missing} segment(s) still missing — downloading from Pexels...")
                count2 = download_missing_stock(cfg["json"], segments, clips_folder, log)
                log(f"  Pexels fallback: {count2} clip(s) downloaded")
        else:
            log(f"STEP 3  downloading stock video for {missing} missing segments...")
            count = download_missing_stock(cfg["json"], segments, clips_folder, log)
            log(f"  stock download complete: {count} new clips saved in {clips_folder}")
    image_fallbacks = replace_short_videos_with_images(
        cfg["json"], segments, clips_folder, log)
    if image_fallbacks:
        log(f"  short-video fallback: {image_fallbacks} segment(s) changed to slow-zoom images")

    try:
        width, height = (int(v) for v in cfg.get("resolution", "1280x720").split("x"))
    except (ValueError, TypeError):
        width, height = 1280, 720
    output = os.path.abspath(cfg.get("video_out") or
                             (os.path.splitext(cfg["json"])[0] + ".mp4"))
    os.makedirs(os.path.dirname(output), exist_ok=True)
    render_cfg = {"width": width, "height": height, "fps": int(cfg.get("fps", 20)), "crf": int(cfg.get("crf", 18)),
                  "preview": bool(cfg.get("preview", False)) and not bool(cfg.get("video_only", False)), "out": output,
                  "title": data.get("title", ""), "subtitle": data.get("subtitle", ""),
                  "show_title": bool(cfg.get("show_title", True)), "logo": cfg.get("logo", ""),
                  "use_logo": bool(cfg.get("use_logo", False)), "logo_corner": cfg.get("logo_corner", "bottom-right"),
                  "channel": cfg.get("channel", ""), "channel_corner": cfg.get("channel_corner", "top-right"),
                  "mute_audio": bool(cfg.get("video_only", False)),
                  "effect_style": cfg.get("effect_style", "Horror Cinematic"), "bg_music": cfg.get("bg_music", ""),
                  "bg_percent": float(cfg.get("bg_percent", 0.18)), "json": cfg["json"],
                  "enable_subtitles": bool(cfg.get("enable_subtitles", False)),
                  "subtitle_size": int(cfg.get("subtitle_size", 28)),
                  "subtitle_position": cfg.get("subtitle_position", "bottom"),
                  "make_thumbnail": bool(cfg.get("make_thumbnail", False)),
                  "use_ai_images": bool(cfg.get("use_ai_images", False))}
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
