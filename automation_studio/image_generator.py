"""AI image generation for video segments using OpenAI DALL-E 3."""

import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import OPENAI_KEY


def _dalle_image_url(prompt, api_key, size="1792x1024"):
    """Call DALL-E 3 and return the generated image URL."""
    payload = json.dumps({
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": "standard",
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "automation-studio/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["data"][0]["url"]


def _build_image_prompt(segment):
    """Build a cinematic DALL-E prompt from segment metadata."""
    query = (segment.get("stock_query") or
             segment.get("video_feed_description") or
             segment.get("title") or "").strip()
    emotion = str(segment.get("emotion") or segment.get("mood") or "").strip().lower()

    if emotion in ("fear", "tense", "ominous", "horror"):
        style = "dark and foreboding, cinematic horror, dramatic chiaroscuro lighting, atmospheric fog"
    elif emotion == "mysterious":
        style = "mysterious, atmospheric, moody side-lighting, cinematic depth"
    elif emotion == "sad":
        style = "melancholic, somber, muted desaturated colors, cinematic"
    elif emotion == "urgent":
        style = "tense, dramatic motion blur, high contrast cinematic"
    else:
        style = "cinematic, dramatic lighting, photorealistic, high quality"

    base = query if query else "dark cinematic landscape"
    return f"{base}, {style}, no text, no watermarks, wide landscape"


def _download_url(url, destination):
    """Download a remote URL to a local file."""
    req = urllib.request.Request(url, headers={"User-Agent": "automation-studio/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with open(destination, "wb") as f:
        f.write(data)


def generate_ai_images(json_path, segments, clips_folder, log,
                       api_key=OPENAI_KEY, max_workers=2):
    """Generate DALL-E 3 images for segments that are missing media.

    Updates each segment's ``image_or_video`` list in-place.
    Returns the count of newly generated/cached images used.
    """
    if not api_key:
        log("⚠️ OPENAI_KEY not set; AI image generation skipped.")
        return 0

    os.makedirs(clips_folder, exist_ok=True)
    json_base = os.path.dirname(os.path.abspath(json_path))

    missing = []
    for idx, segment in enumerate(segments):
        existing = next((str(p) for p in (segment.get("image_or_video") or []) if p), "")
        resolved = existing if os.path.isabs(existing) else os.path.join(json_base, existing)
        if not existing or not os.path.exists(resolved):
            missing.append((idx, segment))

    if not missing:
        log("  AI images: all segments already have media — skipping generation.")
        return 0

    log(f"  AI images: generating {len(missing)} image(s) with DALL-E 3...")

    def _slug(text):
        return re.sub(r"[^a-z0-9]+", "_", (text or "img")[:40].lower()).strip("_") or "img"

    def generate_one(idx_seg):
        idx, segment = idx_seg
        sid = int(segment.get("segment_id") or idx + 1)
        prompt = _build_image_prompt(segment)
        query = segment.get("stock_query") or segment.get("title") or ""
        dest = os.path.abspath(
            os.path.join(clips_folder, f"ai_{_slug(query)}_{sid:03d}.jpg"))

        if os.path.exists(dest) and os.path.getsize(dest) > 5000:
            log(f"  AI seg {sid}: using cached {os.path.basename(dest)}")
            return idx, dest, True

        try:
            log(f"  AI seg {sid}: '{prompt[:70]}...'")
            url = _dalle_image_url(prompt, api_key)
            _download_url(url, dest)
            log(f"  ✅ AI seg {sid}: saved {os.path.basename(dest)}")
            return idx, dest, True
        except Exception as exc:
            log(f"  ⚠️ AI seg {sid}: {str(exc)[:120]}")
            return idx, None, False

    generated = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(generate_one, item): item for item in missing}
        for future in as_completed(futures):
            idx, dest, ok = future.result()
            if ok and dest:
                segments[idx]["image_or_video"] = [dest]
                generated += 1

    log(f"  AI images: {generated}/{len(missing)} generated successfully.")
    return generated
