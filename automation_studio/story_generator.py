"""AI-powered story JSON generator using the Anthropic Claude API."""

import json
import os
import re

from .config import ANTHROPIC_KEY, EMOTION_DIRECTIONS


_GENRES = {
    "Horror":      "slow, restrained horror narration with dread and unease",
    "Mystery":     "calm, investigative tone with measured curiosity",
    "Thriller":    "tense, urgent delivery with rising suspense",
    "True Crime":  "neutral, journalistic tone — factual yet gripping",
    "Sci-Fi":      "thoughtful, ominous narration with a sense of wonder and danger",
}


def _build_prompt(title, premise, genre, duration_minutes, segment_count, language):
    """Return the Claude user prompt for story JSON generation."""
    seconds_per_segment = int((duration_minutes * 60) / segment_count)
    words_per_segment = int(seconds_per_segment * 2.5)
    emotion_options = ", ".join(EMOTION_DIRECTIONS.keys())
    narration_note = _GENRES.get(genre, "neutral, engaging narration")

    # Build duration ranges: "0:00-1:00", "1:00-2:00", ...
    ranges = []
    for i in range(segment_count):
        start_s = i * seconds_per_segment
        end_s = (i + 1) * seconds_per_segment
        ranges.append(f"{start_s // 60}:{start_s % 60:02d}-{end_s // 60}:{end_s % 60:02d}")

    return f"""You are a professional storyteller and screenwriter.

Generate a complete story JSON for an automated narration video system.

STORY BRIEF:
- Title: {title}
- Premise: {premise}
- Genre: {genre}
- Total duration: {duration_minutes} minutes
- Segments: {segment_count}
- Language: {language}

OUTPUT RULES:
1. Output ONLY valid JSON — no markdown, no explanation, no code fences.
2. The JSON must have this exact top-level structure:
   {{"title": "...", "language": "{language}", "segments": [...]}}
3. Each segment must have EXACTLY these fields:
   - "segment_id": integer starting at 1
   - "title": short scene title (3-6 words)
   - "target_text": narration text (~{words_per_segment} words, spoken in {language})
   - "duration": use EXACTLY these pre-assigned ranges in order: {json.dumps(ranges)}
   - "stock_query": 5-8 keyword visual description for stock footage search (English always)
   - "emotion": one of: {emotion_options}
   - "control_instruction": "{narration_note}"
4. Write exactly {segment_count} segments.
5. The story must have a clear beginning, rising tension, and resolution.
6. "stock_query" must be visual and cinematic (e.g. "dark forest fog night cinematic").
7. Choose "emotion" that best matches each scene's mood.

Generate the JSON now:"""


def generate_story_json(title, premise, genre, duration_minutes,
                        segment_count, language, log, api_key=ANTHROPIC_KEY):
    """Call Claude to generate a story JSON dict.

    Returns the parsed dict on success, or None on failure.
    """
    if not api_key:
        log("❌ ANTHROPIC_KEY not set. Add it to your .env file: ANTHROPIC_KEY=sk-ant-...")
        return None

    try:
        import anthropic
    except ImportError:
        log("❌ anthropic package not installed. Run: pip install anthropic")
        return None

    prompt = _build_prompt(title, premise, genre, duration_minutes, segment_count, language)
    log(f"  Calling Claude (claude-haiku-4-5-20251001) for '{title}' — {segment_count} segments, {duration_minutes} min...")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
    except Exception as exc:
        log(f"❌ Claude API error: {exc}")
        return None

    # Strip markdown code fences if Claude wrapped output anyway
    clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE).strip()

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        log(f"❌ Claude returned invalid JSON: {exc}")
        log(f"  Raw response (first 400 chars): {raw[:400]}")
        return None

    segments = data.get("segments", [])
    if not segments:
        log("❌ Generated JSON has no segments.")
        return None

    if len(segments) != segment_count:
        log(f"  ⚠️ Expected {segment_count} segments, got {len(segments)} — continuing anyway.")

    log(f"  ✅ Generated {len(segments)} segments ({duration_minutes} min total)")
    return data


def _build_txt2json_prompt(plain_text, genre, language, segment_count):
    """Return the Claude prompt for converting plain text to story JSON."""
    narration_note = _GENRES.get(genre, "neutral, engaging narration")
    emotion_options = ", ".join(EMOTION_DIRECTIONS.keys())
    approx_words = len(plain_text.split())
    approx_secs = max(30, int((approx_words / 130) * 60))
    secs_per_seg = max(30, approx_secs // segment_count)

    return f"""You are a story structure specialist.

Convert the following plain-text story into a structured story JSON for an automated narration video system.

IMPORTANT RULES:
1. Output ONLY valid JSON — no markdown, no explanation, no code fences.
2. Top-level structure: {{"title": "...", "language": "{language}", "segments": [...]}}
3. Split the text into exactly {segment_count} segments at natural scene/paragraph breaks.
4. Each segment MUST have:
   - "segment_id": integer starting at 1
   - "title": short scene title (3-6 words)
   - "target_text": the exact portion of the original text for this segment (do NOT rewrite it)
   - "duration": estimated range "M:SS-M:SS" based on reading pace (~130 wpm, ~{secs_per_seg}s per segment)
   - "stock_query": 5-8 keyword visual description (English always, cinematic)
   - "emotion": one of: {emotion_options}
   - "control_instruction": "{narration_note}"
5. Each segment's "target_text" must use the ORIGINAL author's words verbatim.
6. The total of all "target_text" values must cover the entire input text.
7. Extract a story title from the text (first heading or first sentence), or use "Untitled Story".

PLAIN TEXT TO CONVERT:
---
{plain_text}
---

Generate the JSON now:"""


def convert_text_to_story_json(plain_text, genre, language, segment_count, output_path, log,
                               api_key=ANTHROPIC_KEY):
    """Convert plain text into story JSON using Claude. Returns parsed dict or None."""
    if not plain_text or not plain_text.strip():
        log("❌ No text provided.")
        return None
    if not api_key:
        log("❌ ANTHROPIC_KEY not set.")
        return None
    try:
        import anthropic
    except ImportError:
        log("❌ anthropic package not installed.")
        return None

    prompt = _build_txt2json_prompt(plain_text.strip(), genre, language, int(segment_count))
    word_count = len(plain_text.split())
    log(f"  Calling Claude to convert {word_count} words → {segment_count} segments...")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
    except Exception as exc:
        log(f"❌ Claude API error: {exc}")
        return None

    clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE).strip()

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        log(f"❌ Claude returned invalid JSON: {exc}")
        log(f"  Raw response (first 400 chars): {raw[:400]}")
        return None

    if not data.get("segments"):
        log("❌ No segments in output.")
        return None

    log(f"  ✅ Converted to {len(data['segments'])} segments.")
    return data


def save_story_json(data, output_path, log):
    """Write story dict to a JSON file. Returns the path or None on error."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log(f"  ✅ Saved to {output_path}")
        return output_path
    except Exception as exc:
        log(f"❌ Failed to save JSON: {exc}")
        return None
