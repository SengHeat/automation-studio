"""Gradio callbacks, layout, and application launcher."""

import json
import os
import queue
import threading
import time
import traceback

from .config import (APP_DEBUG, DEBUG_STORY_JSON, DEFAULT_STORY_CARD_DURATION,
                     DEFAULT_VOICE_REF, STORY_CARD_BG, VOICE_PRESETS,
                     VOICE_STYLES)
from .audio import export_srt, generate_youtube_chapters
from .pipeline import _flatten_segments, _make_voice, run_make_video, run_voice_only
from .story_generator import _GENRES, generate_story_json, save_story_json
from .video import run_make_multi_story_video


def _gradio_run_voice(json_path, voice_source, voice_preset, voice_style, voice_ref,
                      voice_file, cfg_value, do_normalize, denoise, auto_emotion, speaker_lock, max_workers,
                      bg_music, bg_sound_query, bg_percent, auto_amb, voice_out, segments_output):
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
                "bg_music": bg_music or "", "bg_sound_query": bg_sound_query or "",
                "bg_percent": float(bg_percent),
                "auto_amb": bool(auto_amb), "voice_out": output,
                "segments_output": segment_dir,
            }
            with open(story_path, encoding="utf-8") as f:
                data = json.load(f)
            result["path"] = _make_voice(cfg, _flatten_segments(data), ui_log)
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
                      bg_music, bg_sound_query, bg_percent, auto_amb, voice_out, segments_output,
                      story_authors, story_card_duration, story_card_bg,
                      video_out,
                      resolution, fps, crf, transition_duration, effect_style,
                      enable_subtitles, subtitle_size, subtitle_position,
                      make_thumbnail=True, use_ai_images=False,
                      show_title=False, logo=None, use_logo=False,
                      logo_corner="bottom-right", channel="",
                      channel_corner="top-right"):
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
                "bg_sound_query": bg_sound_query or "",
                "bg_percent": float(bg_percent), "auto_amb": bool(auto_amb),
                "voice_out": os.path.abspath(voice_out or "voice_final.mp3"),
                "segments_output": os.path.abspath(segments_output or "segments_audio"),
                "video_out": video_out or "", "video_only": False,
                "resolution": resolution,
                "fps": int(fps), "crf": int(crf),
                "transition_duration": float(transition_duration),
                "effect_style": effect_style,
                "enable_subtitles": bool(enable_subtitles),
                "subtitle_size": int(subtitle_size),
                "subtitle_position": subtitle_position or "bottom",
                "make_thumbnail": bool(make_thumbnail),
                "use_ai_images": bool(use_ai_images),
                "show_title": bool(show_title),
                "logo": logo or "", "use_logo": bool(use_logo),
                "logo_corner": logo_corner or "bottom-right",
                "channel": channel or "",
                "channel_corner": channel_corner or "top-right",
                "preview": False,
                "story_card_duration": float(story_card_duration),
                "story_card_bg": story_card_bg or "",
            }
            output_path = run_make_multi_story_video(
                cfg, json_paths, authors, ui_log, lambda value: None)
            if not output_path or not os.path.exists(output_path):
                raise RuntimeError("Video rendering finished without a persistent output file.")
            result["path"] = output_path
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


def _gradio_generate_story(title, premise, genre, duration_minutes,
                           segment_count, language, output_path):
    """Stream story generation logs and return JSON preview + saved path."""
    messages = []
    updates = queue.Queue()
    finished = threading.Event()
    result = {"path": None, "preview": ""}

    def ui_log(message):
        updates.put(str(message))

    def work():
        try:
            if not title or not title.strip():
                raise ValueError("Please enter a story title.")
            out = output_path.strip() or "generated_story.json"
            data = generate_story_json(
                title=title.strip(),
                premise=(premise or "").strip(),
                genre=genre,
                duration_minutes=float(duration_minutes),
                segment_count=int(segment_count),
                language=language,
                log=ui_log,
            )
            if data:
                saved = save_story_json(data, out, ui_log)
                result["path"] = saved
                result["preview"] = json.dumps(data, indent=2, ensure_ascii=False)
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
        yield "\n".join(messages), result["preview"], result["path"]
        time.sleep(0.25)
    yield "\n".join(messages), result["preview"], result["path"]


def _export_srt(voice_out, json_path):
    """Export .srt subtitle file from the voice timeline."""
    voice_path = (voice_out or "voice_final.mp3").strip()
    timeline_path = voice_path + ".timeline.json"
    if not os.path.exists(timeline_path):
        return f"❌ Timeline not found: {timeline_path}\nGenerate voice first.", None
    try:
        story_path = json_path[0] if isinstance(json_path, (list, tuple)) and json_path else json_path
        if story_path and os.path.exists(story_path):
            with open(story_path, encoding="utf-8") as f:
                data = json.load(f)
            segments = _flatten_segments(data)
        else:
            segments = []
        srt_path = os.path.splitext(voice_path)[0] + ".srt"
        result = export_srt(timeline_path, segments, srt_path)
        if result:
            return f"✅ SRT exported: {result}", result
        return "❌ SRT export failed — timeline may be empty.", None
    except Exception:
        return "❌ ERROR:\n" + traceback.format_exc(), None


def _generate_chapters(voice_out, json_path):
    """Generate YouTube chapter markers from voice timeline."""
    voice_path = (voice_out or "voice_final.mp3").strip()
    timeline_path = voice_path + ".timeline.json"
    if not os.path.exists(timeline_path):
        return "❌ Timeline not found. Generate voice first.", ""
    try:
        story_path = json_path[0] if isinstance(json_path, (list, tuple)) and json_path else json_path
        if story_path and os.path.exists(story_path):
            with open(story_path, encoding="utf-8") as f:
                data = json.load(f)
            segments = _flatten_segments(data)
        else:
            segments = []
        chapters = generate_youtube_chapters(segments, timeline_path)
        if chapters:
            return "✅ Chapters generated — copy into your YouTube description:", chapters
        return "❌ No timing data found.", ""
    except Exception:
        return "❌ ERROR:\n" + traceback.format_exc(), ""


