"""VoxCPM2 and Edge TTS voice generation."""

import os
import random
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .audio import merge_voice_chunks, normalize_audio_lufs, safe_log, split_voice_text
from .config import FFMPEG, VOICE_PRESETS, VOICE_STYLES, segment_emotion


VOXCPM2_URLS = [
    "https://openbmb-voxcpm-demo.hf.space",
    "openbmb/VoxCPM-Demo",
]


def _silence_marker(audio_path):
    """Return the sidecar used to distinguish fallback silence from real speech."""
    return audio_path + ".silent"


def _is_generated_speech(audio_path):
    return (os.path.exists(audio_path) and os.path.getsize(audio_path) > 1500
            and not os.path.exists(_silence_marker(audio_path)))


def _clear_silence_marker(audio_path):
    try:
        os.unlink(_silence_marker(audio_path))
    except OSError:
        pass


def _mark_silence(audio_path):
    with open(_silence_marker(audio_path), "w", encoding="utf-8") as marker:
        marker.write("Generated fallback silence; retry voice synthesis on the next run.\n")


def _remove_file(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def generate_single_segment_retry(client, has_ref, seg, full_ci, out_mp3, voice_ref,
                                  cfg_value, do_normalize, denoise, log, max_retries=4,
                                  text_override=None, label=None):
    """Generate a single segment with retries (thread-safe)"""
    sid = int(seg.get("segment_id", 0))
    text = (text_override if text_override is not None else seg.get("target_text") or "").strip()
    display = label or f"seg {sid:02d}"

    if not text:
        return False

    # Avoid a retry stampede against the public Space. Each worker begins at a
    # slightly different time and transient failures receive exponential backoff.
    time.sleep(random.uniform(0.0, 0.8))
    for attempt in range(1, max_retries + 1):
        try:
            from gradio_client import handle_file

            # A cancelled/crashed prior run may have left this attempt's target
            # behind. Never mistake that stale file for the current API result.
            _remove_file(out_mp3)

            kwargs = {
                "text_input": text,
                "control_instruction": full_ci,
                "reference_wav_path_input": None,
                "use_prompt_text": False,
                "prompt_text_input": "",
                "cfg_value_input": float(cfg_value),
                "do_normalize": bool(do_normalize),
                "denoise": bool(denoise),
                "api_name": "/generate",
            }

            if has_ref:
                kwargs["reference_wav_path_input"] = handle_file(voice_ref)

            result = client.predict(**kwargs)

            if not result:
                raise RuntimeError("Empty result from API")

            # Extract audio path
            audio_path = None
            if isinstance(result, (list, tuple)) and result:
                audio_path = result[0]
            elif isinstance(result, dict):
                audio_path = result.get("audio") or result.get("output") or result.get("path")
            else:
                audio_path = str(result)

            if not audio_path or not os.path.exists(str(audio_path)):
                raise RuntimeError(f"No valid audio: {audio_path}")

            converted = subprocess.run(
                [FFMPEG, "-y", "-i", str(audio_path),
                 "-af", "loudnorm=I=-16:TP=-1.5:LRA=7",
                 "-c:a", "libmp3lame", "-b:a", "192k", out_mp3],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=45
            )

            if (converted.returncode == 0 and os.path.exists(out_mp3)
                    and os.path.getsize(out_mp3) > 1500):
                _clear_silence_marker(out_mp3)
                safe_log(log, f"    ✅ {display} (attempt {attempt})")
                return True
            else:
                raise RuntimeError("Output too small / missing")

        except Exception as e:
            error = str(e)
            if attempt < max_retries:
                is_dns = any(k in error for k in ("Errno 8", "nodename", "servname", "Name or service"))
                # DNS failures need much longer recovery time than transient API errors
                base_delay = 30.0 if is_dns else (2 ** attempt)
                delay = min(60.0, base_delay + random.uniform(0.5, 3.0))
                safe_log(log, f"    ⚠️ {display} attempt {attempt}: {error[:45]} → retry in {delay:.1f}s"
                              + (" (DNS — waiting for recovery)" if is_dns else ""))
                time.sleep(delay)
            else:
                safe_log(log, f"   ❌ {display}: {error[:70]}")

    return False


def generate_voice_voxcpm2(segments, voice_ref, out_folder, log, voice_cfg, max_workers=2):
    """Generate voice using VoxCPM2 — PARALLEL"""
    try:
        from gradio_client import Client
    except ImportError:
        log("❌ gradio_client not installed. Run: pip install gradio_client")
        return []
    except Exception as e:
        log(f"❌ gradio_client import error: {e}")
        return []

    os.makedirs(out_folder, exist_ok=True)

    def _connect():
        for url in VOXCPM2_URLS:
            try:
                log(f"  Connecting to {url} ...")
                c = Client(url, verbose=False, httpx_kwargs={"timeout": 300})
                log(f"  ✅ Connected to {url}")
                return c
            except Exception as e:
                log(f"  ⚠️ Failed: {str(e)[:80]}")
        return None

    client = _connect()
    if client is None:
        log("❌ Could not connect to VoxCPM2. Will try fallback.")
        return []

    # Mutable so the recovery pass can swap in a fresh client after DNS drop
    active_client = [client]

    has_ref = bool(voice_ref and os.path.exists(voice_ref))
    if has_ref:
        log(f"  Mode: Cloning (ref: {os.path.basename(voice_ref)})")
    else:
        log("  Mode: Voice Design")

    voice_preset = voice_cfg.get("voice_preset", "")
    voice_style  = voice_cfg.get("voice_style", "")
    cfg_value    = float(voice_cfg.get("cfg_value", 2.0))
    do_normalize = voice_cfg.get("do_normalize", False)
    denoise      = voice_cfg.get("denoise", False)
    auto_emotion = voice_cfg.get("auto_emotion", True)
    speaker_lock = voice_cfg.get("speaker_lock", True)

    if voice_preset and voice_preset in VOICE_PRESETS:
        control_desc = VOICE_PRESETS[voice_preset]
        if voice_style and voice_style in VOICE_STYLES:
            control_desc = f"{control_desc} Also {VOICE_STYLES[voice_style]}."
    elif voice_style and voice_style in VOICE_STYLES:
        control_desc = VOICE_STYLES[voice_style]
    else:
        control_desc = "Natural, balanced, conversational voice."

    log(f"  Control: {control_desc[:60]}...")
    # Public HF Spaces are queue-backed and become unreliable under a burst of
    # concurrent uploads. Two requests still give parallelism without flooding it.
    requested_workers = max(1, int(max_workers))
    max_workers = min(requested_workers, 2)
    if requested_workers != max_workers:
        log(f"  ℹ️ Workers capped at {max_workers} for VoxCPM2 public-space stability")
    log(f"  CFG: {cfg_value:.1f} | Parallel workers: {max_workers}")

    # Prepare jobs
    jobs = []
    existing = []
    for seg in segments:
        sid = int(seg.get("segment_id", 0))
        text = (seg.get("target_text") or "").strip()
        if not text:
            continue
        seg_ci = (seg.get("control_instruction") or "").strip()
        emotion, emotion_ci = segment_emotion(seg, auto_emotion)
        consistency_ci = ("Use exactly one narrator identity for the entire production. Never act as "
                          "another character. Never change gender, age, accent, vocal identity, pitch range, "
                          "or vocal weight for dialogue. Read quoted speech in the same narrator voice. "
                          "Express emotion only through subtle pacing and emphasis.")
        # A JSON control_instruction may request character acting or a different
        # age/gender. Under speaker lock it must not override narrator identity.
        instruction_parts = (control_desc, emotion_ci, consistency_ci) if speaker_lock else (
            control_desc, emotion_ci, seg_ci, consistency_ci)
        full_ci = " ".join(p for p in instruction_parts if p).strip()
        log(f"    🎭 seg {sid:02d} feeling: {emotion}")
        out_mp3 = os.path.join(out_folder, f"{sid:02d}.mp3")
        if _is_generated_speech(out_mp3):
            log(f"    ⏭️ seg {sid:02d} already exists")
            existing.append(sid)
            continue
        if os.path.exists(_silence_marker(out_mp3)):
            log(f"    🔁 seg {sid:02d} was fallback silence; retrying VoxCPM2")
            _remove_file(out_mp3)
            _clear_silence_marker(out_mp3)
        jobs.append((sid, seg, full_ci, out_mp3))

    total = len(jobs)
    if total == 0:
        log("  All segments already exist." if existing else "  No text.txt segments to generate.")
        return existing

    log(f"  🚀 Launching {total} segments in parallel (max {max_workers} workers)...")

    generated = list(existing)
    completed = 0

    active_ref = [voice_ref]
    active_has_ref = [has_ref]

    def _generate_job(item, retries=3):
        sid, seg, full_ci, out_mp3 = item
        chunks = split_voice_text(seg.get("target_text", ""))
        if len(chunks) > 1:
            safe_log(log, f"    ✂️ seg {sid:02d}: {len(chunks)} chunks (~15s maximum each)")
        parts = []
        for index, chunk in enumerate(chunks, 1):
            part = out_mp3 + f".part{index:02d}.mp3"
            label = f"seg {sid:02d} chunk {index}/{len(chunks)}"
            if not generate_single_segment_retry(
                    active_client[0], active_has_ref[0], seg, full_ci, part, active_ref[0],
                    cfg_value, do_normalize, denoise, log, max_retries=retries,
                    text_override=chunk, label=label):
                for made in parts:
                    try: os.unlink(made)
                    except OSError: pass
                return sid, False
            parts.append(part)
        success = bool(parts) and merge_voice_chunks(parts, out_mp3)
        for part in parts:
            if os.path.exists(part):
                try: os.unlink(part)
                except OSError: pass
        return sid, success

    def _worker(item):
        return _generate_job(item, retries=3)

    # With no user reference, create one anchor segment first and clone it for
    # every other request. This prevents VoxCPM from redesigning a new speaker.
    if speaker_lock and not has_ref and jobs:
        anchor_job = jobs.pop(0)
        anchor_sid, anchor_ok = _generate_job(anchor_job, retries=4)
        completed += 1
        if anchor_ok:
            generated.append(anchor_sid)
            active_ref[0] = anchor_job[3]
            active_has_ref[0] = True
            log(f"  🔒 Narrator locked from seg {anchor_sid:02d}; cloning this voice for all remaining segments")
        else:
            log("❌ Could not create narrator anchor; stopped to prevent mixed voices.")
            return generated

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_worker, job): job[0] for job in jobs}
        for future in as_completed(futures):
            sid = futures[future]
            try:
                _, success = future.result()
            except Exception as exc:
                success = False
                safe_log(log, f"   ❌ seg {sid:02d} worker error: {str(exc)[:70]}")
            completed += 1
            if success:
                generated.append(sid)
            safe_log(log, f"  Progress: {completed}/{total}  (new ok: {len(generated) - len(existing)})")

    # A quiet, single-worker recovery pass is much more successful than falling
    # back immediately after the Space has just been saturated.
    failed_jobs = [job for job in jobs if job[0] not in generated]
    if failed_jobs:
        log(f"  🩹 Recovery pass: {len(failed_jobs)} failed segment(s), one at a time...")
        log("  ⏳ Waiting 30s for network/DNS to stabilize...")
        time.sleep(30)
        # Reconnect with a fresh client — old client may have stale DNS state
        fresh = _connect()
        if fresh:
            active_client[0] = fresh
            log("  🔌 Reconnected to VoxCPM2 for recovery pass")
        else:
            log("  ⚠️ Could not reconnect — retrying with existing client")
        for job in failed_jobs:
            sid, success = _generate_job(job, retries=4)
            if success:
                generated.append(sid)

    log(f"  VoxCPM2 done: {len(generated)}/{total + len(existing)} segments")
    return generated


