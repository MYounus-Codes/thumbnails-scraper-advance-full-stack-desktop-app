from __future__ import annotations

from pathlib import Path
import os


def _playwright_cache_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local")
    return Path(local_app_data) / "ms-playwright"


os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_playwright_cache_dir())