def _save_preset(preset_path, *values):
    """Save current Studio settings to a JSON preset file."""
    keys = [
        "voice_preset", "voice_style", "cfg_value", "do_normalize", "denoise",
        "auto_emotion", "speaker_lock", "max_workers", "bg_percent", "auto_amb",
        "bg_sound_query", "resolution", "fps", "crf", "transition_duration",
        "effect_style", "enable_subtitles", "subtitle_size", "subtitle_position",
        "make_thumbnail", "use_ai_images", "show_title", "use_logo", "logo_corner",
        "channel", "channel_corner",
    ]
    preset_path = (preset_path or "studio_preset.json").strip()
    data = dict(zip(keys, values))
    try:
        with open(preset_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return f"✅ Preset saved: {preset_path}"
    except Exception as exc:
        return f"❌ Save failed: {exc}"


def _load_preset(preset_path):
    """Load Studio settings from a JSON preset file. Returns list of values in key order."""
    import gradio as gr
    preset_path = (preset_path or "studio_preset.json").strip()
    if not os.path.exists(preset_path):
        return [gr.update()] * 26 + [f"❌ File not found: {preset_path}"]
    try:
        with open(preset_path, encoding="utf-8") as f:
            data = json.load(f)
        keys = [
            "voice_preset", "voice_style", "cfg_value", "do_normalize", "denoise",
            "auto_emotion", "speaker_lock", "max_workers", "bg_percent", "auto_amb",
            "bg_sound_query", "resolution", "fps", "crf", "transition_duration",
            "effect_style", "enable_subtitles", "subtitle_size", "subtitle_position",
            "make_thumbnail", "use_ai_images", "show_title", "use_logo", "logo_corner",
            "channel", "channel_corner",
        ]
        updates = [gr.update(value=data[k]) if k in data else gr.update() for k in keys]
        return updates + [f"✅ Loaded preset: {preset_path}"]
    except Exception as exc:
        return [gr.update()] * 26 + [f"❌ Load failed: {exc}"]


def _preview_segment(json_path, segment_index, voice_preset, voice_style, voice_ref,
                     cfg_value, do_normalize, denoise, speaker_lock):
    """Generate voice for a single segment and return it for preview."""
    messages = []
    updates = queue.Queue()
    finished = threading.Event()
    result = {"path": None}

    def ui_log(m):
        updates.put(str(m))

    def work():
        try:
            story_path = json_path[0] if isinstance(json_path, (list, tuple)) and json_path else json_path
            if not story_path or not os.path.exists(story_path):
                raise ValueError("Load a Story JSON first.")
            with open(story_path, encoding="utf-8") as f:
                data = json.load(f)
            segments = _flatten_segments(data)
            if not segments:
                raise ValueError("No segments found.")
            idx = max(0, min(int(segment_index or 0), len(segments) - 1))
            seg = segments[idx]
            ui_log(f"Previewing segment {idx + 1}: \"{(seg.get('target_text') or '')[:60]}...\"")
            import tempfile
            from .voice import generate_voice
            tmp = tempfile.mkdtemp(prefix="preview_")
            voice_cfg = {
                "voice_preset": voice_preset or "Balanced Neutral",
                "voice_style": voice_style or "Balanced",
                "cfg_value": float(cfg_value or 1.7),
                "do_normalize": bool(do_normalize),
                "denoise": bool(denoise),
                "auto_emotion": False,
                "speaker_lock": bool(speaker_lock),
            }
            generate_voice([seg], voice_ref or "", tmp, ui_log, voice_cfg, max_workers=1)
            # Find the generated file
            import glob
            clips = glob.glob(os.path.join(tmp, "*.mp3")) + glob.glob(os.path.join(tmp, "*.wav"))
            if clips:
                result["path"] = clips[0]
                ui_log(f"✅ Preview ready.")
            else:
                ui_log("❌ No audio generated.")
        except Exception:
            ui_log("❌ ERROR:\n" + traceback.format_exc())
        finally:
            finished.set()

    threading.Thread(target=work, daemon=True).start()
    collected = []
    while not finished.is_set() or not updates.empty():
        try:
            while True:
                collected.append(updates.get_nowait())
        except queue.Empty:
            pass
        yield "\n".join(collected), result["path"]
        time.sleep(0.3)
    yield "\n".join(collected), result["path"]


def _queue_scan_folder(folder, queue_state):
    """Scan folder for story JSONs and add them to the queue state."""
    import gradio as gr
    folder = (folder or ".").strip()
    if not os.path.isdir(folder):
        return queue_state, _queue_table_rows(queue_state), "❌ Folder not found."
    added = 0
    existing_paths = {j["json_path"] for j in queue_state}
    for root, _dirs, files in os.walk(folder):
        for fname in sorted(files):
            if not fname.lower().endswith(".json"):
                continue
            fpath = os.path.join(root, fname)
            if fpath in existing_paths:
                continue
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                if "segments" not in data and "stories" not in data:
                    continue
                queue_state.append({
                    "json_path": fpath,
                    "effect_style": "Horror Cinematic",
                    "privacy": "private",
                    "auto_upload": False,
                    "status": "⏳ Queued",
                })
                added += 1
            except Exception:
                pass
    rows = _queue_table_rows(queue_state)
    return queue_state, rows, f"✅ Added {added} story file(s). Queue: {len(queue_state)} total."


def _queue_table_rows(queue_state):
    """Convert queue state to gr.Dataframe rows."""
    return [
        [os.path.basename(j["json_path"]), j["effect_style"],
         j["privacy"], "Yes" if j["auto_upload"] else "No", j["status"]]
        for j in queue_state
    ]


def _queue_clear(queue_state):
    """Clear all jobs from the queue."""
    queue_state.clear()
    return queue_state, [], "Queue cleared."


def _queue_run_jobs(queue_state, base_effect, base_resolution, base_fps, base_crf,
                    base_voice_preset, base_auto_upload, queue_secrets, queue_token,
                    queue_stop_state):
    """Streaming generator: run all queued jobs sequentially."""
    from .batch_queue import run_batch, STATUS_QUEUED

    if not queue_state:
        yield "❌ Queue is empty.", _queue_table_rows(queue_state), queue_stop_state
        return

    messages = []
    updates = queue.Queue()
    stop_event = threading.Event()
    queue_stop_state = stop_event  # store so stop button can set it

    base_cfg = {
        "voice_source": "generate",
        "voice_preset": base_voice_preset or "Balanced Neutral",
        "voice_style": "Balanced",
        "voice_ref": "", "voice_file": "",
        "cfg_value": 1.7, "do_normalize": False,
        "denoise": True, "auto_emotion": False,
        "speaker_lock": True, "max_workers": 2,
        "bg_music": "", "bg_sound_query": "",
        "bg_percent": 0.18, "auto_amb": False,
        "resolution": base_resolution or "1280x720",
        "fps": int(base_fps or 20),
        "crf": int(base_crf or 18),
        "transition_duration": 1.5,
        "effect_style": base_effect or "Horror Cinematic",
        "enable_subtitles": False,
        "subtitle_size": 28,
        "subtitle_position": "bottom",
        "make_thumbnail": True,
        "use_ai_images": False,
        "preview": False,
        "show_title": False,
        "channel": "", "logo": "", "use_logo": False,
        "story_card_duration": 5.0, "story_card_bg": "",
        "video_only": False,
    }

    # Apply auto_upload and per-job overrides
    for job in queue_state:
        if job["status"] == "⏳ Queued":
            job["auto_upload"] = bool(base_auto_upload)
            if base_effect:
                job["effect_style"] = base_effect

    def work():
        run_batch(
            jobs=queue_state,
            base_cfg=base_cfg,
            client_secrets_path=queue_secrets or "",
            token_path=queue_token or "youtube_token.json",
            log_queue=updates,
            stop_event=stop_event,
        )
        updates.put(None)  # sentinel

    threading.Thread(target=work, daemon=True).start()

    while True:
        try:
            while True:
                item = updates.get_nowait()
                if item is None:
                    yield "\n".join(messages), _queue_table_rows(queue_state), stop_event
                    return
                messages.append(item)
        except queue.Empty:
            pass
        yield "\n".join(messages), _queue_table_rows(queue_state), stop_event
        time.sleep(0.3)


def _queue_stop(stop_state):
    """Signal the running batch to stop after current job."""
    if stop_state and hasattr(stop_state, "set"):
        stop_state.set()
        return "⏹ Stop requested — current job will finish, then queue halts."
    return "⚠️ No active queue to stop."


def _hist_scan(folder):
    """Scan a folder recursively for story JSON files and return dropdown choices."""
    import gradio as gr
    folder = (folder or ".").strip()
    if not os.path.isdir(folder):
        return gr.update(choices=[], value=None), "❌ Folder not found."
    choices = []
    for root, _dirs, files in os.walk(folder):
        for fname in sorted(files):
            if not fname.lower().endswith(".json"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                if "segments" not in data and "stories" not in data:
                    continue
                title = data.get("title") or fname
                label = f"{title}  [{fname}]"
                choices.append((label, fpath))
            except Exception:
                pass
    return gr.update(choices=choices, value=None), f"✅ Found {len(choices)} story file(s)."


def _hist_preview(fpath):
    """Load a story JSON and return metadata summary, JSON preview, and the path."""
    if not fpath or not os.path.exists(fpath):
        return "", "", ""
    try:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        segs = list(data.get("segments") or [])
        for story in data.get("stories") or []:
            segs.extend(story.get("segments") or [])
        title = data.get("title", "—")
        lang = data.get("language", "—")
        # Estimate duration from last segment end time
        max_end = 0.0
        for seg in segs:
            dur = str(seg.get("duration") or "")
            if "-" in dur:
                try:
                    end = dur.split("-")[-1].strip()
                    parts = end.split(":")
                    if len(parts) == 2:
                        max_end = max(max_end, int(parts[0]) + int(parts[1]) / 60)
                except Exception:
                    pass
        dur_str = f"{max_end:.1f} min" if max_end > 0 else "—"
        meta = (f"📄 {os.path.basename(fpath)}\n"
                f"🎬 {title}\n"
                f"📝 {len(segs)} segment(s) · {lang} · {dur_str}")
        preview = json.dumps(data, indent=2, ensure_ascii=False)
        return meta, preview, fpath
    except Exception as e:
        return f"❌ {e}", "", ""


def _hist_delete_file(fpath):
    """Delete the selected story JSON file."""
    if not fpath or not os.path.exists(fpath):
        return "❌ No file selected or file not found."
    try:
        os.remove(fpath)
        return f"✅ Deleted: {os.path.basename(fpath)}"
    except Exception as e:
        return f"❌ Delete failed: {e}"


def _yt_authorize(client_secrets_path, token_path):
    """Streaming generator: start device-code flow and poll until authorized."""
    import gradio as gr
    from .uploader import load_client_secrets, start_device_flow, poll_device_token, save_tokens

    messages = []

    def log(m):
        messages.append(str(m))

    if not client_secrets_path or not os.path.exists(client_secrets_path):
        yield "❌ client_secrets.json not found. Download it from Google Cloud Console."
        return

    token_path = (token_path or "youtube_token.json").strip()

    try:
        secrets = load_client_secrets(client_secrets_path)
        log("🔐 Starting YouTube authorization (device flow)...")
        flow = start_device_flow(secrets["client_id"])
        url = flow.get("verification_url", "https://google.com/device")
        code = flow.get("user_code", "")
        log(f"\n👉 Visit:  {url}")
        log(f"   Enter:  {code}\n")
        log("Waiting for you to authorize in the browser (up to 5 minutes)...")
        yield "\n".join(messages)

        interval = int(flow.get("interval", 5))
        device_code = flow["device_code"]
        deadline = time.time() + 300
        token = None
        while time.time() < deadline:
            time.sleep(interval)
            try:
                import urllib.error
                import urllib.parse
                import urllib.request
                data = {}
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
                    save_tokens(token_path, data)
                    log(f"\n✅ Authorized! Token saved to: {token_path}")
                    token = data
                    break
                if data.get("error") == "slow_down":
                    interval += 5
                elif data.get("error") not in ("authorization_pending", None):
                    log(f"❌ OAuth error: {data.get('error')}")
                    break
                else:
                    log("  Still waiting...")
            except Exception as exc:
                log(f"  Poll error: {exc}")
            yield "\n".join(messages)

        if not token:
            log("❌ Authorization timed out or failed.")
    except Exception:
        log("❌ ERROR:\n" + traceback.format_exc())

    yield "\n".join(messages)


def _yt_upload(video_path, title, description, tags, privacy,
               client_secrets_path, token_path):
    """Streaming generator: upload a video to YouTube."""
    from .uploader import upload_to_youtube

    messages = []
    updates = queue.Queue()
    finished = threading.Event()
    result = {"video_id": None}

    def ui_log(m):
        updates.put(str(m))

    def work():
        try:
            vp = (video_path or "").strip()
            if not vp or not os.path.exists(vp):
                raise ValueError("Video file not found. Render a video first.")
            if not client_secrets_path or not os.path.exists(client_secrets_path):
                raise ValueError("client_secrets.json not found.")
            tok = (token_path or "youtube_token.json").strip()
            result["video_id"] = upload_to_youtube(
                video_path=vp,
                title=title or os.path.basename(vp),
                description=description or "",
                tags=tags or "",
                privacy=privacy or "private",
                client_secrets_path=client_secrets_path,
                token_path=tok,
                log=ui_log,
            )
        except Exception:
            ui_log("❌ ERROR:\n" + traceback.format_exc())
        finally:
            finished.set()

    threading.Thread(target=work, daemon=True).start()
    collected = []
    while not finished.is_set() or not updates.empty():
        try:
            while True:
                collected.append(updates.get_nowait())
        except queue.Empty:
            pass
        yield "\n".join(collected), result["video_id"] or ""
        time.sleep(0.3)
    yield "\n".join(collected), result["video_id"] or ""


def _eta_estimate(text_input, json_path, wpm, cpm):
    """Estimate TTS reading time for pasted text or a loaded story JSON."""
    wpm = float(wpm or 130)
    cpm = float(cpm or 280)
    segments_data = []

    story_path = json_path[0] if isinstance(json_path, (list, tuple)) and json_path else json_path
    if story_path and os.path.exists(story_path):
        try:
            with open(story_path, encoding="utf-8") as f:
                data = json.load(f)
            for seg in _flatten_segments(data):
                segments_data.append({
                    "id": seg.get("segment_id", "?"),
                    "title": seg.get("title", ""),
                    "text": seg.get("target_text", ""),
                })
        except Exception as e:
            return f"❌ Failed to load JSON: {e}", ""

    if not segments_data and text_input and text_input.strip():
        import re as _re
        blocks = [b.strip() for b in _re.split(r"\n{2,}", text_input.strip()) if b.strip()]
        for i, block in enumerate(blocks, 1):
            segments_data.append({"id": i, "title": f"Block {i}", "text": block})

    if not segments_data:
        return "Paste text or load a JSON to estimate duration.", ""

    def _estimate_seconds(text):
        non_latin = sum(1 for c in text if ord(c) > 0x1000)
        if non_latin > len(text) * 0.3:
            return (len(text) / cpm) * 60
        return (len(text.split()) / wpm) * 60

    lines, total_s = [], 0.0
    for seg in segments_data:
        s = _estimate_seconds(seg["text"])
        total_s += s
        words = len(seg["text"].split())
        chars = len(seg["text"])
        lines.append(
            f"Seg {str(seg['id']):>3}  {seg['title'][:28]:<28}  "
            f"{words:>5}w / {chars:>6}c  →  "
            f"{int(s // 60)}:{int(s % 60):02d}"
        )

    breakdown = "\n".join(lines)
    total_str = f"Total estimated: {int(total_s // 60)} min {int(total_s % 60)} sec  ({total_s:.0f}s)"
    return breakdown, total_str


def _gradio_convert_text_to_json(plain_text, genre, language, segment_count, output_path):
    """Stream plain-text → story JSON conversion to Gradio."""
    from .story_generator import convert_text_to_story_json, save_story_json
    messages, updates = [], queue.Queue()
    finished = threading.Event()
    result = {"path": None, "preview": ""}

    def ui_log(m):
        updates.put(str(m))

    def work():
        try:
            out = (output_path or "converted_story.json").strip()
            data = convert_text_to_story_json(
                plain_text=plain_text,
                genre=genre,
                language=language,
                segment_count=int(segment_count),
                output_path=out,
                log=ui_log,
            )
            if data:
                saved = save_story_json(data, out, ui_log)
                result["path"] = saved
                result["preview"] = json.dumps(data, indent=2, ensure_ascii=False)
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
        yield "\n".join(messages), result["preview"], result["path"]
        time.sleep(0.25)
    yield "\n".join(messages), result["preview"], result["path"]


def build_gradio_ui():
    """Automation-Studio-style web UI for voice and video generation."""
    import gradio as gr

    css = """
    #run-log textarea  { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    #gen-log textarea  { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    #yt-log textarea   { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    #queue-log textarea { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    #eta-log textarea  { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    #txt2json-log textarea { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    .menu-card button {
        min-height: 110px; white-space: pre-wrap; line-height: 1.5;
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155 !important; border-radius: 12px !important;
        color: #e2e8f0 !important; font-size: 14px; font-weight: 500;
        transition: border-color .2s, transform .15s, box-shadow .2s;
    }
    .menu-card button:hover {
        border-color: #3b82f6 !important; transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(59,130,246,.25) !important;
    }
    .back-row { margin-bottom: 16px; }
    """

    ALL_PANELS = []

    def _nav_to(target_col):
        return [gr.update(visible=(col is target_col)) for col in ALL_PANELS]

    with gr.Blocks(title="Automation Studio") as demo:

        # ── HOME ──────────────────────────────────────────────────────────
        with gr.Column(visible=True) as home_col:
            gr.Markdown("# 🎙 Mr.Midnight — Automation Studio")
            gr.Markdown("Choose a tool to get started:")
            with gr.Row():
                btn_story   = gr.Button("✍️\nGenerate Story\nAI creates full story JSON",    elem_classes="menu-card")
                btn_voice   = gr.Button("🎙\nGenerate Voice\nTTS + narration pipeline",        elem_classes="menu-card")
                btn_video   = gr.Button("🎬\nMake Video\nVoice + cinematic video renderer",    elem_classes="menu-card")
                btn_eta     = gr.Button("⏱\nETA Duration\nEstimate script reading time",      elem_classes="menu-card")
            with gr.Row():
                btn_txt2j   = gr.Button("📝\nText → JSON\nConvert plain text to story JSON",  elem_classes="menu-card")
                btn_history = gr.Button("📂\nHistory\nBrowse & manage saved story files",      elem_classes="menu-card")
                btn_youtube = gr.Button("📺\nYouTube Upload\nOAuth + direct video upload",     elem_classes="menu-card")
                btn_queue   = gr.Button("🚀\nBatch Queue\nOvernight multi-story rendering",    elem_classes="menu-card")

        # ── GENERATE STORY ────────────────────────────────────────────────
        with gr.Column(visible=False) as story_col:
            with gr.Row(elem_classes="back-row"):
                story_back_btn = gr.Button("← Back to Menu", size="sm")
            gr.Markdown("## ✍️ Generate Story")
            gr.Markdown("Generate a complete Story JSON from a title and premise using Claude AI.")
            with gr.Row():
                with gr.Column(scale=3):
                    gen_title = gr.Textbox(
                        label="Story Title",
                        placeholder="e.g. The House on the Hill")
                    gen_premise = gr.Textbox(
                        label="Premise / Idea",
                        placeholder="e.g. A family moves into an old house and discovers it has a dark history...",
                        lines=4)
                    with gr.Row():
                        gen_genre = gr.Dropdown(
                            list(_GENRES.keys()), value="Horror", label="Genre")
                        gen_language = gr.Dropdown(
                            ["English", "Khmer", "French", "Spanish", "Japanese"],
                            value="English", label="Language")
                    with gr.Row():
                        gen_duration = gr.Slider(
                            1, 10, value=3, step=0.5, label="Duration (minutes)")
                        gen_segments = gr.Slider(
                            3, 12, value=5, step=1, label="Number of segments")
                    gen_output_path = gr.Textbox(
                        value="generated_story.json",
                        label="Save JSON to",
                        placeholder="generated_story.json")
                    gen_btn = gr.Button("✨ Generate Story JSON", variant="primary")
                with gr.Column(scale=4):
                    gen_log = gr.Textbox(
                        label="Live log", lines=8, interactive=False, elem_id="gen-log")
                    gen_preview = gr.Code(
                        label="Generated JSON preview",
                        language="json",
                        lines=20,
                        interactive=False)
                    gen_saved = gr.Textbox(
                        label="Saved file path", interactive=False)

            gen_btn.click(
                _gradio_generate_story,
                inputs=[gen_title, gen_premise, gen_genre, gen_duration,
                        gen_segments, gen_language, gen_output_path],
                outputs=[gen_log, gen_preview, gen_saved])

        # ── STUDIO (voice + video) ────────────────────────────────────────
        with gr.Column(visible=False) as studio_col:
            with gr.Row(elem_classes="back-row"):
                studio_back_btn = gr.Button("← Back to Menu", size="sm")
            gr.Markdown("## 🎬 Voice & Video Studio")
            with gr.Row():

                with gr.Column(scale=1, min_width=220):
                    gr.Markdown("#### 📁 Project")
                    debug_story = (
                        [DEBUG_STORY_JSON]
                        if APP_DEBUG and DEBUG_STORY_JSON and os.path.isfile(DEBUG_STORY_JSON)
                        else None
                    )
                    story_json = gr.File(
                        value=debug_story,
                        label="Story JSON (1, 2, 3 order)",
                        file_types=[".json"],
                        type="filepath",
                        file_count="multiple",
                    )
                    story_authors = gr.Textbox(
                        value="Anonymous",
                        label="Authors (comma-separated)",
                        placeholder="Anonymous, Ranger P.")
                    voice_source = gr.Radio(
                        ["generate", "existing"], value="generate", label="Voice source")

                    gr.Markdown("#### 📤 Output")
                    voice_out = gr.Textbox(value="voice_final.mp3", label="Voice output")
                    segments_output = gr.Textbox(value="segments_audio", label="Segments folder")
                    video_out = gr.Textbox(value="", label="Video output (.mp4)")

                    gr.Markdown("#### 🎴 Story Cards")
                    story_card_duration = gr.Slider(
                        3, 5, value=DEFAULT_STORY_CARD_DURATION, step=0.5,
                        label="Card duration (s)")
                    story_card_bg = gr.Textbox(
                        value=STORY_CARD_BG, label="Card background sound")

                    gr.Markdown("#### ▶ Actions")
                    run_btn = gr.Button("▶ Generate Voice", size="sm")
                    video_btn = gr.Button("🎬 Make Video", variant="primary", size="sm")

                with gr.Column(scale=4):
                    with gr.Tabs():

                        with gr.Tab("🎙 Voice"):
                            with gr.Row():
                                voice_preset = gr.Dropdown(
                                    list(VOICE_PRESETS), value="Balanced Neutral", label="Preset")
                                voice_style = gr.Dropdown(
                                    list(VOICE_STYLES), value="Balanced", label="Style")
                            voice_ref = gr.File(
                                value=DEFAULT_VOICE_REF,
                                label="Reference voice (optional — for cloning)",
                                file_types=["audio"], type="filepath")
                            voice_file = gr.File(
                                label="Existing voice file (when source = existing)",
                                file_types=["audio"], type="filepath")

                        with gr.Tab("⚙️ Advanced"):
                            with gr.Row():
                                cfg_value = gr.Slider(
                                    1.0, 3.0, value=1.7, step=0.1,
                                    label="CFG guidance (1.6–1.8 for Khmer)")
                                max_workers = gr.Slider(
                                    1, 2, value=2, step=1, label="Parallel workers")
                            with gr.Row():
                                do_normalize = gr.Checkbox(value=False, label="Text normalization")
                                denoise = gr.Checkbox(value=True, label="Reference denoising")
                            auto_emotion = gr.Checkbox(
                                value=False, label="Different feeling for every segment",
                                info="Uses emotion/feeling/mood from JSON, or detects from English text.")
                            speaker_lock = gr.Checkbox(
                                value=True, label="Lock one narrator voice for all segments",
                                info="Creates one anchor voice, then clones it to prevent gender/age changes.")

                        with gr.Tab("🎵 Audio"):
                            bg_music = gr.File(
                                label="Music file (optional — overrides stock query)",
                                file_types=["audio"], type="filepath")
                            bg_sound_query = gr.Textbox(
                                value="",
                                label="Stock music query (leave blank to skip)",
                                placeholder="e.g. dark ambient horror, suspense, eerie wind",
                                info="Downloads free music from Pixabay (PIXABAY_KEY) or ccMixter. Ignored when a file is uploaded.")
                            with gr.Row():
                                bg_percent = gr.Slider(
                                    0.0, 0.5, value=0.18, step=0.01, label="Music level")
                                auto_amb = gr.Checkbox(
                                    value=False, label="Generate dark ambience if no music")

                        with gr.Tab("🎬 Video"):
                            with gr.Row():
                                resolution = gr.Dropdown(
                                    ["1920x1080", "1280x720"], value="1280x720", label="Resolution")
                                fps = gr.Slider(12, 30, value=20, step=1, label="FPS")
                                crf = gr.Slider(18, 28, value=18, step=1, label="Quality CRF")
                            transition_duration = gr.Slider(
                                0.3, 3.0, value=1.5, step=0.1,
                                label="Transition speed (s — higher = slower)")
                            effect_style = gr.Dropdown(
                                ["Horror Cinematic", "Blood Red",
                                 "Black & White Dread", "Natural Dark"],
                                value="Horror Cinematic", label="Horror visual effect")
                            make_thumbnail = gr.Checkbox(
                                value=True, label="Generate thumbnail beside video",
                                info="Saves a cinematic thumbnail JPG with title text.")
                            use_ai_images = gr.Checkbox(
                                value=False, label="Generate AI images with DALL-E 3",
                                info="Requires OPENAI_KEY in .env. Generates a unique cinematic image per segment instead of downloading from Pexels. Falls back to Pexels for any failures.")

                        with gr.Tab("💬 Subtitles"):
                            enable_subtitles = gr.Checkbox(
                                value=False, label="Burn captions into video",
                                info="Uses narration timing from voice timeline. Adds one re-encode pass.")
                            with gr.Row():
                                subtitle_size = gr.Slider(
                                    14, 48, value=28, step=2, label="Font size (px)")
                                subtitle_position = gr.Dropdown(
                                    ["bottom", "top", "center"],
                                    value="bottom", label="Position")

                        with gr.Tab("🎨 Branding"):
                            show_title = gr.Checkbox(
                                value=False, label="Show story title card (first 5 seconds)",
                                info="Burns the story title at the top of the video for 5 seconds.")
                            gr.Markdown("**Channel watermark**")
                            with gr.Row():
                                channel = gr.Textbox(
                                    value="", label="Channel name",
                                    placeholder="e.g. Mr.Midnight")
                                channel_corner = gr.Dropdown(
                                    ["top-right", "top-left", "bottom-right", "bottom-left"],
                                    value="top-right", label="Channel corner")
                            gr.Markdown("**Logo overlay**")
                            with gr.Row():
                                use_logo = gr.Checkbox(value=False, label="Overlay logo image")
                                logo_corner = gr.Dropdown(
                                    ["bottom-right", "bottom-left", "top-right", "top-left"],
                                    value="bottom-right", label="Logo corner")
                            logo = gr.File(
                                label="Logo image (PNG with transparency recommended)",
                                file_types=["image"], type="filepath")

                        with gr.Tab("🛠 Tools"):
                            gr.Markdown("**Export SRT subtitles** from the last generated voice timeline")
                            with gr.Row():
                                srt_export_btn = gr.Button("📝 Export SRT", size="sm")
                            srt_status = gr.Textbox(label="Status", interactive=False, lines=1)
                            srt_file = gr.File(label="Download .srt file", interactive=False)

                            gr.Markdown("---\n**YouTube Chapter Markers** from voice timeline")
                            chapter_btn = gr.Button("📋 Generate Chapters", size="sm")
                            chapter_status = gr.Textbox(label="Status", interactive=False, lines=1)
                            chapter_text = gr.Textbox(
                                label="Chapter markers (copy → paste into YouTube description)",
                                lines=10, interactive=True)

                            gr.Markdown("---\n**Voice Segment Preview** — test one segment quickly")
                            with gr.Row():
                                preview_seg_idx = gr.Number(
                                    value=0, label="Segment index (0 = first)", precision=0)
                                preview_seg_btn = gr.Button("▶ Preview Segment", size="sm")
                            preview_seg_log = gr.Textbox(
                                label="Preview log", lines=4, interactive=False)
                            preview_seg_audio = gr.Audio(
                                label="Segment preview", type="filepath", interactive=False)

                            gr.Markdown("---\n**Settings Presets** — save/load Studio config")
                            with gr.Row():
                                preset_path = gr.Textbox(
                                    value="studio_preset.json", label="Preset file",
                                    placeholder="studio_preset.json", scale=4)
                                preset_save_btn = gr.Button("💾 Save", size="sm", scale=1)
                                preset_load_btn = gr.Button("📂 Load", size="sm", scale=1)
                            preset_status = gr.Textbox(label="Status", interactive=False, lines=1)

                    gr.Markdown("---")
                    with gr.Row():
                        run_log = gr.Textbox(
                            label="Live log", lines=16, interactive=False,
                            elem_id="run-log", scale=4)
                        with gr.Column(scale=3):
                            output_audio = gr.Audio(
                                label="Final voice", type="filepath", interactive=False)
                            output_video = gr.Video(
                                label="Final video", interactive=False)

            studio_inputs = [story_json, voice_source, voice_preset, voice_style, voice_ref,
                             voice_file, cfg_value, do_normalize, denoise, auto_emotion,
                             speaker_lock, max_workers,
                             bg_music, bg_sound_query, bg_percent, auto_amb,
                             voice_out, segments_output]
            run_btn.click(_gradio_run_voice, inputs=studio_inputs, outputs=[run_log, output_audio])
            video_inputs = studio_inputs + [story_authors, story_card_duration, story_card_bg,
                                            video_out,
                                            resolution, fps, crf, transition_duration, effect_style,
                                            enable_subtitles, subtitle_size, subtitle_position,
                                            make_thumbnail, use_ai_images,
                                            show_title, logo, use_logo, logo_corner,
                                            channel, channel_corner]
            video_btn.click(_gradio_run_video, inputs=video_inputs, outputs=[run_log, output_video])

            srt_export_btn.click(
                _export_srt,
                inputs=[voice_out, story_json],
                outputs=[srt_status, srt_file])
            chapter_btn.click(
                _generate_chapters,
                inputs=[voice_out, story_json],
                outputs=[chapter_status, chapter_text])
            preview_seg_btn.click(
                _preview_segment,
                inputs=[story_json, preview_seg_idx, voice_preset, voice_style,
                        voice_ref, cfg_value, do_normalize, denoise, speaker_lock],
                outputs=[preview_seg_log, preview_seg_audio])

            preset_save_inputs = [
                preset_path,
                voice_preset, voice_style, cfg_value, do_normalize, denoise,
                auto_emotion, speaker_lock, max_workers, bg_percent, auto_amb,
                bg_sound_query, resolution, fps, crf, transition_duration,
                effect_style, enable_subtitles, subtitle_size, subtitle_position,
                make_thumbnail, use_ai_images, show_title, use_logo, logo_corner,
                channel, channel_corner,
            ]
            preset_save_btn.click(
                _save_preset,
                inputs=preset_save_inputs,
                outputs=[preset_status])
            preset_load_outputs = [
                voice_preset, voice_style, cfg_value, do_normalize, denoise,
                auto_emotion, speaker_lock, max_workers, bg_percent, auto_amb,
                bg_sound_query, resolution, fps, crf, transition_duration,
                effect_style, enable_subtitles, subtitle_size, subtitle_position,
                make_thumbnail, use_ai_images, show_title, use_logo, logo_corner,
                channel, channel_corner,
                preset_status,
            ]
            preset_load_btn.click(
                _load_preset,
                inputs=[preset_path],
                outputs=preset_load_outputs)

        # ── ETA DURATION ──────────────────────────────────────────────────
        with gr.Column(visible=False) as eta_col:
            with gr.Row(elem_classes="back-row"):
                eta_back_btn = gr.Button("← Back to Menu", size="sm")
            gr.Markdown("## ⏱ ETA Script Duration Estimator")
            gr.Markdown("Estimate how long a script will take to narrate at TTS speaking pace.")
            with gr.Row():
                with gr.Column(scale=2):
                    eta_text = gr.Textbox(
                        label="Paste plain text (or leave blank and load JSON below)",
                        lines=12,
                        placeholder="Paste your script here...")
                    eta_json = gr.File(
                        label="Or load Story JSON",
                        file_types=[".json"], type="filepath")
                    with gr.Row():
                        eta_wpm = gr.Slider(80, 200, value=130, step=5,
                                            label="Words/min (Latin scripts)")
                        eta_cpm = gr.Slider(150, 500, value=280, step=10,
                                            label="Chars/min (Khmer/CJK)")
                    eta_btn = gr.Button("⏱ Estimate Duration", variant="primary")
                with gr.Column(scale=3):
                    eta_breakdown = gr.Textbox(
                        label="Per-segment breakdown",
                        lines=20, interactive=False,
                        elem_id="eta-log")
                    eta_total = gr.Textbox(
                        label="Total estimated duration",
                        interactive=False)

            eta_btn.click(
                _eta_estimate,
                inputs=[eta_text, eta_json, eta_wpm, eta_cpm],
                outputs=[eta_breakdown, eta_total])

        # ── PLAIN TEXT → JSON ─────────────────────────────────────────────
        with gr.Column(visible=False) as txt2json_col:
            with gr.Row(elem_classes="back-row"):
                txt2j_back_btn = gr.Button("← Back to Menu", size="sm")
            gr.Markdown("## 📝 Convert Plain Text → Story JSON")
            gr.Markdown("Paste a written story and Claude will structure it into the segment JSON format without rewriting the content.")
            with gr.Row():
                with gr.Column(scale=2):
                    txt2j_text = gr.Textbox(
                        label="Plain text story",
                        lines=16,
                        placeholder="Paste your written story here...")
                    with gr.Row():
                        txt2j_genre = gr.Dropdown(
                            list(_GENRES.keys()), value="Horror", label="Genre")
                        txt2j_language = gr.Dropdown(
                            ["English", "Khmer", "French", "Spanish", "Japanese"],
                            value="English", label="Language")
                    txt2j_segments = gr.Slider(
                        3, 12, value=5, step=1, label="Target segment count")
                    txt2j_output = gr.Textbox(
                        value="converted_story.json",
                        label="Save JSON to")
                    txt2j_btn = gr.Button("📝 Convert to JSON", variant="primary")
                with gr.Column(scale=3):
                    txt2j_log = gr.Textbox(
                        label="Live log", lines=6, interactive=False,
                        elem_id="txt2json-log")
                    txt2j_preview = gr.Code(
                        label="Generated JSON", language="json",
                        lines=18, interactive=False)
                    txt2j_saved = gr.Textbox(
                        label="Saved file path", interactive=False)

            txt2j_btn.click(
                _gradio_convert_text_to_json,
                inputs=[txt2j_text, txt2j_genre, txt2j_language, txt2j_segments, txt2j_output],
                outputs=[txt2j_log, txt2j_preview, txt2j_saved])

        # ── HISTORY ───────────────────────────────────────────────────────
        with gr.Column(visible=False) as history_col:
            with gr.Row(elem_classes="back-row"):
                hist_back_btn = gr.Button("← Back to Menu", size="sm")
            gr.Markdown("## 📂 History & File Manager")
            gr.Markdown("Browse and manage saved Story JSON files.")
            with gr.Row():
                hist_folder = gr.Textbox(
                    value=".", label="Folder to scan",
                    placeholder="./stories", scale=5)
                hist_scan_btn = gr.Button("🔍 Scan", size="sm", scale=1)
            hist_status = gr.Textbox(label="Status", interactive=False, lines=1)
            hist_file_dd = gr.Dropdown(
                choices=[], label="Select Story JSON", interactive=True)
            hist_meta = gr.Textbox(
                label="Metadata", interactive=False, lines=3)
            hist_preview = gr.Code(
                label="JSON Preview", language="json",
                lines=15, interactive=False)
            hist_selected_state = gr.State(value="")
            with gr.Row():
                hist_send_btn = gr.Button(
                    "📤 Send to Studio", variant="primary", size="sm")
                hist_delete_btn = gr.Button(
                    "🗑 Delete", variant="stop", size="sm")

            hist_scan_btn.click(
                _hist_scan,
                inputs=[hist_folder],
                outputs=[hist_file_dd, hist_status])
            hist_file_dd.change(
                _hist_preview,
                inputs=[hist_file_dd],
                outputs=[hist_meta, hist_preview, hist_selected_state])
            hist_delete_btn.click(
                _hist_delete_file,
                inputs=[hist_selected_state],
                outputs=[hist_status]).then(
                _hist_scan,
                inputs=[hist_folder],
                outputs=[hist_file_dd, hist_status])

        # ── YOUTUBE ───────────────────────────────────────────────────────
        with gr.Column(visible=False) as youtube_col:
            with gr.Row(elem_classes="back-row"):
                yt_back_btn = gr.Button("← Back to Menu", size="sm")
            gr.Markdown(
                "## 📺 YouTube Upload\n"
                "Requires a **client_secrets.json** from Google Cloud Console "
                "(YouTube Data API v3, Desktop app OAuth).")
            with gr.Row():
                with gr.Column(scale=1):
                    yt_secrets = gr.File(
                        label="client_secrets.json",
                        file_types=[".json"], type="filepath")
                    yt_token = gr.Textbox(
                        value="youtube_token.json",
                        label="Token save path")
                    yt_auth_btn = gr.Button("🔐 Authorize YouTube", size="sm")
                    gr.Markdown("---")
                    yt_video = gr.Textbox(
                        label="Video file path",
                        placeholder="/path/to/output.mp4")
                    yt_title = gr.Textbox(label="Title", placeholder="My Horror Story")
                    yt_description = gr.Textbox(
                        label="Description", lines=4,
                        placeholder="Generated with Automation Studio...")
                    yt_tags = gr.Textbox(
                        label="Tags (comma-separated)",
                        placeholder="horror, narration, creepy")
                    yt_privacy = gr.Dropdown(
                        ["private", "unlisted", "public"],
                        value="private", label="Privacy")
                    yt_upload_btn = gr.Button(
                        "📤 Upload to YouTube", variant="primary", size="sm")
                with gr.Column(scale=2):
                    yt_log = gr.Textbox(
                        label="Log", lines=20, interactive=False,
                        elem_id="yt-log")
                    yt_video_id = gr.Textbox(
                        label="YouTube Video ID / URL", interactive=False)

            yt_auth_btn.click(
                _yt_authorize,
                inputs=[yt_secrets, yt_token],
                outputs=[yt_log])
            yt_upload_btn.click(
                _yt_upload,
                inputs=[yt_video, yt_title, yt_description, yt_tags,
                        yt_privacy, yt_secrets, yt_token],
                outputs=[yt_log, yt_video_id])

        # ── BATCH QUEUE ───────────────────────────────────────────────────
        with gr.Column(visible=False) as queue_col:
            with gr.Row(elem_classes="back-row"):
                queue_back_btn = gr.Button("← Back to Menu", size="sm")
            gr.Markdown(
                "## 🚀 Batch Queue\n"
                "Scan a folder to load stories, then click **▶ Run Queue** "
                "to render all of them sequentially while you sleep.")
            queue_state = gr.State([])
            queue_stop_state = gr.State(None)

            with gr.Row():
                queue_folder = gr.Textbox(
                    value=".", label="Folder to scan", scale=5,
                    placeholder="./stories")
                queue_scan_btn = gr.Button("🔍 Scan & Add", size="sm", scale=1)
                queue_clear_btn = gr.Button("🗑 Clear Queue", size="sm", scale=1)

            queue_status = gr.Textbox(label="Status", interactive=False, lines=1)
            queue_table = gr.Dataframe(
                headers=["File", "Effect Style", "Privacy", "Auto-Upload", "Status"],
                label="Job Queue",
                interactive=False,
                wrap=True)

            gr.Markdown("#### ⚙️ Queue Settings")
            with gr.Row():
                queue_effect = gr.Dropdown(
                    ["Horror Cinematic", "Blood Red",
                     "Black & White Dread", "Natural Dark"],
                    value="Horror Cinematic", label="Effect style (all jobs)")
                queue_resolution = gr.Dropdown(
                    ["1280x720", "1920x1080"], value="1280x720",
                    label="Resolution")
                queue_fps = gr.Slider(12, 30, value=20, step=1, label="FPS")
                queue_crf = gr.Slider(18, 28, value=18, step=1, label="Quality CRF")
            with gr.Row():
                queue_voice_preset = gr.Dropdown(
                    list(VOICE_PRESETS), value="Balanced Neutral",
                    label="Voice preset")
                queue_auto_upload = gr.Checkbox(
                    value=False, label="Auto-upload to YouTube after each render")
            with gr.Row():
                queue_secrets = gr.File(
                    label="client_secrets.json (for YouTube)",
                    file_types=[".json"], type="filepath")
                queue_token = gr.Textbox(
                    value="youtube_token.json",
                    label="YouTube token path")

            with gr.Row():
                queue_run_btn = gr.Button(
                    "▶ Run Queue", variant="primary", size="sm")
                queue_stop_btn = gr.Button(
                    "⏹ Stop after current job", size="sm")

            queue_log = gr.Textbox(
                label="Live log", lines=20, interactive=False,
                elem_id="queue-log")

            queue_scan_btn.click(
                _queue_scan_folder,
                inputs=[queue_folder, queue_state],
                outputs=[queue_state, queue_table, queue_status])
            queue_clear_btn.click(
                _queue_clear,
                inputs=[queue_state],
                outputs=[queue_state, queue_table, queue_status])
            queue_run_btn.click(
                _queue_run_jobs,
                inputs=[queue_state, queue_effect, queue_resolution,
                        queue_fps, queue_crf, queue_voice_preset,
                        queue_auto_upload, queue_secrets, queue_token,
                        queue_stop_state],
                outputs=[queue_log, queue_table, queue_stop_state])
            queue_stop_btn.click(
                _queue_stop,
                inputs=[queue_stop_state],
                outputs=[queue_status])

        # ── Navigation wiring ─────────────────────────────────────────────
        ALL_PANELS.extend([
            home_col, story_col, studio_col, eta_col, txt2json_col,
            history_col, youtube_col, queue_col,
        ])

        # Home → feature panels
        btn_story.click(   lambda: _nav_to(story_col),    outputs=ALL_PANELS)
        btn_voice.click(   lambda: _nav_to(studio_col),   outputs=ALL_PANELS)
        btn_video.click(   lambda: _nav_to(studio_col),   outputs=ALL_PANELS)
        btn_eta.click(     lambda: _nav_to(eta_col),      outputs=ALL_PANELS)
        btn_txt2j.click(   lambda: _nav_to(txt2json_col), outputs=ALL_PANELS)
        btn_history.click( lambda: _nav_to(history_col),  outputs=ALL_PANELS)
        btn_youtube.click( lambda: _nav_to(youtube_col),  outputs=ALL_PANELS)
        btn_queue.click(   lambda: _nav_to(queue_col),    outputs=ALL_PANELS)

        # Feature → Home (Back buttons)
        story_back_btn.click(  lambda: _nav_to(home_col), outputs=ALL_PANELS)
        studio_back_btn.click( lambda: _nav_to(home_col), outputs=ALL_PANELS)
        eta_back_btn.click(    lambda: _nav_to(home_col), outputs=ALL_PANELS)
        txt2j_back_btn.click(  lambda: _nav_to(home_col), outputs=ALL_PANELS)
        hist_back_btn.click(   lambda: _nav_to(home_col), outputs=ALL_PANELS)
        yt_back_btn.click(     lambda: _nav_to(home_col), outputs=ALL_PANELS)
        queue_back_btn.click(  lambda: _nav_to(home_col), outputs=ALL_PANELS)

        # History "Send to Studio" → load JSON and navigate to Studio
        hist_send_btn.click(
            lambda p: [p] if p else [],
            inputs=[hist_selected_state],
            outputs=[story_json],
        ).then(lambda: _nav_to(studio_col), outputs=ALL_PANELS)

    return demo, css


def main():
    """Build and launch the Gradio application."""
    demo, ui_css = build_gradio_ui()
    demo.launch(inbrowser=True, share=False, css=ui_css,
                theme=__import__("gradio").themes.Base(primary_hue="blue", neutral_hue="slate"))
