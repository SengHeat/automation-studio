"""Compatibility facade for the modular Automation Studio package."""

from .audio import *  # noqa: F401,F403
from .config import *  # noqa: F401,F403
from .gradio_ui import build_gradio_ui, main
from .pipeline import *  # noqa: F401,F403
from .stock_media import *  # noqa: F401,F403
from .story import check_segments, export_prompts
from .story_generator import generate_story_json, save_story_json
from .tkinter_ui import App, ScrollableFrame
from .video import *  # noqa: F401,F403
from .voice import *  # noqa: F401,F403


if __name__ == "__main__":
    main()
