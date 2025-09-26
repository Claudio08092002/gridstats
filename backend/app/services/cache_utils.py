from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
import json


def get_cache_dir(router_file: str) -> Path:
    """Resolve season cache folder relative to router/services package.
    router_file: pass __file__ from the caller module.
    """
    base = Path(router_file).resolve().parent.parent
    p = base / "season_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def season_cache_path(router_file: str, year: int) -> Path:
    return get_cache_dir(router_file) / f"season_{year}.json"


def load_season(router_file: str, year: int) -> Dict[str, Any] | None:
    p = season_cache_path(router_file, year)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_season(router_file: str, year: int, payload: Dict[str, Any]) -> None:
    p = season_cache_path(router_file, year)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
