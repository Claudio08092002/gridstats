import os
from pathlib import Path

# Single place to quickly force a debug driver points breakdown without touching docker-compose.
# Set to a 3-letter driver code (e.g. "PIA", "VER") or None to disable.
FORCE_DEBUG_DRIVER_POINTS = None

# Optional file-based override: put a file named .debug_driver in project root or backend/app
# containing a driver code. This is handy to toggle without code change.
_DEBUG_FILE_NAMES = [".debug_driver", "debug_driver.txt"]


def resolve_forced_debug_driver() -> str | None:
    # 1. Code constant wins if set
    if FORCE_DEBUG_DRIVER_POINTS:
        return FORCE_DEBUG_DRIVER_POINTS.strip().upper()
    # 2. Environment variable (still supported if user wants ephemeral toggle)
    envv = os.getenv("DEBUG_DRIVER_POINTS")
    if envv:
        v = envv.strip().upper()
        if v:
            return v
    # 3. File override
    search_dirs = [Path.cwd(), Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent]
    for d in search_dirs:
        for name in _DEBUG_FILE_NAMES:
            p = d / name
            if p.exists():
                try:
                    content = p.read_text(encoding="utf-8").strip().upper()
                    if content:
                        return content
                except Exception:
                    pass
    return None
