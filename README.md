# Automation Studio

Run the Gradio application with either entry point:

```bash
python3 index.py
# or
python3 -m automation_studio
```

## Project structure

- `index.py` — backward-compatible launcher
- `automation_studio/config.py` — executable paths, presets, and emotion settings
- `automation_studio/audio.py` — audio normalization, chunking, ambience, and merging
- `automation_studio/voice.py` — VoxCPM2 and Edge TTS generation
- `automation_studio/story.py` — story validation and prompt export
- `automation_studio/stock_media.py` — Pexels media lookup and timeline helpers
- `automation_studio/video.py` — FFmpeg rendering and multi-story compilation
- `automation_studio/pipeline.py` — top-level workflow orchestration
- `automation_studio/gradio_ui.py` — web UI and callbacks
- `automation_studio/tkinter_ui.py` — optional desktop UI
- `automation_studio/application.py` — compatibility facade for previous imports