def generate_voice_edge(segments, out_folder, log, missing_ids=None):
    """Generate voice using edge-tts (fallback)"""
    try:
        import edge_tts
        import asyncio
    except ImportError:
        log("⚠️ edge-tts not installed. Try: pip install edge-tts")
        return []

    os.makedirs(out_folder, exist_ok=True)
    log("  Using edge-tts fallback...")

    voice = "en-US-JennyNeural"
    generated = []

    targets = (missing_ids if missing_ids is not None
               else [int(s.get("segment_id", 0)) for s in segments])

    for seg in segments:
        sid = int(seg.get("segment_id", 0))
        if sid not in targets:
            continue

        text = (seg.get("target_text") or "").strip()
        if not text:
            continue

        out_mp3 = os.path.join(out_folder, f"{sid:02d}.mp3")
        log(f"  edge-tts seg {sid:02d}")

        success = False
        for attempt in range(1, 4):
            try:
                _remove_file(out_mp3)

                async def generate():
                    comm = edge_tts.Communicate(text, voice, rate="+0%", pitch="+0Hz")
                    await comm.save(out_mp3)

                asyncio.run(generate())

                if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1500:
                    if not normalize_audio_lufs(out_mp3):
                        raise RuntimeError("Edge-TTS loudness normalization failed")
                    _clear_silence_marker(out_mp3)
                    generated.append(sid)
                    success = True
                    log(f"    ✅ seg {sid:02d} (edge-tts attempt {attempt}, -16 LUFS)")
                    break

            except Exception as e:
                if attempt < 3:
                    log(f"    ⚠️ edge-tts attempt {attempt} failed, retrying...")
                    time.sleep(1.5)
                else:
                    log(f"   ❌ seg {sid:02d}: {str(e)[:60]}")

        if not success:
            try:
                _mark_silence(out_mp3)
                silent = subprocess.run([
                    FFMPEG, "-y", "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=22050",
                    "-t", "4", "-c:a", "libmp3lame", "-b:a", "192k", out_mp3
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if (silent.returncode == 0 and os.path.exists(out_mp3)
                        and os.path.getsize(out_mp3) > 1500):
                    log(f"    🔇 Created silent placeholder for seg {sid:02d}")
                else:
                    _remove_file(out_mp3)
                    _clear_silence_marker(out_mp3)
            except Exception:
                _remove_file(out_mp3)
                _clear_silence_marker(out_mp3)
                pass

        time.sleep(0.2)

    log(f"  edge-tts: {len(generated)}/{len(targets)} segments")
    return generated


def generate_voice(segments, voice_ref, out_folder, log, voice_cfg, max_workers=2):
    """Generate voice - try VoxCPM2 parallel first, then edge-tts for missing ones"""
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        log("⚠️  edge-tts is NOT installed — if VoxCPM2 fails, segments will be silent gaps.")
        log("    Fix: pip install edge-tts")
    log("  Attempting VoxCPM2 (parallel)...")
    generated = generate_voice_voxcpm2(segments, voice_ref, out_folder, log, voice_cfg, max_workers)

    all_ids = [int(s.get("segment_id", 0)) for s in segments if s.get("target_text", "").strip()]
    missing = [sid for sid in all_ids if sid not in generated]

    if missing:
        log(f"  ⚠️ {len(missing)} segments failed in VoxCPM2 → edge-tts fallback...")
        edge_generated = generate_voice_edge(segments, out_folder, log, missing)
        generated.extend(edge_generated)

    final_missing = [sid for sid in all_ids if sid not in generated]
    if final_missing:
        log(f"  ⚠️ {len(final_missing)} segments still missing → creating silence: {final_missing}")
        for sid in final_missing:
            out_mp3 = os.path.join(out_folder, f"{sid:02d}.mp3")
            try:
                _mark_silence(out_mp3)
                silent = subprocess.run([
                    FFMPEG, "-y", "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=22050",
                    "-t", "5", "-c:a", "libmp3lame", "-b:a", "192k", out_mp3
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if (silent.returncode == 0 and os.path.exists(out_mp3)
                        and os.path.getsize(out_mp3) > 1500):
                    log(f"    🔇 silence for seg {sid:02d}")
                    generated.append(sid)
                else:
                    _remove_file(out_mp3)
                    _clear_silence_marker(out_mp3)
            except Exception:
                _remove_file(out_mp3)
                _clear_silence_marker(out_mp3)
                pass

    return len(generated) > 0
