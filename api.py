"""FastAPI backend — exposes all automation-studio logic as REST + SSE endpoints."""

from __future__ import annotations

import json
import os
import queue as qmod
import re
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Bootstrap project (loads .env, discovers ffmpeg, etc.) ──────────────────
from automation_studio.config import (
    APP_DEBUG, DEBUG_STORY_JSON, DEFAULT_STORY_CARD_DURATION, DEFAULT_VOICE_REF,
    EMOTION_DIRECTIONS, STORY_CARD_BG, VOICE_PRESETS, VOICE_STYLES,
)
from automation_studio.audio import export_srt, generate_youtube_chapters
from automation_studio.gradio_ui import _eta_estimate
from automation_studio.pipeline import _flatten_segments, _make_voice, run_make_video, run_voice_only
from automation_studio.story_generator import (
    _GENRES, convert_text_to_story_json, generate_story_json, save_story_json,
)
from automation_studio.video import run_make_multi_story_video

# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(title="Automation Studio API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory job store ──────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}
_queue_state: list[dict] = []
_queue_stop_events: dict[str, threading.Event] = {}


def _new_job() -> str:
    jid = str(uuid.uuid4())
    _jobs[jid] = {"q": qmod.Queue(), "result": {}, "done": threading.Event()}
    return jid


def _job_log(jid: str, message: str) -> None:
    if jid in _jobs:
        _jobs[jid]["q"].put({"log": str(message)})


def _job_done(jid: str, result: dict | None = None) -> None:
    if jid in _jobs:
        if result:
            _jobs[jid]["result"] = result
            _jobs[jid]["q"].put({"done": True, "result": result})
        else:
            _jobs[jid]["q"].put({"done": True})
        _jobs[jid]["done"].set()


# ── SSE streaming helper ──────────────────────────────────────────────────────

async def _sse_stream(jid: str):
    """Yield SSE events for a job until it finishes."""
    if jid not in _jobs:
        yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
        return
    job = _jobs[jid]
    while True:
        try:
            while True:
                item = job["q"].get_nowait()
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("done"):
                    return
        except qmod.Empty:
            pass
        if job["done"].is_set() and job["q"].empty():
            return
        await asyncio.sleep(0.15)


import asyncio

# ── Upload temp dir ───────────────────────────────────────────────────────────

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

FIXTURE_DIR = Path("fixtures")
TEST_STORY_FIXTURE = FIXTURE_DIR / "test_story_home_invasion.json"


