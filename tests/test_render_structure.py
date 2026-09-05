"""
Structure-validation test renderer for Whispered Confessions pipeline.

Renders the full video assembly (starting → stories → ending) without TTS.
Each segment becomes a color-coded placeholder card with the visual_prompt text
overlaid. Story-before / story-after transition cards are included.

Usage:
    python -m tests.test_render_structure <json_path> [output.mp4]
    python -m tests.test_render_structure uploads/my_story.json

Options (env vars):
    TEST_WIDTH   default 640
    TEST_HEIGHT  default 360
    TEST_FPS     default 20
    TEST_CRF     default 28  (fast / low-quality)
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time


# ── helpers ──────────────────────────────────────────────────────────────────

FFMPEG = shutil.which("ffmpeg")


def _fail(msg: str) -> None:
    print(f"\n❌  {msg}", file=sys.stderr)
    sys.exit(1)


def _parse_duration(field: str) -> float:
    """Parse 'MM:SS-MM:SS' or 'SS-SS' → float seconds of the segment."""
    value = str(field or "").strip()
    m = re.match(r"^\s*([\d:.]+)\s*[-–—]\s*([\d:.]+)\s*$", value)
    if not m:
        return 0.0

    def _tv(s: str) -> float:
        parts = s.split(":")
        try:
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            if len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            return float(parts[0])
        except ValueError:
            return 0.0

    start = _tv(m.group(1))
    end = _tv(m.group(2))
    return max(0.0, end - start)


def _fmt(secs: float) -> str:
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _esc(text: str) -> str:
    """Escape text for FFmpeg drawtext."""
    return (text
            .replace("\\", "\\\\")
            .replace("'", "\u2019")
            .replace(":", r"\:")
            .replace(",", r"\,")
            .replace("[", r"\[")
            .replace("]", r"\]")
            .replace("%", r"\%"))


# ── card factories ────────────────────────────────────────────────────────────

def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    """Convert '#rrggbb', '0xrrggbb', or 'rrggbb' to (r, g, b)."""
    c = color.strip()
    if c.lower().startswith("0x"):
        c = c[2:]
    elif c.startswith("#"):
        c = c[1:]
    c = c.zfill(6)[-6:]
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _make_card(
    out_path: str,
    duration: float,
    bg_color: str,
    lines: list[tuple[str, int, str]],   # [(text, fontsize, rgb_color_str), ...]
    width: int,
    height: int,
    fps: int,
    crf: int,
) -> str:
    """Render a plain color card using Pillow (no drawtext needed), return out_path."""
    from PIL import Image, ImageDraw, ImageFont

    if duration < 0.5:
        duration = 0.5

    bg_rgb = _hex_to_rgb(bg_color)
    img = Image.new("RGB", (width, height), bg_rgb)
    draw = ImageDraw.Draw(img)

    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    def _font(size: int):
        for p in font_paths:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except OSError:
                    pass
        return ImageFont.load_default()

    margin = max(16, int(width * 0.04))
    max_text_w = width - margin * 2
    y = height // 8

    for text, fontsize, color_str in lines:
        fg = _hex_to_rgb(color_str)
        fnt = _font(fontsize)
        # Manual word-wrap via Pillow bbox
        words = text.split()
        current_line = ""
        rendered_lines: list[str] = []
        for word in words:
            test = (current_line + " " + word).strip()
            bbox = draw.textbbox((0, 0), test, font=fnt)
            if bbox[2] - bbox[0] > max_text_w and current_line:
                rendered_lines.append(current_line)
                current_line = word
            else:
                current_line = test
        if current_line:
            rendered_lines.append(current_line)

        for line in rendered_lines:
            bbox = draw.textbbox((0, 0), line, font=fnt)
            lw = bbox[2] - bbox[0]
            lh = bbox[3] - bbox[1]
            x = (width - lw) // 2
            # Subtle shadow
            draw.text((x + 2, y + 2), line, font=fnt, fill=(0, 0, 0))
            draw.text((x, y), line, font=fnt, fill=fg)
            y += lh + max(6, fontsize // 5)
        y += fontsize // 2  # extra gap between logical lines

    # Save image to temp file
    img_path = out_path + ".png"
    img.save(img_path, "PNG")

    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-framerate", str(fps), "-i", img_path,
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", str(duration),
        "-vf", "format=yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "64k", "-ar", "44100", "-ac", "1",
        "-shortest", out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        os.unlink(img_path)
    except OSError:
        pass
    if result.returncode != 0:
        print(f"  ⚠️  card failed ({out_path}):\n"
              + "\n".join(result.stderr.splitlines()[-4:]))
    return out_path


# Palette for segment types (RGB hex strings for Pillow)
_PALETTE = {
    "starting": "0d1a2a",   # dark navy
    "segment":  "1a0d0d",   # dark maroon
    "before":   "0a0a1a",   # deep indigo
    "after":    "0a1a0a",   # deep green
    "ending":   "1a1a0a",   # dark olive
}


def _segment_card(work: str, idx: int, segment: dict, kind: str,
                  width: int, height: int, fps: int, crf: int) -> tuple[str, float]:
    """Build one segment placeholder card. Returns (path, duration_seconds)."""
    dur = _parse_duration(segment.get("duration", ""))
    if dur <= 0:
        dur = 10.0   # fallback for segments with no/zero duration

    prompt = segment.get("visual_prompt") or segment.get("video_feed_description") or ""
    seg_id = segment.get("segment_id") or segment.get("segment") or idx
    title = segment.get("title") or f"Seg {seg_id}"

    lines = [
        (kind.upper(), 18, "0xaaaaaa"),
        (f"[{title}]  {_fmt(dur)}", 22, "0xdddddd"),
        (prompt[:200], 16, "0xcccc88"),
    ]
    out = os.path.join(work, f"seg_{idx:04d}.mp4")
    _make_card(out, dur, _PALETTE.get(kind, _PALETTE["segment"]),
               lines, width, height, fps, crf)
    return out, dur


def _title_card(work: str, name: str, duration: float, bg: str,
                lines: list[tuple[str, int, str]],
                width: int, height: int, fps: int, crf: int) -> str:
    out = os.path.join(work, f"{name}.mp4")
    _make_card(out, duration, bg, lines, width, height, fps, crf)
    return out


# ── main ─────────────────────────────────────────────────────────────────────

def run(json_path: str, output_path: str) -> None:
    if not FFMPEG:
        _fail("ffmpeg not found in PATH")
    if not os.path.exists(json_path):
        _fail(f"JSON not found: {json_path}")

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
    project_title = project.get("title") or data.get("title") or "Untitled"
    channel = project.get("channel") or ""
    estimated_total = project.get("estimated_duration", "")

    WIDTH  = int(os.getenv("TEST_WIDTH",  640))
    HEIGHT = int(os.getenv("TEST_HEIGHT", 360))
    FPS    = int(os.getenv("TEST_FPS",    20))
    CRF    = int(os.getenv("TEST_CRF",    28))

    print(f"\n{'='*60}")
    print(f"  TEST RENDER — {project_title}")
    print(f"  Channel: {channel or '(none)'}   Estimated: {estimated_total or '?'}")
    print(f"  Resolution: {WIDTH}x{HEIGHT}  FPS:{FPS}  CRF:{CRF}")
    print(f"{'='*60}\n")

    work = tempfile.mkdtemp(prefix="test_render_")
    pieces: list[str] = []
    card_idx = 0
    total_dur = 0.0
    story_summary: list[dict] = []

    try:
        # ── STARTING ────────────────────────────────────────────────────────
        starting = data.get("starting")
        if isinstance(starting, dict):
            narr = starting.get("narration") or starting.get("target_text") or ""
            dur = _parse_duration(starting.get("duration", "")) or max(5.0, len(narr) / 14)
            title_text = starting.get("title") or "Intro"
            prompt = starting.get("visual_prompt") or ""
            card_idx += 1
            path = _title_card(
                work, f"starting_{card_idx:04d}", dur,
                _PALETTE["starting"],
                [
                    ("▶ STARTING  " + title_text, 24, "0xffffff"),
                    (prompt[:180], 15, "0xcccc88"),
                    (f"Duration: {_fmt(dur)}", 14, "0x888888"),
                ],
                WIDTH, HEIGHT, FPS, CRF,
            )
            pieces.append(path)
            total_dur += dur
            print(f"  [starting]  {title_text:<30}  {_fmt(dur):>7}")

        # ── STORIES ─────────────────────────────────────────────────────────
        stories = data.get("stories", [])
        for story in stories:
            snum = story.get("story_number") or story.get("number") or (stories.index(story) + 1)
            stitle = story.get("title") or f"Story {snum}"
            yt_title = story.get("youtube_title") or ""
            thumb_text = story.get("thumbnail_text") or ""
            viewer_q = story.get("viewer_question") or ""
            est_dur = story.get("estimated_duration") or ""

            # BEFORE STORY CARD
            card_idx += 1
            before_dur = 5.0
            before_lines = [
                (f"STORY {snum}", 34, "0xffffff"),
                (stitle, 22, "0xddaaaa"),
            ]
            if yt_title:
                before_lines.append((yt_title[:90], 15, "0xaaaacc"))
            if thumb_text:
                before_lines.append((f'"{thumb_text}"', 14, "0xcc8888"))
            before_path = _title_card(
                work, f"before_{card_idx:04d}", before_dur,
                _PALETTE["before"], before_lines,
                WIDTH, HEIGHT, FPS, CRF,
            )
            pieces.append(before_path)
            total_dur += before_dur

            # STORY SEGMENTS
            segments = story.get("segments", [])
            story_dur = 0.0
            seg_count = 0
            for seg in segments:
                card_idx += 1
                path, dur = _segment_card(
                    work, card_idx, seg, "segment",
                    WIDTH, HEIGHT, FPS, CRF,
                )
                pieces.append(path)
                story_dur += dur
                total_dur += dur
                seg_count += 1

            # AFTER STORY CARD
            card_idx += 1
            after_dur = 5.0
            after_lines = [
                (f"END OF STORY {snum}  [{_fmt(story_dur)}]", 20, "0xdddddd"),
            ]
            if viewer_q:
                after_lines.append((viewer_q[:160], 15, "0xaaccaa"))
            after_path = _title_card(
                work, f"after_{card_idx:04d}", after_dur,
                _PALETTE["after"], after_lines,
                WIDTH, HEIGHT, FPS, CRF,
            )
            pieces.append(after_path)
            total_dur += after_dur

            story_summary.append({
                "number": snum,
                "title": stitle,
                "segments": seg_count,
                "duration_s": story_dur,
                "estimated": est_dur,
            })
            print(f"  [story {snum}]  {stitle:<30}  {seg_count:>3} segs  "
                  f"{_fmt(story_dur):>7}  (est: {est_dur or '?'})")

        # ── ENDING ───────────────────────────────────────────────────────────
        ending = data.get("ending")
        if isinstance(ending, dict):
            narr = ending.get("narration") or ending.get("target_text") or ""
            dur = _parse_duration(ending.get("duration", "")) or max(5.0, len(narr) / 14)
            etitle = ending.get("title") or "End Screen"
            eprompt = ending.get("visual_prompt") or ""
            card_idx += 1
            path = _title_card(
                work, f"ending_{card_idx:04d}", dur,
                _PALETTE["ending"],
                [
                    ("▶ ENDING  " + etitle, 24, "0xffffff"),
                    (eprompt[:180], 15, "0xcccc88"),
                    (f"Duration: {_fmt(dur)}", 14, "0x888888"),
                ],
                WIDTH, HEIGHT, FPS, CRF,
            )
            pieces.append(path)
            total_dur += dur
            print(f"  [ending]    {etitle:<30}  {_fmt(dur):>7}")

        # ── CONCAT ───────────────────────────────────────────────────────────
        print(f"\n  Total pieces: {len(pieces)}   Est. runtime: {_fmt(total_dur)}\n")
        print("  Concatenating…")

        manifest = os.path.join(work, "manifest.txt")
        with open(manifest, "w", encoding="utf-8") as mf:
            for p in pieces:
                mf.write(f"file '{p}'\n")

        t0 = time.time()
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        join = subprocess.run(
            [
                FFMPEG, "-y",
                "-f", "concat", "-safe", "0", "-i", manifest,
                "-map", "0:v:0", "-map", "0:a:0",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", str(CRF),
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "64k", "-ar", "44100", "-ac", "1",
                "-movflags", "+faststart",
                output_path,
            ],
            capture_output=True, text=True,
        )
        elapsed = time.time() - t0

        if join.returncode != 0:
            print("❌  Final concat failed:")
            print("\n".join(join.stderr.splitlines()[-10:]))
            return

        actual_size = os.path.getsize(output_path) / 1024 / 1024

        # ── SUMMARY ──────────────────────────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"  ✅  TEST RENDER COMPLETE")
        print(f"{'='*60}")
        print(f"  Output : {output_path}")
        print(f"  Size   : {actual_size:.1f} MB")
        print(f"  Runtime: {_fmt(total_dur)} total")
        print(f"  Encode : {elapsed:.1f}s  ({total_dur/elapsed:.1f}x realtime)")
        print(f"\n  Per-story breakdown:")
        total_seg_count = 0
        for s in story_summary:
            est = s["estimated"] or "?"
            match_note = ""
            # Try to compare parsed estimate with actual
            ep = _parse_duration(est)
            if ep > 0:
                diff = s["duration_s"] - ep
                match_note = f"  Δ{diff:+.0f}s" if abs(diff) > 10 else "  ✓"
            print(f"    Story {s['number']:>2}: {s['title']:<32} "
                  f"{s['segments']:>3} segs  {_fmt(s['duration_s']):>7}  "
                  f"(est: {est}){match_note}")
            total_seg_count += s["segments"]
        print(f"\n  Total segments: {total_seg_count}")
        print(f"  Total cards   : {len(pieces)}")
        print(f"{'='*60}\n")

    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("Usage: python -m tests.test_render_structure <json> [output.mp4]")
        sys.exit(1)

    json_arg = sys.argv[1]
    out_arg = sys.argv[2] if len(sys.argv) >= 3 else (
        os.path.splitext(os.path.abspath(json_arg))[0] + "_test_render.mp4"
    )
    run(json_arg, out_arg)
