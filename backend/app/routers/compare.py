from fastapi import APIRouter, HTTPException, Response
import fastf1
import pandas as pd
from typing import Dict, Any, Tuple
from app.services.f1_utils import load_results_strict  # deine robuste Loader-Funktion
import os
from pathlib import Path
import json

router = APIRouter(prefix="/f1", tags=["fastf1"])

# ---- Cache (nur hier einmal) -------------------------------------------------
default_cache = "C:/Users/claud/.fastf1_cache" if os.name == "nt" else "/data/fastf1_cache"
cache_dir = os.getenv("FASTF1_CACHE", default_cache)
os.makedirs(cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(cache_dir)

# Persistenter JSON-Cache für die gesamte Saison
CACHE_DIR = (Path(__file__).resolve().parent.parent / "season_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _season_cache_path(year: int) -> Path:
    return CACHE_DIR / f"season_{year}.json"

def _load_from_cache(year: int) -> Dict[str, Any] | None:
    p = _season_cache_path(year)
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    return None

def _save_to_cache(year: int, payload: Dict[str, Any]) -> None:
    p = _season_cache_path(year)
    with p.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

# ---- Hilfen für Poles --------------------------------------------------------

def _count_poles_from_grid(df: pd.DataFrame) -> Dict[str, int]:
    """Zähle Poles über GridPosition==1, wenn vorhanden."""
    poles: Dict[str, int] = {}
    if "GridPosition" not in df.columns:
        return poles
    g = pd.to_numeric(df["GridPosition"], errors="coerce")
    mask = g == 1
    if not mask.any():
        return poles
    for _, row in df[mask].iterrows():
        code = row.get("Abbreviation")
        if code and pd.notna(code):
            poles[code] = poles.get(code, 0) + 1
    return poles

def _qualifying_pole_code(year: int, rnd: int) -> str | None:
    """Bestimme Polesetter via Qualifying/Sprint-Shootout (Position==1)."""
    # 1) Klassisches Qualifying
    try:
        with fastf1.Cache.disabled():
            q = fastf1.get_session(year, rnd, "Q", backend="ergast")
            q.load(laps=False, telemetry=False, weather=False, messages=False)
            qres = q.results
        if qres is not None and not qres.empty and "Position" in qres.columns:
            pos = pd.to_numeric(qres["Position"], errors="coerce")
            sub = qres[pos == 1]
            if not sub.empty:
                return sub.iloc[0].get("Abbreviation")
    except Exception:
        pass
    # 2) Sprint-Quali (Sprint Shootout) – falls Wochenenden mit SQ
    try:
        with fastf1.Cache.disabled():
            sq = fastf1.get_session(year, rnd, "SQ", backend="ergast")
            sq.load(laps=False, telemetry=False, weather=False, messages=False)
            sqres = sq.results
        if sqres is not None and not sqres.empty and "Position" in sqres.columns:
            pos = pd.to_numeric(sqres["Position"], errors="coerce")
            sub = sqres[pos == 1]
            if not sub.empty:
                return sub.iloc[0].get("Abbreviation")
    except Exception:
        pass
    return None

# ---- Endpoint ----------------------------------------------------------------

@router.get("/season/{year}")
def load_season(year: int, response: Response, refresh: bool = False) -> Dict[str, Any]:
    """
    Aggregiert pro Fahrer:
      total_points, wins, podiums, dnfs, avg_finish, poles

    - nutzt load_results_strict (fastf1 -> ergast -> derived)
    - persistenter JSON-Cache
    - Poles: GridPosition==1; Fallback: Quali/SQ Position==1
    """
    try:
        if not refresh:
            cached = _load_from_cache(year)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=86400"
                return cached

        schedule = fastf1.get_event_schedule(year, include_testing=False)
        results_by_driver: Dict[str, Dict[str, Any]] = {}

        for _, ev in schedule.iterrows():
            rnd = ev.get("RoundNumber")
            if pd.isna(rnd) or int(rnd) <= 0:
                continue
            rnd = int(rnd)

            # Race-Results (robust)
            try:
                _, df = load_results_strict(year, rnd)
            except Exception:
                continue
            if df is None or df.empty:
                continue

            # Normalisieren
            for need in ("Points", "Position"):
                if need not in df.columns:
                    df[need] = pd.NA
            if "GridPosition" not in df.columns:
                df["GridPosition"] = pd.NA

            df["Points"] = pd.to_numeric(df["Points"], errors="coerce").fillna(0.0)
            df["Position"] = pd.to_numeric(df["Position"], errors="coerce")
            df["GridPosition"] = pd.to_numeric(df["GridPosition"], errors="coerce")

            # Erstmal Poles aus Grid
            poles_this_round = _count_poles_from_grid(df)
            # Falls keiner ermittelt: Qualifying/SQ holen
            if not poles_this_round:
                pole_code = _qualifying_pole_code(year, rnd)
                if pole_code:
                    poles_this_round = {pole_code: 1}

            # Aggregation pro Fahrer
            for _, row in df.iterrows():
                code = row.get("Abbreviation")
                if not code or pd.isna(code):
                    continue
                d = results_by_driver.setdefault(code, {
                    "name": row.get("FullName") or row.get("BroadcastName") or code,
                    "team": row.get("TeamName"),
                    "points": 0.0,
                    "wins": 0,
                    "podiums": 0,
                    "dnfs": 0,
                    "positions": [],
                    "poles": 0,
                })

                d["points"] += float(row["Points"])

                pos = row.get("Position")
                if pd.notna(pos):
                    ipos = int(pos)
                    d["positions"].append(ipos)
                    if ipos == 1:
                        d["wins"] += 1
                    if ipos <= 3:
                        d["podiums"] += 1

                status = (row.get("Status") or "").strip()
                if status and status not in ("Finished", "") and not str(status).startswith("+"):
                    d["dnfs"] += 1

            # Poles dieser Runde addieren
            for code, inc in poles_this_round.items():
                if code in results_by_driver:
                    results_by_driver[code]["poles"] += int(inc)

        # Finalisieren
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
                "poles": int(d["poles"]),
            }
        payload = {"season": year, "drivers": out}
        _save_to_cache(year, payload)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return payload

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