async def _save_upload(file: UploadFile) -> str:
    dest = UPLOAD_DIR / f"{uuid.uuid4()}_{file.filename}"
    content = await file.read()
    dest.write_bytes(content)
    return str(dest)


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURE — test story for structure validation renders
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/fixture/test-story")
async def get_test_story_fixture():
    """Return the built-in Home Invasion test story JSON for structure-validation renders."""
    if not TEST_STORY_FIXTURE.exists():
        raise HTTPException(status_code=404, detail="Test fixture not found")
    return FileResponse(
        str(TEST_STORY_FIXTURE),
        media_type="application/json",
        filename="test_story_home_invasion.json",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/config")
async def get_config():
    return {
        "voice_presets": list(VOICE_PRESETS.keys()),
        "voice_styles": list(VOICE_STYLES.keys()),
        "genres": list(_GENRES.keys()),
        "emotions": list(EMOTION_DIRECTIONS.keys()),
        "languages": ["English", "Khmer", "French", "Spanish", "Japanese"],
        "resolutions": ["1280x720", "1920x1080"],
        "effect_styles": ["Horror Cinematic", "Blood Red", "Black & White Dread", "Natural Dark"],
        "subtitle_positions": ["bottom", "top", "center"],
        "logo_corners": ["bottom-right", "bottom-left", "top-right", "top-left"],
        "defaults": {
            "voice_preset": "Balanced Neutral",
            "voice_style": "Balanced",
            "cfg_value": 1.7,
            "max_workers": 2,
            "bg_percent": 0.18,
            "resolution": "1280x720",
            "fps": 20,
            "crf": 18,
            "transition_duration": 1.5,
            "effect_style": "Horror Cinematic",
            "subtitle_size": 28,
            "story_card_duration": DEFAULT_STORY_CARD_DURATION,
            "default_voice_ref": DEFAULT_VOICE_REF or "",
            "story_card_bg": STORY_CARD_BG or "",
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# JOB STREAM
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    return StreamingResponse(
        _sse_stream(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# STORY GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

class GenerateStoryBody(BaseModel):
    title: str
    premise: str = ""
    genre: str = "Horror"
    duration_minutes: float = 3.0
    segment_count: int = 5
    language: str = "English"
    output_path: str = "generated_story.json"


@app.post("/api/story/generate")
async def story_generate(body: GenerateStoryBody):
    jid = _new_job()

    def work():
        try:
            data = generate_story_json(
                title=body.title.strip(),
                premise=body.premise.strip(),
                genre=body.genre,
                duration_minutes=body.duration_minutes,
                segment_count=body.segment_count,
                language=body.language,
                log=lambda m: _job_log(jid, m),
            )
            if data:
                saved = save_story_json(data, body.output_path or "generated_story.json",
                                        lambda m: _job_log(jid, m))
                _job_done(jid, {"path": saved, "json": data})
            else:
                _job_log(jid, "❌ Generation returned no data.")
                _job_done(jid)
        except Exception:
            _job_log(jid, "❌ ERROR:\n" + traceback.format_exc())
            _job_done(jid)

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


class ConvertTextBody(BaseModel):
    text: str
    genre: str = "Horror"
    language: str = "English"
    segment_count: int = 5
    output_path: str = "converted_story.json"


@app.post("/api/story/convert")
async def story_convert(body: ConvertTextBody):
    jid = _new_job()

    def work():
        try:
            data = convert_text_to_story_json(
                plain_text=body.text,
                genre=body.genre,
                language=body.language,
                segment_count=body.segment_count,
                output_path=body.output_path,
                log=lambda m: _job_log(jid, m),
            )
            if data:
                saved = save_story_json(data, body.output_path,
                                        lambda m: _job_log(jid, m))
                _job_done(jid, {"path": saved, "json": data})
            else:
                _job_log(jid, "❌ Conversion returned no data.")
                _job_done(jid)
        except Exception:
            _job_log(jid, "❌ ERROR:\n" + traceback.format_exc())
            _job_done(jid)

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


# ═══════════════════════════════════════════════════════════════════════════════
# VOICE GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/voice")
async def run_voice(
    story_json: list[UploadFile] = File(default=[]),
    json_path: str = Form(""),
    voice_source: str = Form("generate"),
    voice_preset: str = Form("Balanced Neutral"),
    voice_style: str = Form("Balanced"),
    cfg_value: float = Form(1.7),
    do_normalize: bool = Form(False),
    denoise: bool = Form(True),
    auto_emotion: bool = Form(False),
    speaker_lock: bool = Form(True),
    max_workers: int = Form(2),
    bg_sound_query: str = Form(""),
    bg_percent: float = Form(0.18),
    auto_amb: bool = Form(False),
    voice_out: str = Form("voice_final.mp3"),
    segments_output: str = Form("segments_audio"),
    voice_ref: Optional[UploadFile] = File(None),
    voice_file: Optional[UploadFile] = File(None),
    bg_music: Optional[UploadFile] = File(None),
):
    jid = _new_job()
    if json_path.strip():
        resolved = os.path.abspath(json_path.strip())
        if not os.path.exists(resolved):
            raise HTTPException(status_code=400, detail=f"JSON path not found: {resolved}")
        json_paths = [resolved]
    elif story_json:
        json_paths = [await _save_upload(f) for f in story_json]
    else:
        raise HTTPException(status_code=422, detail="Provide either story_json file or json_path")
    voice_ref_path = await _save_upload(voice_ref) if voice_ref else DEFAULT_VOICE_REF or ""
    voice_file_path = await _save_upload(voice_file) if voice_file else ""
    bg_music_path = await _save_upload(bg_music) if bg_music else ""

    cfg = {
        "json": json_paths[0], "voice_source": voice_source,
        "voice_preset": voice_preset, "voice_style": voice_style,
        "voice_ref": voice_ref_path, "voice_file": voice_file_path,
        "cfg_value": cfg_value, "do_normalize": do_normalize,
        "denoise": denoise, "auto_emotion": auto_emotion,
        "speaker_lock": speaker_lock, "max_workers": max_workers,
        "bg_music": bg_music_path, "bg_sound_query": bg_sound_query,
        "bg_percent": bg_percent, "auto_amb": auto_amb,
        "voice_out": os.path.abspath(voice_out),
        "segments_output": os.path.abspath(segments_output),
    }

    def work():
        try:
            with open(json_paths[0], encoding="utf-8") as f:
                data = json.load(f)
            result_path = _make_voice(cfg, _flatten_segments(data),
                                      lambda m: _job_log(jid, m))
            if result_path:
                _job_log(jid, f"✅ VOICE READY → {result_path}")
                _job_done(jid, {"path": result_path})
            else:
                _job_done(jid)
        except Exception:
            _job_log(jid, "❌ ERROR:\n" + traceback.format_exc())
            _job_done(jid)

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


# ═══════════════════════════════════════════════════════════════════════════════
# VIDEO GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/video")
async def run_video(
    story_json: list[UploadFile] = File(default=[]),
    json_path: str = Form(""),
    voice_source: str = Form("generate"),
    voice_preset: str = Form("Balanced Neutral"),
    voice_style: str = Form("Balanced"),
    cfg_value: float = Form(1.7),
    do_normalize: bool = Form(False),
    denoise: bool = Form(True),
    auto_emotion: bool = Form(False),
    speaker_lock: bool = Form(True),
    max_workers: int = Form(2),
    bg_sound_query: str = Form(""),
    bg_percent: float = Form(0.18),
    auto_amb: bool = Form(False),
    voice_out: str = Form("voice_final.mp3"),
    segments_output: str = Form("segments_audio"),
    story_authors: str = Form("Anonymous"),
    story_card_duration: float = Form(DEFAULT_STORY_CARD_DURATION),
    story_card_bg: str = Form(""),
    video_out: str = Form(""),
    resolution: str = Form("1280x720"),
    fps: int = Form(20),
    crf: int = Form(18),
    transition_duration: float = Form(1.5),
    effect_style: str = Form("Horror Cinematic"),
    enable_subtitles: bool = Form(False),
    subtitle_size: int = Form(28),
    subtitle_position: str = Form("bottom"),
    make_thumbnail: bool = Form(True),
    use_ai_images: bool = Form(False),
    show_title: bool = Form(False),
    use_logo: bool = Form(False),
    logo_corner: str = Form("bottom-right"),
    channel: str = Form(""),
    channel_corner: str = Form("top-right"),
    video_only: bool = Form(False),
    voice_ref: Optional[UploadFile] = File(None),
    voice_file: Optional[UploadFile] = File(None),
    bg_music: Optional[UploadFile] = File(None),
    logo: Optional[UploadFile] = File(None),
):
    jid = _new_job()
    if json_path.strip():
        resolved = os.path.abspath(json_path.strip())
        if not os.path.exists(resolved):
            raise HTTPException(status_code=400, detail=f"JSON path not found: {resolved}")
        json_paths = [resolved]
    elif story_json:
        json_paths = [await _save_upload(f) for f in story_json]
    else:
        raise HTTPException(status_code=422, detail="Provide either story_json file or json_path")
    voice_ref_path = await _save_upload(voice_ref) if voice_ref else DEFAULT_VOICE_REF or ""
    voice_file_path = await _save_upload(voice_file) if voice_file else ""
    bg_music_path = await _save_upload(bg_music) if bg_music else ""
    logo_path = await _save_upload(logo) if logo else ""

    authors = [n.strip() or "Anonymous" for n in story_authors.split(",")]
    cfg = {
        "json": json_paths[0], "voice_source": voice_source,
        "voice_preset": voice_preset, "voice_style": voice_style,
        "voice_ref": voice_ref_path, "voice_file": voice_file_path,
        "cfg_value": cfg_value, "do_normalize": do_normalize,
        "denoise": denoise, "auto_emotion": auto_emotion,
        "speaker_lock": speaker_lock, "max_workers": max_workers,
        "bg_music": bg_music_path, "bg_sound_query": bg_sound_query,
        "bg_percent": bg_percent, "auto_amb": auto_amb,
        "voice_out": os.path.abspath(voice_out or "voice_final.mp3"),
        "segments_output": os.path.abspath(segments_output or "segments_audio"),
        "video_out": video_out or "", "video_only": video_only,
        "resolution": resolution, "fps": fps, "crf": crf,
        "transition_duration": transition_duration, "effect_style": effect_style,
        "enable_subtitles": enable_subtitles, "subtitle_size": subtitle_size,
        "subtitle_position": subtitle_position,
        "make_thumbnail": make_thumbnail, "use_ai_images": use_ai_images,
        "show_title": show_title, "logo": logo_path, "use_logo": use_logo,
        "logo_corner": logo_corner, "channel": channel, "channel_corner": channel_corner,
        "preview": False,
        "story_card_duration": story_card_duration,
        "story_card_bg": story_card_bg or "",
    }

    def work():
        try:
            output_path = run_make_multi_story_video(
                cfg, json_paths, authors, lambda m: _job_log(jid, m), lambda v: None)
            if output_path and os.path.exists(output_path):
                _job_log(jid, f"✅ VIDEO READY → {output_path}")
                _job_done(jid, {"path": output_path})
            else:
                _job_log(jid, "❌ Video rendering finished without output file.")
                _job_done(jid)
        except Exception:
            _job_log(jid, "❌ ERROR:\n" + traceback.format_exc())
            _job_done(jid)

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS: ETA / SRT / CHAPTERS / PREVIEW SEGMENT
# ═══════════════════════════════════════════════════════════════════════════════

class EtaBody(BaseModel):
    text: str = ""
    json_path: str = ""
    wpm: float = 130
    cpm: float = 280


@app.post("/api/eta")
async def eta(body: EtaBody):
    breakdown, total = _eta_estimate(
        body.text or "",
        body.json_path or None,
        body.wpm,
        body.cpm,
    )
    return {"breakdown": breakdown, "total": total}


class SrtBody(BaseModel):
    voice_out: str = "voice_final.mp3"
    json_path: str = ""


@app.post("/api/srt")
async def srt_export(body: SrtBody):
    voice_path = body.voice_out.strip() or "voice_final.mp3"
    timeline_path = voice_path + ".timeline.json"
    if not os.path.exists(timeline_path):
        return {"status": f"❌ Timeline not found: {timeline_path}", "file_url": None}
    try:
        segments = []
        if body.json_path and os.path.exists(body.json_path):
            with open(body.json_path, encoding="utf-8") as f:
                segments = _flatten_segments(json.load(f))
        srt_path = os.path.splitext(voice_path)[0] + ".srt"
        result = export_srt(timeline_path, segments, srt_path)
        if result:
            return {"status": f"✅ SRT exported: {result}",
                    "file_url": f"/api/files/download?path={result}"}
        return {"status": "❌ SRT export failed.", "file_url": None}
    except Exception:
        return {"status": "❌ ERROR:\n" + traceback.format_exc(), "file_url": None}


class ChaptersBody(BaseModel):
    voice_out: str = "voice_final.mp3"
    json_path: str = ""


@app.post("/api/chapters")
async def chapters(body: ChaptersBody):
    voice_path = body.voice_out.strip() or "voice_final.mp3"
    timeline_path = voice_path + ".timeline.json"
    if not os.path.exists(timeline_path):
        return {"status": "❌ Timeline not found. Generate voice first.", "chapters": ""}
    try:
        segments = []
        if body.json_path and os.path.exists(body.json_path):
            with open(body.json_path, encoding="utf-8") as f:
                segments = _flatten_segments(json.load(f))
        text = generate_youtube_chapters(segments, timeline_path)
        if text:
            return {"status": "✅ Chapters generated.", "chapters": text}
        return {"status": "❌ No timing data found.", "chapters": ""}
    except Exception:
        return {"status": "❌ ERROR:\n" + traceback.format_exc(), "chapters": ""}


@app.post("/api/preview-segment")
async def preview_segment(
    story_json: UploadFile = File(...),
    segment_index: int = Form(0),
    voice_preset: str = Form("Balanced Neutral"),
    voice_style: str = Form("Balanced"),
    cfg_value: float = Form(1.7),
    do_normalize: bool = Form(False),
    denoise: bool = Form(True),
    speaker_lock: bool = Form(True),
    voice_ref: Optional[UploadFile] = File(None),
):
    jid = _new_job()
    json_path = await _save_upload(story_json)
    voice_ref_path = await _save_upload(voice_ref) if voice_ref else DEFAULT_VOICE_REF or ""

    def work():
        try:
            import glob
            import tempfile
            from automation_studio.voice import generate_voice
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            segments = _flatten_segments(data)
            if not segments:
                _job_log(jid, "❌ No segments found.")
                _job_done(jid)
                return
            idx = max(0, min(segment_index, len(segments) - 1))
            seg = segments[idx]
            _job_log(jid, f"Previewing segment {idx + 1}: \"{(seg.get('target_text') or '')[:60]}...\"")
            tmp = tempfile.mkdtemp(prefix="preview_")
            voice_cfg = {
                "voice_preset": voice_preset,
                "voice_style": voice_style,
                "cfg_value": cfg_value,
                "do_normalize": do_normalize,
                "denoise": denoise,
                "auto_emotion": False,
                "speaker_lock": speaker_lock,
            }
            generate_voice([seg], voice_ref_path, tmp, lambda m: _job_log(jid, m),
                           voice_cfg, max_workers=1)
            clips = glob.glob(os.path.join(tmp, "*.mp3")) + glob.glob(os.path.join(tmp, "*.wav"))
            if clips:
                _job_log(jid, "✅ Preview ready.")
                _job_done(jid, {"path": clips[0]})
            else:
                _job_log(jid, "❌ No audio generated.")
                _job_done(jid)
        except Exception:
            _job_log(jid, "❌ ERROR:\n" + traceback.format_exc())
            _job_done(jid)

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


# ═══════════════════════════════════════════════════════════════════════════════
# PRESETS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/preset/save")
async def preset_save(body: dict):
    preset_path = (body.pop("preset_path", None) or "studio_preset.json").strip()
    try:
        with open(preset_path, "w", encoding="utf-8") as f:
            json.dump(body, f, indent=2)
        return {"status": f"✅ Preset saved: {preset_path}"}
    except Exception as e:
        return {"status": f"❌ Save failed: {e}"}


@app.get("/api/preset/load")
async def preset_load(path: str = "studio_preset.json"):
    if not os.path.exists(path):
        raise HTTPException(404, f"Preset not found: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# HISTORY
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/history/scan")
async def history_scan(folder: str = "."):
    if not os.path.isdir(folder):
        raise HTTPException(400, f"Folder not found: {folder}")
    files = []
    for root, _dirs, filenames in os.walk(folder):
        for fname in sorted(filenames):
            if not fname.lower().endswith(".json"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                if "segments" not in data and "stories" not in data:
                    continue
                files.append({
                    "path": fpath,
                    "filename": fname,
                    "title": data.get("title", fname),
                    "language": data.get("language", "—"),
                })
            except Exception:
                pass
    return {"files": files}


@app.get("/api/history/preview")
async def history_preview(path: str):
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        segs = list(data.get("segments") or [])
        for story in data.get("stories") or []:
            segs.extend(story.get("segments") or [])
        return {
            "title": data.get("title", "—"),
            "language": data.get("language", "—"),
            "segment_count": len(segs),
            "filename": os.path.basename(path),
            "path": path,
            "json": data,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/api/history/file")
async def history_delete(path: str):
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    try:
        os.remove(path)
        return {"status": f"✅ Deleted: {os.path.basename(path)}"}
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# YOUTUBE
# ═══════════════════════════════════════════════════════════════════════════════

class YoutubeAuthorizeBody(BaseModel):
    client_secrets_path: str
    token_path: str = "youtube_token.json"


@app.post("/api/youtube/authorize")
async def youtube_authorize(body: YoutubeAuthorizeBody):
    jid = _new_job()

    def work():
        try:
            from automation_studio.uploader import (
                load_client_secrets, start_device_flow, save_tokens,
            )
            import urllib.error, urllib.parse, urllib.request

            if not os.path.exists(body.client_secrets_path):
                _job_log(jid, "❌ client_secrets.json not found.")
                _job_done(jid)
                return

            secrets = load_client_secrets(body.client_secrets_path)
            _job_log(jid, "🔐 Starting YouTube authorization (device flow)...")
            flow = start_device_flow(secrets["client_id"])
            url = flow.get("verification_url", "https://google.com/device")
            code = flow.get("user_code", "")
            _job_log(jid, f"👉 Visit:  {url}")
            _job_log(jid, f"   Enter:  {code}")
            _job_log(jid, "Waiting for authorization (up to 5 minutes)...")

            interval = int(flow.get("interval", 5))
            device_code = flow["device_code"]
            deadline = time.time() + 300
            token = None
            while time.time() < deadline:
                time.sleep(interval)
                try:
                    payload = urllib.parse.urlencode({
                        "client_id": secrets["client_id"],
                        "client_secret": secrets["client_secret"],
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth2:grant-type:device_code",
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        "https://oauth2.googleapis.com/token", data=payload,
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
                    try:
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                    except urllib.error.HTTPError as exc:
                        data = json.loads(exc.read().decode("utf-8"))
                    if "access_token" in data:
                        data["issued_at"] = time.time()
                        save_tokens(body.token_path, data)
                        _job_log(jid, f"✅ Authorized! Token saved to: {body.token_path}")
                        token = data
                        break
                    if data.get("error") == "slow_down":
                        interval += 5
                    elif data.get("error") not in ("authorization_pending", None):
                        _job_log(jid, f"❌ OAuth error: {data.get('error')}")
                        break
                    else:
                        _job_log(jid, "  Still waiting...")
                except Exception as exc:
                    _job_log(jid, f"  Poll error: {exc}")
            if not token:
                _job_log(jid, "❌ Authorization timed out or failed.")
            _job_done(jid, {"authorized": bool(token)})
        except Exception:
            _job_log(jid, "❌ ERROR:\n" + traceback.format_exc())
            _job_done(jid)

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


class YoutubeUploadBody(BaseModel):
    video_path: str
    title: str = ""
    description: str = ""
    tags: str = ""
    privacy: str = "private"
    client_secrets_path: str
    token_path: str = "youtube_token.json"


@app.post("/api/youtube/upload")
async def youtube_upload(body: YoutubeUploadBody):
    jid = _new_job()

    def work():
        try:
            from automation_studio.uploader import upload_to_youtube
            if not os.path.exists(body.video_path):
                _job_log(jid, "❌ Video file not found.")
                _job_done(jid)
                return
            video_id = upload_to_youtube(
                video_path=body.video_path,
                title=body.title or os.path.basename(body.video_path),
                description=body.description,
                tags=body.tags,
                privacy=body.privacy,
                client_secrets_path=body.client_secrets_path,
                token_path=body.token_path,
                log=lambda m: _job_log(jid, m),
            )
            _job_done(jid, {"video_id": video_id or ""})
        except Exception:
            _job_log(jid, "❌ ERROR:\n" + traceback.format_exc())
            _job_done(jid)

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH QUEUE
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/queue/scan")
async def queue_scan(folder: str = "."):
    if not os.path.isdir(folder):
        raise HTTPException(400, f"Folder not found: {folder}")
    added = 0
    existing = {j["json_path"] for j in _queue_state}
    for root, _dirs, files in os.walk(folder):
        for fname in sorted(files):
            if not fname.lower().endswith(".json"):
                continue
            fpath = os.path.join(root, fname)
            if fpath in existing:
                continue
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                if "segments" not in data and "stories" not in data:
                    continue
                _queue_state.append({
                    "json_path": fpath, "effect_style": "Horror Cinematic",
                    "privacy": "private", "auto_upload": False, "status": "⏳ Queued",
                })
                added += 1
            except Exception:
                pass
    return {"added": added, "total": len(_queue_state), "jobs": _queue_state}


@app.post("/api/queue/clear")
async def queue_clear():
    _queue_state.clear()
    return {"status": "Queue cleared.", "jobs": []}


class QueueRunBody(BaseModel):
    effect_style: str = "Horror Cinematic"
    resolution: str = "1280x720"
    fps: int = 20
    crf: int = 18
    voice_preset: str = "Balanced Neutral"
    auto_upload: bool = False
    client_secrets_path: str = ""
    token_path: str = "youtube_token.json"


@app.post("/api/queue/run")
async def queue_run(body: QueueRunBody):
    if not _queue_state:
        raise HTTPException(400, "Queue is empty.")
    jid = _new_job()
    stop_event = threading.Event()
    _queue_stop_events[jid] = stop_event

    base_cfg = {
        "voice_source": "generate", "voice_preset": body.voice_preset,
        "voice_style": "Balanced", "voice_ref": "", "voice_file": "",
        "cfg_value": 1.7, "do_normalize": False, "denoise": True,
        "auto_emotion": False, "speaker_lock": True, "max_workers": 2,
        "bg_music": "", "bg_sound_query": "", "bg_percent": 0.18, "auto_amb": False,
        "resolution": body.resolution, "fps": body.fps, "crf": body.crf,
        "transition_duration": 1.5, "effect_style": body.effect_style,
        "enable_subtitles": False, "subtitle_size": 28, "subtitle_position": "bottom",
        "make_thumbnail": True, "use_ai_images": False, "preview": False,
        "show_title": False, "channel": "", "logo": "", "use_logo": False,
        "story_card_duration": 5.0, "story_card_bg": "", "video_only": False,
    }

    for job in _queue_state:
        if job["status"] == "⏳ Queued":
            job["auto_upload"] = body.auto_upload
            job["effect_style"] = body.effect_style

    def work():
        try:
            from automation_studio.batch_queue import run_batch
            q = _jobs[jid]["q"]
            run_batch(
                jobs=_queue_state, base_cfg=base_cfg,
                client_secrets_path=body.client_secrets_path,
                token_path=body.token_path,
                log_queue=q,
                stop_event=stop_event,
            )
            _job_done(jid, {"jobs": _queue_state})
        except Exception:
            _job_log(jid, "❌ ERROR:\n" + traceback.format_exc())
            _job_done(jid)

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


@app.post("/api/queue/stop/{job_id}")
async def queue_stop(job_id: str):
    ev = _queue_stop_events.get(job_id)
    if ev:
        ev.set()
        return {"status": "⏹ Stop requested — current job will finish, then queue halts."}
    return {"status": "⚠️ No active queue to stop."}


# ═══════════════════════════════════════════════════════════════════════════════
# FILE DOWNLOAD / SERVE
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/files/download")
async def file_download(path: str):
    if not os.path.exists(path):
        raise HTTPException(404, f"File not found: {path}")
    return FileResponse(path)


# ═══════════════════════════════════════════════════════════════════════════════
# SERVE NEXT.JS STATIC BUILD (must be last)
# ═══════════════════════════════════════════════════════════════════════════════

_FRONTEND_OUT = Path(__file__).parent / "frontend" / "out"
if _FRONTEND_OUT.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_OUT), html=True), name="static")


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
