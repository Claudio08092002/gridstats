from __future__ import annotations

import os
from typing import Any, Dict, List

import fastf1
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastf1.ergast import interface as ergast_interface
from fastf1.core import DataNotLoadedError

from app.services.f1_utils import load_results_strict, get_session_prefer_fastf1

router = APIRouter(prefix="/f1", tags=["race-driver"])

_DEFAULT_FASTF1_CACHE = "C:/Users/claud/.fastf1_cache" if os.name == "nt" else "/data/fastf1_cache"
_cache_dir = os.getenv("FASTF1_CACHE", _DEFAULT_FASTF1_CACHE)
os.makedirs(_cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(_cache_dir)

ERGAST_BASE_URL = os.getenv("ERGAST_BASE_URL")
if ERGAST_BASE_URL:
    ergast_interface.BASE_URL = ERGAST_BASE_URL
else:
    ergast_interface.BASE_URL = "https://api.jolpi.ca/ergast/f1"

from pathlib import Path
import json

_DRV_CACHE_DIR = Path(__file__).resolve().parent.parent / "driver_race_cache"
_DRV_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _drv_race_path(year: int, round_number: int) -> Path:
    # Aggregate all drivers per race in a single file
    return _DRV_CACHE_DIR / f"race_{year}_{round_number}.json"

def _read_json(path: Path):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None
    return None

def _write_json(path: Path, payload: dict) -> None:
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


# Fallback team colors for key teams
TEAM_COLOR_FALLBACK = {
    "MERCEDES": "#00D2BE",
    "FERRARI": "#E80020",
    "RED BULL": "#3671C6",
    "RED BULL RACING": "#3671C6",
    "MCLAREN": "#FF8000",
    "ALPINE": "#0090FF",
    "ASTON MARTIN": "#00665F",
    "WILLIAMS": "#005AFF",
    "HAAS": "#FFFFFF",
    "RB": "#6692FF",
    "KICK SAUBER": "#00E100",
}

def _norm_hex(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s:
        return None
    if not s.startswith('#'):
        s = f'#{s}'
    if len(s) == 4:
        s = '#' + ''.join(ch*2 for ch in s[1:])
    return s.upper() if len(s) == 7 else None

def _fallback_team_color(team: Any, current: Any) -> str | None:
    col = _norm_hex(current)
    if col:
        return col
    name = str(team or '').upper()
    # Basic normalization
    if 'MERCEDES' in name:
        name = 'MERCEDES'
    return TEAM_COLOR_FALLBACK.get(name)

def _to_ms(v: Any) -> int | None:
    # Robust conversion: Timedelta, numeric seconds, or strings like '1:34.567'
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timedelta):
        return int(v.total_seconds() * 1000)
    if isinstance(v, (int, float)):
        try:
            return int(float(v) * 1000)
        except Exception:
            return None
    s = str(v).strip()
    if not s:
        return None
    # Try pandas parsing first for timedelta-like strings
    try:
        td = pd.to_timedelta(s)
        if pd.notna(td):
            return int(td.total_seconds() * 1000)
    except Exception:
        pass
    # Parse mm:ss.mmm or ss.mmm
    import re
    m = re.match(r"^(?:(\d+):)?(\d+)(?:\.(\d+))?$", s)
    if m:
        minutes = int(m.group(1) or 0)
        seconds = int(m.group(2) or 0)
        millis = int((m.group(3) or "0").ljust(3, "0")[:3])
        return (minutes * 60 + seconds) * 1000 + millis
    return None


@router.get("/race/{year}/{round}/driver/{code}")
def race_driver_details(year: int, round: int, code: str, refresh: bool = Query(False)) -> Dict[str, Any]:  # pragma: no cover - fastf1 dependent
    # Try aggregated cache: driver_race_cache/race_{year}_{round}.json
    agg_path = _drv_race_path(year, round)
    code_up = (code or '').strip().upper()
    if not refresh:
        cached_doc = _read_json(agg_path)
        if isinstance(cached_doc, dict) and cached_doc.get('year') == year and cached_doc.get('round') == round:
            drivers_map = cached_doc.get('drivers') or {}
            if isinstance(drivers_map, dict) and code_up in drivers_map:
                return drivers_map[code_up]
    try:
        ses = get_session_prefer_fastf1(year, round, "R")
        ses.load(laps=True, telemetry=False, weather=False, messages=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load race session: {exc}")

    # Results for meta
    _, results = load_results_strict(year, round)
    if results is None or results.empty:
        raise HTTPException(status_code=404, detail="No race results available")

    res_row = None
    try:
        res_row = results.loc[results["Abbreviation"] == code].iloc[0]
    except Exception:
        # fall back to Driver match
        try:
            res_row = results.loc[results["Driver"] == code].iloc[0]
        except Exception:
            res_row = None

    team = str(res_row.get("TeamName") or res_row.get("ConstructorName") or "") if res_row is not None else None
    team_color = _fallback_team_color(team, res_row.get("TeamColor") if res_row is not None else None)
    grid = int(res_row.get("GridPosition")) if (res_row is not None and pd.notna(res_row.get("GridPosition"))) else None
    finish = int(res_row.get("Position")) if (res_row is not None and pd.notna(res_row.get("Position"))) else None
    status = str(res_row.get("Status")) if res_row is not None else None

    # Laps (guard against intermittent DataNotLoadedError on older sessions)
    try:
        laps = ses.laps
    except DataNotLoadedError:
        try:
            ses.load(laps=True, telemetry=False, weather=False, messages=False)
            laps = ses.laps
        except Exception:
            laps = None
    if laps is None or (hasattr(laps, "empty") and laps.empty):
        # Ergast fallback for lap times in older seasons
        try:
            ses_er = fastf1.get_session(year, round, "R", backend="ergast")
            ses_er.load(laps=True, telemetry=False, weather=False, messages=False)
            elaps = getattr(ses_er, "laps", None)
            if elaps is not None and not elaps.empty:
                laps = elaps
        except Exception:
            pass
    if laps is None or (hasattr(laps, "empty") and laps.empty):
        # Gracefully return minimal payload when laps can't be loaded
        _payload_min = {
            "year": year,
            "round": round,
            "driver": code,
            "team": team,
            "team_color": team_color,
            "grid": grid,
            "finish": finish,
            "status": status,
            "pits": [],
            "stints": [],
            "laps": [],
        }
        try:
            doc = _read_json(agg_path) or {"year": year, "round": round, "drivers": {}}
            if not isinstance(doc.get('drivers'), dict):
                doc['drivers'] = {}
            doc['drivers'][code_up] = _payload_min
            _write_json(agg_path, doc)
        except Exception:
            pass
        return _payload_min
    driver_laps = laps.loc[laps["Driver"] == code].copy()
    driver_laps.sort_values("LapNumber", inplace=True)

    # Pit stops
    pits: List[Dict[str, Any]] = []
    if "PitInTime" in driver_laps.columns or "PitOutTime" in driver_laps.columns:
        for _, r in driver_laps.iterrows():
            pin = r.get("PitInTime")
            pout = r.get("PitOutTime")
            if pd.isna(pin) and pd.isna(pout):
                continue
            # Try to find stationary/tyre-change time if present in data
            stationary = None
            for cand in (r.get('PitStopTime'), r.get('PitStopDuration'), r.get('Stationary'), r.get('PitDuration')):
                if cand is not None and not (isinstance(cand, float) and pd.isna(cand)):
                    try:
                        td = pd.to_timedelta(cand)
                        stationary = int(td.total_seconds() * 1000)
                        break
                    except Exception:
                        try:
                            stationary = int(float(str(cand)) * 1000)
                            break
                        except Exception:
                            pass
            pits.append({
                "lap": int(r.get("LapNumber") or 0),
                "pit_in_time_ms": _to_ms(pin),
                "pit_out_time_ms": _to_ms(pout),
                "duration_ms": _to_ms(pd.to_timedelta(pout) - pd.to_timedelta(pin)) if (pd.notna(pin) and pd.notna(pout)) else None,
                "stationary_ms": stationary,
            })

    # Stints
    stints: List[Dict[str, Any]] = []
    if "Stint" in driver_laps.columns:
        for stint_id, g in driver_laps.groupby("Stint"):
            g = g.sort_values("LapNumber")
            comp = g.get("Compound").dropna().iloc[0] if "Compound" in g.columns and not g.get("Compound").dropna().empty else None
            fresh = bool(g.get("FreshTyre").dropna().iloc[0]) if "FreshTyre" in g.columns and not g.get("FreshTyre").dropna().empty else None
            tyre_life_start = int(pd.to_numeric(g.get("TyreLife"), errors="coerce").dropna().iloc[0]) if "TyreLife" in g.columns and not pd.to_numeric(g.get("TyreLife"), errors="coerce").dropna().empty else None
            stints.append({
                "stint": int(stint_id) if pd.notna(stint_id) else None,
                "start_lap": int(g["LapNumber"].min()),
                "end_lap": int(g["LapNumber"].max()),
                "length": int(g["LapNumber"].max()) - int(g["LapNumber"].min()) + 1,
                "compound": str(comp) if comp is not None else None,
                "fresh": fresh,
                "tyre_life_start": tyre_life_start,
            })

    # Derive LapTimeMs and fill gaps if LapTime missing
    driver_laps["LapTimeMs"] = driver_laps.get("LapTime").apply(_to_ms)
    # Fallback 1: sum sector times
    def _sector_sum_ms(row: pd.Series) -> int | None:
        t1 = _to_ms(row.get("Sector1Time"))
        t2 = _to_ms(row.get("Sector2Time"))
        t3 = _to_ms(row.get("Sector3Time"))
        if t1 is None or t2 is None or t3 is None:
            return None
        return int(t1 + t2 + t3)
    if {"Sector1Time", "Sector2Time", "Sector3Time"}.issubset(set(driver_laps.columns)):
        sec_ms = driver_laps.apply(_sector_sum_ms, axis=1)
        mask = driver_laps["LapTimeMs"].isna() | (driver_laps["LapTimeMs"] <= 0)
        driver_laps.loc[mask, "LapTimeMs"] = sec_ms[mask]
    # Fallback 2: next LapStartTime - current LapStartTime
    if "LapStartTime" in driver_laps.columns:
        lst = pd.to_timedelta(driver_laps.get("LapStartTime"), errors="coerce")
        next_lst = lst.shift(-1)
        diff = (next_lst - lst).dt.total_seconds() * 1000
        mask = driver_laps["LapTimeMs"].isna() | (driver_laps["LapTimeMs"] <= 0)
        driver_laps.loc[mask, "LapTimeMs"] = diff[mask]

    # Ensure numeric ints or None
    driver_laps["LapTimeMs"] = pd.to_numeric(driver_laps["LapTimeMs"], errors="coerce")
    driver_laps.loc[~driver_laps["LapTimeMs"].apply(lambda v: pd.notna(v) and float(v) > 0), "LapTimeMs"] = None

    # Laps payload for pace chart
    laps_payload: List[Dict[str, Any]] = []
    for _, r in driver_laps.iterrows():
        laps_payload.append({
            "lap": int(r.get("LapNumber") or 0),
            "lap_time_ms": int(r.get("LapTimeMs")) if pd.notna(r.get("LapTimeMs")) else None,
            "position": int(pd.to_numeric(r.get("Position"), errors="coerce")) if pd.notna(r.get("Position")) else None,
            "compound": str(r.get("Compound")) if r.get("Compound") is not None else None,
            "tyre_life": int(pd.to_numeric(r.get("TyreLife"), errors="coerce")) if pd.notna(r.get("TyreLife")) else None,
            "pit_in": bool(pd.notna(r.get("PitInTime"))) if "PitInTime" in driver_laps.columns else False,
            "pit_out": bool(pd.notna(r.get("PitOutTime"))) if "PitOutTime" in driver_laps.columns else False,
            "is_accurate": bool(r.get("IsAccurate")) if "IsAccurate" in driver_laps.columns else True,
        })

    payload = {
        "year": year,
        "round": round,
        "driver": code,
        "team": team,
        "team_color": team_color,
        "grid": grid,
        "finish": finish,
        "status": status,
        "pits": pits,
        "stints": stints,
        "laps": laps_payload,
    }
    try:
        doc = _read_json(agg_path) or {"year": year, "round": round, "drivers": {}}
        if not isinstance(doc.get('drivers'), dict):
            doc['drivers'] = {}
        doc['drivers'][code_up] = payload
        _write_json(agg_path, doc)
    except Exception:
        pass
    return payload
