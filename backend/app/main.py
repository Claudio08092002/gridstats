# backend/app/main.py

from fastapi import FastAPI
import os
import fastf1
from fastf1.ergast import interface as ergast_interface
from fastapi.middleware.cors import CORSMiddleware

from app.routers import compare, track, constructor


ALLOWED_ORIGINS = [
    "http://localhost:4200",
    "https://claudio.stefanhohl.ch",
]
ALLOWED_ORIGIN_REGEX = r"^https://(?:.+\.)?stefanhohl\.ch$"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(compare.router, prefix="/api")
app.include_router(track.router, prefix="/api")
app.include_router(constructor.router, prefix="/api")

@app.get("/api/healthz")
def healthz():
    from pathlib import Path
    
    # Check cache directories
    app_dir = Path(__file__).resolve().parent
    tracks_cache = app_dir / "tracks_cache"
    season_cache = app_dir / "season_cache"
    
    tracks_files = []
    season_files = []
    
    if tracks_cache.exists():
        tracks_files = [f.name for f in tracks_cache.glob("*.json")]
    
    if season_cache.exists():
        season_files = [f.name for f in season_cache.glob("*.json")]
    
    return {
        "status": "ok",
        "fastf1_version": getattr(fastf1, "__version__", "unknown"),
        "fastf1_cache": os.getenv("FASTF1_CACHE"),
        "ergast_base": getattr(ergast_interface, "BASE_URL", None),
        "force_ergast": os.getenv("FORCE_ERGAST", ""),
        "app_dir": str(app_dir),
        "tracks_cache_exists": tracks_cache.exists(),
        "tracks_cache_path": str(tracks_cache),
        "tracks_cache_files": len(tracks_files),
        "tracks_files_sample": tracks_files[:5],
        "season_cache_exists": season_cache.exists(),
        "season_cache_path": str(season_cache),
        "season_cache_files": len(season_files),
        "season_files_sample": season_files[:5],
    }
