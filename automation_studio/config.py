"""Application configuration, executable discovery, and voice presets."""

import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path=PROJECT_ROOT / ".env"):
    """Load simple KEY=VALUE entries without overriding shell environment."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] == value[-1:] and value[:1] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file()


FFMPEG  = shutil.which("ffmpeg")


FFPROBE = shutil.which("ffprobe")


PEXELS_KEY = os.getenv("PEXELS_KEY", "")


STORY_CARD_BG = os.getenv("STORY_CARD_BG", "")


DEFAULT_VOICE_REF = os.getenv("DEFAULT_VOICE_REF", "")


APP_DEBUG = os.getenv("APP_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


DEBUG_STORY_JSON = os.getenv("DEBUG_STORY_JSON", "")


DEFAULT_STORY_CARD_DURATION = 5.0


TENSE = ["hush","tense","dread","fear","terr","slow","dramatic","whisper","ominous",
         "chilling","shock","horror","unsettl","grave","weight","eerie","somber","deeply"]


FAST  = ["urgent","fast","chaos","intensity","frantic","escalat","rapid","quick","action"]


WARM  = ["warm","welcom","calm","conversational","friendly","gentle"]


VOICE_PRESETS = {
    "Balanced Neutral": "Natural, neutral voice with a calm and even tone. Keep the same pitch, volume, vocal identity, and speaking pace throughout. Speak clearly and steadily without emotional extremes.",
    "Gentle Narrator": "A soft, warm voice with a gentle and soothing quality. Calm and reassuring without being overly emotional.",
    "Professional Announcer": "Clear, well-modulated voice with balanced tone. Authoritative but not aggressive.",
    "Calm Storyteller": "Steady, measured voice with natural warmth. Engaging without being dramatic.",
    "Neutral Female": "Natural female voice with balanced pitch and tone. Clear and pleasant without emotional coloring.",
    "Neutral Male": "Natural male voice with even tone. Relaxed and professional without being monotone.",
    "Soft Spoken": "Quiet, gentle voice with a soft quality. Warm but restrained.",
}


VOICE_STYLES = {
    "Balanced": "balanced, natural, even-toned, steady",
    "Calm": "calm, composed, steady, measured",
    "Neutral": "neutral, even, balanced, natural",
    "Warm": "warm, gentle, friendly, pleasant",
    "Clear": "clear, articulate, distinct, well-paced",
    "Professional": "professional, polished, authoritative, confident",
    "Narrative": "narrative, flowing, steady, engaging",
    "Soft": "soft, gentle, quiet, intimate",
}


EMOTION_DIRECTIONS = {
    "neutral": "Remain natural, balanced, and emotionally restrained.",
    "calm": "Speak calmly and gently with an even pace.",
    "mysterious": "Sound mysterious and intimate, with deliberate pauses and quiet suspense.",
    "tense": "Build restrained tension; speak carefully with an uneasy, suspenseful tone.",
    "fear": "Sound genuinely frightened and vulnerable, with controlled urgency.",
    "sad": "Speak softly with grief, heaviness, and subdued emotion.",
    "angry": "Use controlled anger and firm emphasis without shouting.",
    "urgent": "Speak urgently with a quicker pace and clear, forceful emphasis.",
    "shocked": "Sound startled and disbelieving, then regain control naturally.",
    "ominous": "Use a low, grave, foreboding delivery with measured pacing.",
}


EMOTION_HINTS = {
    "fear": ("afraid", "fear", "terrified", "panic", "trembl", "scream"),
    "urgent": ("hurry", "run", "quick", "urgent", "immediately", "escape"),
    "shocked": ("suddenly", "shock", "couldn't believe", "could not believe", "gasp"),
    "sad": ("sad", "grief", "cry", "cried", "tears", "died", "death", "lost", "losing"),
    "angry": ("angry", "rage", "furious", "shouted", "yelled"),
    "ominous": ("dark", "death", "grave", "curse", "blood", "shadow"),
    "tense": ("slowly", "footstep", "behind", "door", "silence", "waiting"),
    "mysterious": ("mystery", "unknown", "whisper", "strange", "secret"),
    "calm": ("calm", "peace", "gentle", "quiet", "safe"),
}


def segment_emotion(seg, auto_detect=True):
    """Return (emotion name, Vox direction), preferring explicit JSON metadata."""
    explicit = next((str(seg.get(k, "")).strip().lower()
                     for k in ("emotion", "feeling", "mood", "voice_emotion")
                     if str(seg.get(k, "")).strip()), "")
    for name, direction in EMOTION_DIRECTIONS.items():
        if name in explicit:
            return name, direction
    if explicit:
        return explicit, f"Express this segment as {explicit}, naturally and without exaggeration."
    if auto_detect:
        sample = " ".join(str(seg.get(k, "")) for k in
                          ("title", "target_text", "control_instruction")).lower()
        for name, hints in EMOTION_HINTS.items():
            if any(hint in sample for hint in hints):
                return name, EMOTION_DIRECTIONS[name]
    return "neutral", EMOTION_DIRECTIONS["neutral"]
