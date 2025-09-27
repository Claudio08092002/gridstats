# backend/app/services/cache_utils.py

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
import json
import os

# Wurzelordner für Season-JSONs ermitteln
def season_cache_root(router_file: str) -> Path:
    # Optional per Env überschreibbar (wird in deinem Compose bereits gemountet)
    env_dir = os.getenv("SEASON_CACHE_DIR")
    if env_dir:
        p = Path(env_dir)
    else:
        # Default: <backend/app/>/season_cache
        p = Path(router_file).resolve().parent.parent / "season_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_cache_dir(router_file: str) -> Path:
    # Alias für bestehenden Code, der get_cache_dir verwendet
    return season_cache_root(router_file)

def season_cache_path(router_file: str, year: int) -> Path:
    return season_cache_root(router_file) / f"season_{year}.json"

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
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
