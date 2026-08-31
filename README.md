# Automation Studio

An automated horror/narrative video production pipeline. Generate voice narration, download stock footage, add background music, and render cinematic videos — all from a story JSON file.

---

## Quick Start

```bash
# Install dependencies
pip install gradio anthropic pydub numpy pillow gradio_client

# Launch the web UI
python3 index.py
# or
python3 -m automation_studio
```

---

## Features

### ✍️ Story JSON Generator
Generate a complete story JSON from a title and premise using Claude AI.

- Type a title + premise → Claude writes all segments with narration, timing, emotions, and stock queries
- Supports genres: Horror, Mystery, Thriller, True Crime, Sci-Fi
- Output JSON is immediately ready to feed into the Studio pipeline
- Requires `ANTHROPIC_KEY` in `.env`

### 🎙 Voice Generation
- VoxCPM2 voice cloning (via HuggingFace Space)
- Edge-TTS fallback for missing segments
- Speaker lock: clones one anchor voice across all segments for consistency
- Parallel generation with auto-retry
- Per-segment emotion direction (10 emotions supported)

### 🎵 Background Music
- **Upload a file** — use any local audio file as background music
- **Stock music query** — type a search term to auto-download free music:
  - Pixabay Audio API (high quality, requires `PIXABAY_KEY`)
  - ccMixter fallback (CC-licensed, no API key required)
- **Auto-ambience** — synthesizes a dark drone bed if no music is provided

### 🎬 Video Rendering
- Auto-downloads stock footage from Pexels for each segment (`PEXELS_KEY` required)
- Ken Burns slow-zoom effect for still images
- 4 cinematic color grades: Horror Cinematic, Blood Red, Black & White Dread, Natural Dark
- Smooth xfade transitions between clips
- Multi-story compilation with story cards
- FFmpeg-based rendering at up to 1080p

---

## Setup

### 1. Create `.env` in the project root

```env
# Required for stock video download
PEXELS_KEY=your_pexels_api_key

# Required for AI story generation
ANTHROPIC_KEY=sk-ant-api03-...

# Optional: higher-quality stock music (falls back to ccMixter if missing)
PIXABAY_KEY=your_pixabay_api_key

# Optional: HuggingFace token for VoxCPM2 private spaces
HF_TOKEN=hf_...

# Optional: default voice reference file for cloning
DEFAULT_VOICE_REF=/path/to/reference.mp3

# Optional: background sound for story cards
STORY_CARD_BG=/path/to/card_sound.mp3
```

### 2. Get API Keys

| Key | Where to get | Cost |
|-----|-------------|------|
| `PEXELS_KEY` | pexels.com/api | Free |
| `ANTHROPIC_KEY` | console.anthropic.com | Pay-as-you-go (~$0.001/story) |
| `PIXABAY_KEY` | pixabay.com/api/docs | Free |
| `HF_TOKEN` | huggingface.co/settings/tokens | Free |

> **Note:** `PIXABAY_KEY` and `ANTHROPIC_KEY` are optional. Without Pixabay, background music falls back to ccMixter (free, no key). Without Anthropic, the Story Generator tab is disabled.

---

## Story JSON Format

The pipeline accepts two formats:

### Simple format
```json
{
  "title": "My Story",
  "language": "English",
  "segments": [
    {
      "segment_id": 1,
      "title": "The Beginning",
      "target_text": "Narration text spoken aloud...",
      "duration": "0:00-1:00",
      "stock_query": "dark forest fog night cinematic",
      "emotion": "tense",
      "control_instruction": "Slow, restrained horror narration."
    }
  ]
}
```

### Compilation format (multiple stories)
```json
{
  "project": { "narration_notes": "Slow, restrained horror narration." },
  "stories": [
    {
      "title": "Story One",
      "by": "Author Name",
      "segments": [
        { "segment": 1, "narration": "...", "duration": "0:00-1:00" }
      ]
    }
  ]
}
```

Supported emotion values: `neutral`, `calm`, `mysterious`, `tense`, `fear`, `sad`, `angry`, `urgent`, `shocked`, `ominous`

---

## Workflow

```
1. ✍️ Generate Story tab
   → Enter title + premise → click Generate → save JSON

2. 🎬 Studio tab
   → Upload JSON → configure voice & video settings → click Make Video

3. Output
   → voice_final.mp3  (narration with background music)
   → output.mp4       (full cinematic video)
```

---

## Project Structure

| File | Purpose |
|------|---------|
| `index.py` | Entry point launcher |
| `automation_studio/config.py` | API keys, voice presets, emotion settings |
| `automation_studio/story_generator.py` | Claude AI story JSON generation |
| `automation_studio/story.py` | Segment validation and prompt export |
| `automation_studio/voice.py` | VoxCPM2 and Edge-TTS generation |
| `automation_studio/audio.py` | Audio normalization, merging, ambience |
| `automation_studio/stock_media.py` | Pexels video, Pixabay/ccMixter audio download |
| `automation_studio/video.py` | FFmpeg rendering and compilation |
| `automation_studio/pipeline.py` | Top-level workflow orchestration |
| `automation_studio/gradio_ui.py` | Web UI with two tabs: Generator + Studio |
| `automation_studio/tkinter_ui.py` | Optional desktop UI |
| `automation_studio/application.py` | Compatibility facade |
