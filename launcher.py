import os
import sys

from streamlit_desktop_app import start_desktop_app


def resource_path(relative_path: str) -> str:
    """Resolve a bundled file's real path, whether running as a plain
    script or as a frozen PyInstaller exe (where files are extracted to
    a temp folder at sys._MEIPASS, not the exe's own directory)."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


if __name__ == "__main__":
    start_desktop_app(resource_path("graph_app.py"), title="Graph App")
