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
            data = json.load(open(story_path, encoding="utf-8"))
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
                      enable_subtitles, subtitle_size, subtitle_position):
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
                "preview": False,
                "show_title": False, "channel": "",
                "logo": "", "use_logo": False,
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


def build_gradio_ui():
    """Automation-Studio-style web UI for voice and video generation."""
    import gradio as gr

    css = """
    #run-log textarea { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    #gen-log textarea  { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    .studio-title { margin-bottom: 0 !important; }
    """
    with gr.Blocks(title="Horror Voice Studio") as demo:
        gr.Markdown("# 🎙 FilesAtNightfall — Voice & Video Studio", elem_classes="studio-title")
        gr.Markdown("VoxCPM2 cloning · resilient parallel generation · built-in cinematic video renderer")

        with gr.Tabs():

            # ── Tab 1: Story Generator ─────────────────────────────────────
            with gr.Tab("✍️ Generate Story"):
                gr.Markdown("### Generate a complete Story JSON from a title and premise using Claude AI")
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

            # ── Tab 2: Studio (voice + video) ─────────────────────────────
            with gr.Tab("🎬 Studio"):
                with gr.Row():
                    with gr.Column(scale=2):
                        gr.Markdown("### 📖 Story")
                        debug_story = (
                            [DEBUG_STORY_JSON]
                            if APP_DEBUG and DEBUG_STORY_JSON and os.path.isfile(DEBUG_STORY_JSON)
                            else None
                        )
                        story_json = gr.File(
                            value=debug_story,
                            label="Story JSON files (upload in Story 1, 2, 3 order)",
                            file_types=[".json"],
                            type="filepath",
                            file_count="multiple",
                        )
                        story_authors = gr.Textbox(
                            value="Anonymous", label="Authors in order (comma-separated)",
                            placeholder="Anonymous, Ranger P., John")
                        story_card_duration = gr.Slider(
                            3, 5, value=DEFAULT_STORY_CARD_DURATION, step=0.5,
                            label="Story-card duration (3–5 seconds)")
                        story_card_bg = gr.Textbox(
                            value=STORY_CARD_BG, label="Story-card background sound")
                        voice_source = gr.Radio(["generate", "existing"], value="generate", label="Voice source")
                        voice_out = gr.Textbox(value="voice_final.mp3", label="Final voice output")
                        segments_output = gr.Textbox(value="segments_audio", label="Individual segment folder")

                    with gr.Column(scale=5):
                        with gr.Accordion("🎙 Voice settings", open=True):
                            with gr.Row():
                                voice_preset = gr.Dropdown(list(VOICE_PRESETS), value="Balanced Neutral", label="Preset")
                                voice_style = gr.Dropdown(list(VOICE_STYLES), value="Balanced", label="Style")
                            voice_ref = gr.File(
                                value=DEFAULT_VOICE_REF,
                                label="Reference voice (optional)",
                                file_types=["audio"],
                                type="filepath",
                            )
                            voice_file = gr.File(label="Existing voice (when source = existing)", file_types=["audio"], type="filepath")

                        with gr.Accordion("⚙️ VoxCPM2 advanced", open=False):
                            with gr.Row():
                                cfg_value = gr.Slider(1.0, 3.0, value=1.7, step=0.1, label="CFG guidance (1.6–1.8 for Khmer)")
                                max_workers = gr.Slider(1, 2, value=2, step=1, label="Parallel workers")
                            with gr.Row():
                                do_normalize = gr.Checkbox(value=False, label="Text normalization")
                                denoise = gr.Checkbox(value=True, label="Reference denoising")
                            auto_emotion = gr.Checkbox(
                                value=False, label="Different feeling for every segment",
                                info="Uses emotion/feeling/mood from JSON, or detects it from English segment text.")
                            speaker_lock = gr.Checkbox(
                                value=True, label="Lock one narrator voice for all segments",
                                info="Creates one anchor voice, then clones it to prevent gender/age changes.")

                        with gr.Accordion("🎵 Background audio", open=False):
                            bg_music = gr.File(label="Music file (optional, overrides stock query)", file_types=["audio"], type="filepath")
                            bg_sound_query = gr.Textbox(
                                value="",
                                label="Stock background music query (leave blank to skip)",
                                placeholder="e.g. dark ambient horror, suspense, eerie wind",
                                info="Downloads free music from Pixabay (needs PIXABAY_KEY in .env) or ccMixter. Ignored when a Music file is uploaded.",
                            )
                            bg_percent = gr.Slider(0.0, 0.5, value=0.18, step=0.01, label="Music level")
                            auto_amb = gr.Checkbox(value=False, label="Generate dark ambience when no music is selected")

                        with gr.Accordion("🎬 Video settings", open=True):
                            video_out = gr.Textbox(value="", label="Video output (.mp4; blank = beside JSON)")
                            with gr.Row():
                                resolution = gr.Dropdown(["1920x1080", "1280x720"], value="1280x720", label="Resolution")
                                fps = gr.Slider(12, 30, value=20, step=1, label="FPS")
                                crf = gr.Slider(18, 28, value=18, step=1, label="Quality CRF")
                            transition_duration = gr.Slider(
                                0.3, 3.0, value=1.5, step=0.1,
                                label="Transition speed (seconds; higher = slower)")
                            effect_style = gr.Dropdown(
                                ["Horror Cinematic", "Blood Red", "Black & White Dread", "Natural Dark"],
                                value="Horror Cinematic", label="Horror visual effect")

                        with gr.Accordion("💬 Subtitles / Captions", open=False):
                            enable_subtitles = gr.Checkbox(
                                value=False,
                                label="Burn captions into video",
                                info="Reads narration timing from voice timeline. Adds one re-encode pass.")
                            with gr.Row():
                                subtitle_size = gr.Slider(
                                    14, 48, value=28, step=2, label="Font size (px)")
                                subtitle_position = gr.Dropdown(
                                    ["bottom", "top", "center"], value="bottom", label="Position")

                with gr.Row():
                    run_btn = gr.Button("▶ Generate Voice")
                    video_btn = gr.Button("🎬 Make Video", variant="primary")
                with gr.Row():
                    run_log = gr.Textbox(label="Live log", lines=18, interactive=False, elem_id="run-log", scale=4)
                    output_audio = gr.Audio(label="Final voice", type="filepath", interactive=False, scale=2)
                    output_video = gr.Video(label="Final video", interactive=False, scale=3)

                inputs = [story_json, voice_source, voice_preset, voice_style, voice_ref,
                          voice_file, cfg_value, do_normalize, denoise, auto_emotion, speaker_lock, max_workers,
                          bg_music, bg_sound_query, bg_percent, auto_amb, voice_out, segments_output]
                run_btn.click(_gradio_run_voice, inputs=inputs, outputs=[run_log, output_audio])
                video_inputs = inputs + [story_authors, story_card_duration, story_card_bg,
                                         video_out,
                                         resolution, fps, crf, transition_duration, effect_style,
                                         enable_subtitles, subtitle_size, subtitle_position]
                video_btn.click(_gradio_run_video, inputs=video_inputs, outputs=[run_log, output_video])

    return demo, css


def main():
    """Build and launch the Gradio application."""
    demo, ui_css = build_gradio_ui()
    demo.launch(inbrowser=True, share=False, css=ui_css,
                theme=__import__("gradio").themes.Base(primary_hue="blue", neutral_hue="slate"))
