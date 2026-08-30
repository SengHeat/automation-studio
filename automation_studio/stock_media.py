"""Stock-media lookup, download, timing, and replacement helpers."""

import json
import os
import re
import shutil
import ssl
import subprocess
import urllib.parse
import urllib.request

from .config import FFMPEG, FFPROBE, PEXELS_KEY
from .audio import audio_dur


VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")


def _https_context():
    """Return a verified TLS context that also works with macOS Python installs."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


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
    with urllib.request.urlopen(request, timeout=30, context=_https_context()) as response:
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
    with urllib.request.urlopen(request, timeout=30, context=_https_context()) as response:
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
        with urllib.request.urlopen(
                request, timeout=180, context=_https_context()) as response, \
                open(partial, "wb") as output:
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
