"""Local Chatterbox, VoxCPM2, and Edge TTS voice generation."""

import gc
import os
import random
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .audio import merge_voice_chunks, normalize_audio_lufs, safe_log, split_voice_text
from .config import FFMPEG, VOICE_PRESETS, VOICE_STYLES, segment_emotion


VOXCPM2_URLS = [
    "https://openbmb-voxcpm-demo.hf.space",
    "openbmb/VoxCPM-Demo",
]


_CHATTERBOX_MODELS = {}
_CHATTERBOX_LOCK = threading.Lock()


def _chatterbox_device(requested="auto"):
    """Choose the fastest available Chatterbox device."""
    requested = str(requested or "auto").strip().lower()
    import torch
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "mps":
        mps = getattr(torch.backends, "mps", None)
        return "mps" if mps and mps.is_available() else "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_chatterbox(device):
    """Lazily load and cache one model per device."""
    with _CHATTERBOX_LOCK:
        if device not in _CHATTERBOX_MODELS:
            try:
                from perth.perth_net.perth_net_implicit.perth_watermarker import (  # noqa: F401
                    PerthImplicitWatermarker,
                )
            except ModuleNotFoundError as exc:
                if exc.name == "pkg_resources":
                    raise RuntimeError(
                        "Chatterbox requires pkg_resources for audio watermarking. "
                        "Run: pip install 'setuptools<81'"
                    ) from exc
                raise
            from chatterbox.tts import ChatterboxTTS
            _CHATTERBOX_MODELS[device] = ChatterboxTTS.from_pretrained(device=device)
        return _CHATTERBOX_MODELS[device]


def _chatterbox_free_memory(device):
    """Release cached tensors from the MPS/CUDA device after each generation."""
    import torch
    gc.collect()
    if device == "mps":
        torch.mps.synchronize()
        torch.mps.empty_cache()
    elif device == "cuda":
        torch.cuda.synchronize()
        torch.cuda.empty_cache()


