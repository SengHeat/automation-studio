"""Story JSON validation and scene-prompt export helpers."""

import re


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
