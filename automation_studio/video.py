"""FFmpeg video rendering and multi-story compilation."""

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile

from .audio import audio_dur, normalize_audio_lufs
from .config import DEFAULT_STORY_CARD_DURATION, FFMPEG, FFPROBE, STORY_CARD_BG
from .stock_media import (VIDEO_EXT, _media_duration, _segment_time_range,
                          _story_video_duration, _video_duration, _video_holds,
                          _video_windows)


def _make_thumbnail(output_video_path, segments, title, width, height, log):
    """Generate a cinematic thumbnail JPG beside the output video.

    Extracts a frame from the first segment's media, applies a dark color
    grade via PIL, and overlays the story title in large white text.
    Saves as <output_video_path without .mp4>_thumbnail.jpg.
    """
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

    thumb_path = os.path.splitext(output_video_path)[0] + "_thumbnail.jpg"
    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    def _font(size):
        for p in font_paths:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except OSError:
                    pass
        return ImageFont.load_default()

    # Find first segment media
    source_frame = None
    for seg in segments:
        media_list = seg.get("image_or_video") or []
        media = next((str(m) for m in media_list if m and os.path.exists(str(m))), "")
        if media:
            try:
                tmp_frame = thumb_path + ".frame.jpg"
                if media.lower().endswith(VIDEO_EXT):
                    result = subprocess.run(
                        [FFMPEG, "-y", "-ss", "2", "-i", media,
                         "-frames:v", "1", "-q:v", "2", tmp_frame],
                        capture_output=True, timeout=30)
                    if result.returncode == 0 and os.path.exists(tmp_frame):
                        source_frame = tmp_frame
                else:
                    source_frame = media
            except Exception:
                pass
            if source_frame:
                break

    # Build base image
    if source_frame and os.path.exists(source_frame):
        try:
            img = Image.open(source_frame).convert("RGB")
            img = img.resize((width, height), Image.LANCZOS)
        except Exception:
            img = Image.new("RGB", (width, height), (5, 6, 9))
    else:
        img = Image.new("RGB", (width, height), (5, 6, 9))

    # Dark cinematic grade: reduce brightness, desaturate slightly
    img = ImageEnhance.Brightness(img).enhance(0.45)
    img = ImageEnhance.Color(img).enhance(0.7)
    img = ImageEnhance.Contrast(img).enhance(1.2)

    # Dark gradient overlay on bottom third
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    gradient_top = height * 2 // 3
    for y in range(gradient_top, height):
        alpha = int(210 * (y - gradient_top) / (height - gradient_top))
        draw_ov.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    # Draw title text
    draw = ImageDraw.Draw(img)
    clean_title = (title or "Untitled").upper()
    font_size = max(32, int(height * 0.09))
    title_font = _font(font_size)
    sub_font = _font(max(18, int(height * 0.04)))

    title_box = draw.textbbox((0, 0), clean_title, font=title_font)
    tw = title_box[2] - title_box[0]
    tx = max(40, (width - tw) // 2)
    ty = height - int(height * 0.22)

    # Shadow
    draw.text((tx + 3, ty + 3), clean_title, font=title_font, fill=(0, 0, 0, 180))
    # Main text
    draw.text((tx, ty), clean_title, font=title_font, fill=(240, 235, 220))

    # Thin red accent line above title
    draw.rectangle([(tx, ty - 14), (tx + min(tw, width - 80), ty - 10)],
                   fill=(160, 20, 20))

    # Subtitle "A Horror Story"
    genre_text = "A Cinematic Horror Story"
    sub_box = draw.textbbox((0, 0), genre_text, font=sub_font)
    sw = sub_box[2] - sub_box[0]
    draw.text(((width - sw) // 2, ty + font_size + 10), genre_text,
              font=sub_font, fill=(180, 170, 160))

    img.save(thumb_path, "JPEG", quality=92)

    # Clean temp frame
    if source_frame and source_frame.endswith(".frame.jpg"):
        try:
            os.unlink(source_frame)
        except OSError:
            pass

    log(f"  thumbnail saved → {os.path.basename(thumb_path)}")
    return thumb_path


def _build_subtitle_filter(segments, timeline_path, font_size=28, position="bottom"):
    """Build a comma-chained FFmpeg drawtext filter string from timeline.json.

    Each drawtext uses enable='between(t,start,end)' so only one caption is
    visible at a time. Returns "" if the timeline file is missing or empty.
    """
    if not timeline_path or not os.path.exists(timeline_path):
        return ""
    try:
        with open(timeline_path, encoding="utf-8") as _f:
            timeline = json.load(_f)
    except Exception:
        return ""
    if not timeline:
        return ""

    seg_map = {s.get("segment_id"): s for s in segments}
    y_expr = {"top": "30", "center": "(h-text_h)/2"}.get(position, "h-text_h-40")
    parts = []
    for entry in timeline:
        sid = entry.get("segment_id")
        start = entry.get("start_ms", 0) / 1000.0
        end = entry.get("end_ms", 0) / 1000.0
        if end <= start:
            continue
        seg = seg_map.get(sid, {})
        text = re.sub(r"\s+", " ", (seg.get("target_text") or seg.get("narration", ""))).strip()
        m = re.match(r"^[^.!?]+[.!?]", text)
        text = m.group(0).strip() if m else text[:100]
        if not text:
            continue
        # Escape characters special to FFmpeg drawtext
        text = text.replace("\\", "\\\\").replace("'", "\u2019").replace(":", "\\:").replace(",", "\\,").replace("[", "\\[").replace("]", "\\]")
        parts.append(
            f"drawtext=fontsize={font_size}:fontcolor=white"
            f":x=(w-text_w)/2:y={y_expr}"
            f":text='{text}'"
            f":enable='between(t,{start:.3f},{end:.3f})'"
            f":box=1:boxcolor=black@0.5:boxborderw=8"
        )
    return ",".join(parts)


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

            # JSON timing is rescaled to the generated narration, so a video
            # that looked long enough before voice generation can still be too
            # short for its final hold. Do not freeze its last frame. Convert a
            # representative frame to an image and apply continuous Ken Burns
            # motion for the complete narration-aligned duration instead.
            if media and media.lower().endswith(VIDEO_EXT):
                source_duration = _media_duration(media)
                if source_duration > 0 and source_duration + 0.25 < logical_duration:
                    poster = os.path.join(work, f"poster_{number:04d}.jpg")
                    seek = min(max(0.0, source_duration * 0.35), 3.0)
                    frame = subprocess.run(
                        [FFMPEG, "-y", "-ss", f"{seek:.3f}", "-i", media,
                         "-frames:v", "1", "-q:v", "2", poster],
                        capture_output=True, text=True,
                    )
                    if frame.returncode == 0 and os.path.exists(poster):
                        log(
                            f"  video hold {number}: source {source_duration:.1f}s < "
                            f"hold {logical_duration:.1f}s; using animated still frame"
                        )
                        media = poster

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

        # Phase 2.5 — subtitle burn-in (optional, one extra encode pass)
        if cfg.get("enable_subtitles") and not cfg.get("mute_audio"):
            timeline_path = voice_path + ".timeline.json"
            sub_filter = _build_subtitle_filter(
                segments, timeline_path,
                font_size=int(cfg.get("subtitle_size", 28)),
                position=cfg.get("subtitle_position", "bottom"),
            )
            if sub_filter:
                joined_sub = os.path.join(work, "joined_sub.mp4")
                sub_cmd = [FFMPEG, "-y", "-i", joined, "-vf", sub_filter,
                           "-c:v", "libx264", "-crf", str(crf),
                           "-preset", "fast", "-pix_fmt", "yuv420p", joined_sub]
                sub_result = subprocess.run(sub_cmd, capture_output=True, text=True, timeout=600)
                if sub_result.returncode == 0 and os.path.getsize(joined_sub) > 0:
                    joined = joined_sub
                    log("  subtitles burned in")
                else:
                    log("  ⚠️ subtitle burn-in failed — rendering without captions")
            else:
                log("  ⚠️ no timeline found — skipping subtitles")

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
                       "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", output]
            log(f"  adding background sound at {music_level:.0%} volume")
        elif cfg.get("mute_audio"):
            mux_cmd = [FFMPEG, "-y", "-i", joined, "-map", "0:v:0", "-t", str(voice_duration),
                       "-c:v", "copy", "-an", "-movflags", "+faststart", output]
        else:
            mux_cmd = [FFMPEG, "-y", "-i", joined, "-i", voice_path,
                       "-map", "0:v:0", "-map", "1:a:0", "-t", str(voice_duration),
                       "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
                       "-movflags", "+faststart", output]
        mux = subprocess.run(mux_cmd, capture_output=True, text=True)
        if mux.returncode != 0:
            log("❌ Final audio/video merge failed:\n" + "\n".join(mux.stderr.splitlines()[-6:]))
            return None
        progress(100)
        if cfg.get("make_thumbnail", False):
            try:
                _make_thumbnail(output, segments, cfg.get("title", ""), width, height, log)
            except Exception as exc:
                log(f"  ⚠️ thumbnail generation failed: {exc}")
        return output
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
                    "-ar", "48000", "-ac", "2",
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
    """Normalize every concat piece to AAC 48 kHz stereo.

    The concat demuxer requires matching stream parameters. Copying mono story
    audio beside stereo story-card audio can otherwise produce audible crackle.
    """
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", source], capture_output=True, text=True)
    if probe.stdout.strip():
        command = [
            FFMPEG, "-y", "-i", source, "-t", str(duration),
            "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
            "-af", "aresample=48000:async=1:first_pts=0",
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
            "-shortest", output,
        ]
    else:
        command = [
            FFMPEG, "-y", "-i", source, "-f", "lavfi",
            "-i", "anullsrc=r=48000:cl=stereo", "-t", str(duration),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
            "-shortest", output,
        ]
    result = subprocess.run(command, capture_output=True, text=True)
    return output if result.returncode == 0 else None


def expand_compilation_json(json_paths, supplied_authors, output_folder, log):
    """Expand JSON files containing a top-level stories[] compilation."""
    expanded, authors = [], []
    for source_path in json_paths:
        with open(source_path, encoding="utf-8") as _f:
            data = json.load(_f)
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
    # Imported lazily because the pipeline uses this module's render function.
    from .pipeline import run_make_video

    selected_script = os.path.abspath(json_paths[0])
    expansion_work = tempfile.mkdtemp(prefix="jruy_compilation_")
    json_paths, authors = expand_compilation_json(
        json_paths, authors, expansion_work, log)
    if len(json_paths) < 2:
        try:
            single_cfg = dict(cfg)
            single_cfg["json"] = json_paths[0]
            # An embedded story lives in expansion_work, which is deleted in
            # the finally block below. Keep the delivered MP4 beside the
            # originally selected JSON (or at the user's explicit path).
            single_cfg["video_out"] = os.path.abspath(
                cfg.get("video_out") or
                (os.path.splitext(selected_script)[0] + "_video.mp4")
            )
            return run_make_video(single_cfg, log, progress)
        finally:
            shutil.rmtree(expansion_work, ignore_errors=True)
    if cfg.get("voice_source") == "existing" and not cfg.get("video_only"):
        shutil.rmtree(expansion_work, ignore_errors=True)
        raise ValueError("Multi-story voice mode requires generated voice, not one existing voice file.")

    width, height = (int(value) for value in cfg.get("resolution", "1280x720").split("x"))
    fps = int(cfg.get("fps", 20))
    card_duration = max(
        3.0,
        min(5.0, float(cfg.get("story_card_duration", DEFAULT_STORY_CARD_DURATION))),
    )
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
             "-b:a", "256k", "-ar", "48000", "-ac", "2",
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
