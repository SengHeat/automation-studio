"""Batch job queue for overnight rendering and auto YouTube upload.

Usage (from gradio_ui.py):
    stop = threading.Event()
    for log_line, table_rows in run_batch(jobs, base_cfg, secrets, token, log_fn, stop):
        yield log_line, table_rows
"""

import os
import threading

from .pipeline import run_make_video
from .uploader import upload_to_youtube

# Status labels
STATUS_QUEUED = "⏳ Queued"
STATUS_RUNNING = "▶ Running"
STATUS_DONE = "✅ Done"
STATUS_FAILED = "❌ Failed"
STATUS_SKIPPED = "⏩ Skipped"


def _job_rows(jobs):
    """Convert jobs list to a 2-D list for gr.Dataframe."""
    return [
        [os.path.basename(j["json_path"]), j["effect_style"],
         j["privacy"], j["status"]]
        for j in jobs
    ]


def run_batch(jobs, base_cfg, client_secrets_path, token_path,
              log_queue, stop_event):
    """Process jobs sequentially in a background thread.

    Args:
        jobs: List of dicts with keys:
              json_path, effect_style, privacy, auto_upload, status
        base_cfg: Shared config dict (voice, video settings). Individual job
                  overrides (effect_style, privacy) are merged in per-job.
        client_secrets_path: Path to Google client_secrets.json (for upload).
        token_path: Path to YouTube token JSON.
        log_queue: queue.Queue — caller puts log lines here.
        stop_event: threading.Event — set to cancel after current job.

    Yields nothing — all output goes through log_queue and mutates jobs[].status.
    Call this in a thread; poll log_queue from the Gradio generator.
    """

    def log(msg):
        log_queue.put(str(msg))

    for idx, job in enumerate(jobs):
        if stop_event.is_set():
            job["status"] = STATUS_SKIPPED
            log(f"⏩ Job {idx + 1}/{len(jobs)} skipped (stopped).")
            continue

        json_path = job["json_path"]
        log(f"\n{'='*60}")
        log(f"▶ Job {idx + 1}/{len(jobs)}: {os.path.basename(json_path)}")
        log(f"{'='*60}")
        job["status"] = STATUS_RUNNING

        # Merge base config with per-job overrides
        cfg = dict(base_cfg)
        cfg["json"] = json_path
        cfg["effect_style"] = job.get("effect_style") or base_cfg.get(
            "effect_style", "Horror Cinematic")
        # Derive output paths from JSON filename
        stem = os.path.splitext(os.path.abspath(json_path))[0]
        cfg.setdefault("voice_out", stem + "_voice.mp3")
        cfg.setdefault("video_out", stem + ".mp4")
        cfg.setdefault("segments_output", stem + "_segments")

        try:
            output = run_make_video(cfg, log, lambda v: None)
            if output and os.path.exists(output):
                job["status"] = STATUS_DONE
                log(f"✅ Rendered: {output}")

                if job.get("auto_upload") and client_secrets_path and token_path:
                    log(f"  Uploading to YouTube (privacy: {job.get('privacy', 'private')})...")
                    try:
                        import json as _json
                        with open(json_path, encoding="utf-8") as _f:
                            _data = _json.load(_f)
                        yt_title = _data.get("title", os.path.basename(json_path))
                        video_id = upload_to_youtube(
                            video_path=output,
                            title=yt_title,
                            description="",
                            tags="horror, narration",
                            privacy=job.get("privacy", "private"),
                            client_secrets_path=client_secrets_path,
                            token_path=token_path,
                            log=log,
                        )
                        log(f"  📺 YouTube: https://youtu.be/{video_id}")
                    except Exception as yt_exc:
                        log(f"  ⚠️ YouTube upload failed: {str(yt_exc)[:120]}")
            else:
                job["status"] = STATUS_FAILED
                log(f"❌ Render produced no output file.")
        except Exception as exc:
            job["status"] = STATUS_FAILED
            log(f"❌ Job failed: {str(exc)[:200]}")

    log(f"\n{'='*60}")
    done = sum(1 for j in jobs if j["status"] == STATUS_DONE)
    failed = sum(1 for j in jobs if j["status"] == STATUS_FAILED)
    log(f"Queue complete: {done} done, {failed} failed, {len(jobs) - done - failed} skipped.")
    log(f"{'='*60}")
