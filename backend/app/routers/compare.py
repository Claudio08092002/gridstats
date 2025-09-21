# backend/app/routers/compare.py
from fastapi import APIRouter, HTTPException, Response
import fastf1
import pandas as pd
from typing import Dict, Any
from app.services.f1_utils import load_results_strict
import os
# --- optional: Standard-Lib für Cache ---
from pathlib import Path
import json

router = APIRouter(prefix="/f1", tags=["fastf1"])


fastf1.Cache.enable_cache(os.getenv("FASTF1_CACHE", "/data/fastf1_cache"))

# === Persistenter JSON-Cache pro Saison ===
CACHE_DIR = (Path(__file__).resolve().parent.parent / "season_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _season_cache_path(year: int) -> Path:
    return CACHE_DIR / f"season_{year}.json"

def _load_from_cache(year: int) -> Dict[str, Any] | None:
    path = _season_cache_path(year)
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return None

def _save_to_cache(year: int, payload: Dict[str, Any]) -> None:
    path = _season_cache_path(year)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

# ======================================================

@router.get("/season/{year}")
def load_season(year: int, response: Response, refresh: bool = False) -> Dict[str, Any]:
    """
    Aggregiert pro Fahrer der Saison:
      total_points, wins, podiums, dnfs, avg_finish, poles=0

    - Nutzt robustes load_results_strict (fastf1 -> ergast -> derived)
    - Persistenter JSON-Cache pro Season unter app/season_cache
    - Mit ?refresh=true kann der Cache umgangen/neu geschrieben werden
    """
    try:
        # 1) Cache-Hit?
        if not refresh:
            cached = _load_from_cache(year)
            if cached:
                # leichtes HTTP-Caching für Browser
                response.headers["Cache-Control"] = "public, max-age=86400"
                return cached

        # 2) Daten neu berechnen
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        results_by_driver: Dict[str, Dict[str, Any]] = {}

        for _, ev in schedule.iterrows():
            rnd = ev.get("RoundNumber")
            if pd.isna(rnd) or int(rnd) <= 0:
                continue
            rnd = int(rnd)

            try:
                _, df = load_results_strict(year, rnd)  # robust: nimmt ggf. ergast/derived
            except Exception:
                continue
            if df is None or df.empty:
                continue

            # numerisch + Defaults
            if "Points" not in df.columns:
                df["Points"] = 0.0
            if "Position" not in df.columns:
                df["Position"] = pd.NA

            df["Points"] = pd.to_numeric(df["Points"], errors="coerce").fillna(0.0)
            df["Position"] = pd.to_numeric(df["Position"], errors="coerce")

            # Summierung pro Fahrer
            for _, row in df.iterrows():
                code = row.get("Abbreviation")
                if not code or pd.isna(code):
                    continue
                d = results_by_driver.setdefault(
                    code,
                    {
                        "name": row.get("FullName") or row.get("BroadcastName") or code,
                        "team": row.get("TeamName"),
                        "points": 0.0,
                        "wins": 0,
                        "podiums": 0,
                        "dnfs": 0,
                        "positions": [],
                    },
                )

                # Punkte
                d["points"] += float(row["Points"])

                # Position -> wins/podiums/avg
                pos = row.get("Position")
                if pd.notna(pos):
                    ipos = int(pos)
                    d["positions"].append(ipos)
                    if ipos == 1:
                        d["wins"] += 1
                    if ipos <= 3:
                        d["podiums"] += 1

                # DNF via Status
                status = (row.get("Status") or "").strip()
                if status and status not in ("Finished", "") and not str(status).startswith("+"):
                    d["dnfs"] += 1

        # 3) Finalisieren (nur native Python-Typen)
        out: Dict[str, Any] = {}
        for code, d in results_by_driver.items():
            positions = d["positions"]
            avg = float(pd.Series(positions).mean()) if positions else None
            out[code] = {
                "name": str(d["name"]) if d["name"] else code,
                "team": (str(d["team"]) if d["team"] else None),
                "total_points": float(d["points"]),
                "wins": int(d["wins"]),
                "podiums": int(d["podiums"]),
                "dnfs": int(d["dnfs"]),
                "avg_finish": (float(avg) if avg is not None else None),
                "poles": 0,
            }

        payload = {"season": year, "drivers": out}

        # 4) Cache speichern & Header setzen
        _save_to_cache(year, payload)
        response.headers["Cache-Control"] = "public, max-age=86400"

        return payload

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
