"""Automation Studio application package.

The public imports below preserve access to the main UI and pipeline functions
without making the repository entry point responsible for their implementation.
"""

from .application import (
    App,
    build_gradio_ui,
    check_segments,
    export_prompts,
    generate_story_json,
    main,
    run_make_multi_story_video,
    run_make_video,
    run_voice_only,
    save_story_json,
)

__all__ = [
    "App",
    "build_gradio_ui",
    "check_segments",
    "export_prompts",
    "generate_story_json",
    "main",
    "run_make_multi_story_video",
    "run_make_video",
    "run_voice_only",
    "save_story_json",
]
