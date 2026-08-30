"""Compatibility facade for the modular Automation Studio package."""

from .audio import *  # noqa: F401,F403
from .config import *  # noqa: F401,F403
from .gradio_ui import build_gradio_ui, main
from .pipeline import *  # noqa: F401,F403
from .stock_media import *  # noqa: F401,F403
from .story import check_segments, export_prompts
from .video import *  # noqa: F401,F403
from .voice import *  # noqa: F401,F403


try:
    from .tkinter_ui import App, ScrollableFrame
except ModuleNotFoundError as exc:
    if exc.name != "_tkinter":
        raise
    _TKINTER_IMPORT_ERROR = exc

    class _TkinterUnavailable:
        """Explain the optional desktop dependency when it is actually used."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "The optional Tkinter desktop UI is unavailable in this Python "
                "installation. Use the Gradio UI with `python index.py`, or "
                "install a Python build that includes Tkinter."
            ) from _TKINTER_IMPORT_ERROR

    App = _TkinterUnavailable
    ScrollableFrame = _TkinterUnavailable


if __name__ == "__main__":
    main()