def generate_voice_chatterbox(segments, voice_ref, out_folder, log, voice_cfg):
    """Generate segments with the local Chatterbox English TTS model."""
    try:
        import torchaudio
        device = _chatterbox_device(voice_cfg.get("chatterbox_device", "auto"))
    except ImportError:
        log("❌ Chatterbox is not installed. Use Python 3.11 and run: pip install chatterbox-tts")
        return []
    except Exception as e:
        log(f"❌ Chatterbox device setup failed: {str(e)[:100]}")
        return []

    os.makedirs(out_folder, exist_ok=True)
    requested_device = str(voice_cfg.get("chatterbox_device", "auto") or "auto").lower()
    if requested_device not in {"auto", device}:
        log(f"  ⚠️ {requested_device.upper()} is unavailable in this PyTorch build; using {device.upper()}")
    log(f"  Loading Chatterbox locally on {device.upper()} (first run downloads the model)...")
    try:
        model = _load_chatterbox(device)
    except Exception as e:
        log(f"❌ Could not load Chatterbox: {str(e)[:140]}")
        return []

    audio_prompt = voice_ref if voice_ref and os.path.exists(voice_ref) else None
    if audio_prompt:
        log(f"  Mode: local voice cloning (ref: {os.path.basename(audio_prompt)})")
    else:
        log("  Mode: Chatterbox built-in voice")

    exaggeration = max(0.0, min(2.0, float(voice_cfg.get("chatterbox_exaggeration", 0.5))))
    cfg_weight = max(0.0, min(1.0, float(voice_cfg.get("chatterbox_cfg_weight", 0.5))))
    generated = []

    # A model instance is deliberately reused sequentially. Concurrent calls on
    # the same PyTorch model can corrupt state or exhaust unified/GPU memory.
    for seg in segments:
        sid = int(seg.get("segment_id", 0))
        text = (seg.get("target_text") or "").strip()
        if not text:
            continue
        out_mp3 = os.path.join(out_folder, f"{sid:02d}.mp3")
        if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1500:
            generated.append(sid)
            log(f"    ⏭️ seg {sid:02d} already exists")
            continue

        chunks = split_voice_text(text)
        parts = []
        transient_paths = []
        log(f"    🎙 seg {sid:02d} ({len(chunks)} chunk{'s' if len(chunks) != 1 else ''})")
        try:
            # Pre-compute reference conditioning once per segment rather than
            # redundantly on every chunk, to avoid repeated tensor allocations.
            if audio_prompt:
                model.prepare_conditionals(audio_prompt, exaggeration=exaggeration)
            for index, chunk in enumerate(chunks, 1):
                wav_path = os.path.join(out_folder, f".{sid:02d}.cb{index:02d}.wav")
                mp3_path = out_mp3 + f".part{index:02d}.mp3"
                transient_paths.extend((wav_path, mp3_path))
                kwargs = {
                    "exaggeration": exaggeration,
                    "cfg_weight": cfg_weight,
                }
                wav = model.generate(chunk, **kwargs)
                torchaudio.save(wav_path, wav.cpu(), model.sr)
                del wav
                _chatterbox_free_memory(model.device)
                converted = subprocess.run(
                    [FFMPEG, "-y", "-i", wav_path,
                     "-af", "loudnorm=I=-16:TP=-1.5:LRA=7",
                     "-c:a", "libmp3lame", "-b:a", "192k", mp3_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
                if converted.returncode != 0 or not os.path.exists(mp3_path) or os.path.getsize(mp3_path) <= 1500:
                    raise RuntimeError(f"audio conversion failed for chunk {index}")
                parts.append(mp3_path)

            if parts and merge_voice_chunks(parts, out_mp3):
                generated.append(sid)
                log(f"    ✅ seg {sid:02d} (Chatterbox local)")
            else:
                raise RuntimeError("could not merge generated chunks")
        except Exception as e:
            log(f"    ❌ seg {sid:02d}: {str(e)[:120]}")
        finally:
            for path in transient_paths:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            _chatterbox_free_memory(device)

    log(f"  Chatterbox local: {len(generated)}/{len(segments)} segments")
    return generated


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

            subprocess.run(
                [FFMPEG, "-y", "-i", str(audio_path),
                 "-af", "loudnorm=I=-16:TP=-1.5:LRA=7",
                 "-c:a", "libmp3lame", "-b:a", "192k", out_mp3],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=45
            )

            if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1500:
                safe_log(log, f"    ✅ {display} (attempt {attempt})")
                return True
            else:
                raise RuntimeError("Output too small / missing")

        except Exception as e:
            error = str(e)
            if attempt < max_retries:
                delay = min(20.0, (2 ** attempt) + random.uniform(0.5, 2.0))
                safe_log(log, f"    ⚠️ {display} attempt {attempt}: {error[:45]} → retry in {delay:.1f}s")
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

    client = None
    for url in VOXCPM2_URLS:
        try:
            log(f"  Connecting to {url} ...")
            client = Client(url, verbose=False)
            log(f"  ✅ Connected to {url}")
            break
        except Exception as e:
            log(f"  ⚠️ Failed: {str(e)[:80]}")
            continue

    if client is None:
        log("❌ Could not connect to VoxCPM2. Will try fallback.")
        return []

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
        if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1500:
            log(f"    ⏭️ seg {sid:02d} already exists")
            existing.append(sid)
            continue
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
                    client, active_has_ref[0], seg, full_ci, part, active_ref[0],
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
            sid, success = future.result()
            completed += 1
            if success:
                generated.append(sid)
            safe_log(log, f"  Progress: {completed}/{total}  (new ok: {len(generated) - len(existing)})")

    # A quiet, single-worker recovery pass is much more successful than falling
    # back immediately after the Space has just been saturated.
    failed_jobs = [job for job in jobs if job[0] not in generated]
    if failed_jobs:
        log(f"  🩹 Recovery pass: {len(failed_jobs)} failed segment(s), one at a time...")
        time.sleep(3)
        for job in failed_jobs:
            sid, success = _generate_job(job, retries=2)
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

    targets = missing_ids if missing_ids else [int(s.get("segment_id", 0)) for s in segments]

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
                async def generate():
                    comm = edge_tts.Communicate(text, voice, rate="+0%", pitch="+0Hz")
                    await comm.save(out_mp3)

                asyncio.run(generate())

                if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1500:
                    if not normalize_audio_lufs(out_mp3):
                        raise RuntimeError("Edge-TTS loudness normalization failed")
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
                subprocess.run([
                    FFMPEG, "-y", "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=22050",
                    "-t", "4", "-c:a", "libmp3lame", "-b:a", "192k", out_mp3
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if os.path.exists(out_mp3):
                    log(f"    🔇 Created silent placeholder for seg {sid:02d}")
            except Exception:
                pass

        time.sleep(0.2)

    log(f"  edge-tts: {len(generated)}/{len(targets)} segments")
    return generated


def generate_voice(segments, voice_ref, out_folder, log, voice_cfg, max_workers=2):
    """Generate voice with the selected primary backend and resilient fallbacks."""
    backend = str(voice_cfg.get("voice_backend", "voxcpm2")).strip().lower()
    if backend == "chatterbox":
        log("  Attempting Chatterbox (local)...")
        generated = generate_voice_chatterbox(segments, voice_ref, out_folder, log, voice_cfg)
        missing_after_local = [
            seg for seg in segments
            if (seg.get("target_text") or "").strip()
            and int(seg.get("segment_id", 0)) not in generated
        ]
        if missing_after_local:
            log(f"  ⚠️ {len(missing_after_local)} local segment(s) failed → VoxCPM2 fallback...")
            generated.extend(generate_voice_voxcpm2(
                missing_after_local, voice_ref, out_folder, log, voice_cfg, max_workers))
    else:
        log("  Attempting VoxCPM2 (parallel)...")
        generated = generate_voice_voxcpm2(segments, voice_ref, out_folder, log, voice_cfg, max_workers)

    all_ids = [int(s.get("segment_id", 0)) for s in segments if s.get("target_text", "").strip()]
    missing = [sid for sid in all_ids if sid not in generated]

    if missing:
        log(f"  ⚠️ {len(missing)} segments still missing → edge-tts fallback...")
        edge_generated = generate_voice_edge(segments, out_folder, log, missing)
        generated.extend(edge_generated)

    final_missing = [sid for sid in all_ids if sid not in generated]
    if final_missing:
        log(f"  ⚠️ {len(final_missing)} segments still missing → creating silence: {final_missing}")
        for sid in final_missing:
            out_mp3 = os.path.join(out_folder, f"{sid:02d}.mp3")
            try:
                subprocess.run([
                    FFMPEG, "-y", "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=22050",
                    "-t", "5", "-c:a", "libmp3lame", "-b:a", "192k", out_mp3
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if os.path.exists(out_mp3):
                    log(f"    🔇 silence for seg {sid:02d}")
                    generated.append(sid)
            except Exception:
                pass

    return len(generated) > 0
