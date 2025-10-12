from __future__ import annotations

import json
from typing import Any, Dict, List

import fastf1
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from app.services.f1_utils import load_results_strict
from app.routers import compare as compare_router
from app.routers import race as race_router
from app.routers import race_driver as race_driver_router
from app.routers import track as track_router
from app.services.cache_utils import load_season as cache_load, save_season as cache_save

router = APIRouter(prefix="/f1", tags=["maintenance"])


def _enumerate_rounds(year: int) -> List[int]:
    """Return list of round numbers for a season.
    Tries FastF1 schedule first; if unavailable, probes rounds by results.
    """
    rounds: List[int] = []
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        if schedule is not None and not schedule.empty and "RoundNumber" in schedule.columns:
            sc = schedule.copy()
            sc["RoundNumber"] = pd.to_numeric(sc["RoundNumber"], errors="coerce")
            sc = sc.dropna(subset=["RoundNumber"]).sort_values("RoundNumber")
            rounds = [int(v) for v in sc["RoundNumber"].unique().tolist() if pd.notna(v)]
    except Exception:
        pass
    if rounds:
        return rounds
    misses = 0
    for rnd in range(1, 36):
        try:
            _, df = load_results_strict(year, rnd)
            if df is not None and not df.empty:
                rounds.append(rnd)
                misses = 0
            else:
                misses += 1
        except Exception:
            misses += 1
        if rounds and misses >= 5:
            break
    if not rounds:
        raise HTTPException(status_code=404, detail=f"No rounds found for season {year}")
    return rounds


def _ensure_season(year: int) -> Dict[str, Any]:
    cached = cache_load(compare_router.__file__, year) or {}
    if isinstance(cached, dict) and cached.get("schema_version") == compare_router.SCHEMA_VERSION and cached.get("drivers"):
        return cached
    payload = compare_router._build_season_payload(year)  # type: ignore[attr-defined]
    cache_save(compare_router.__file__, year, payload)
    return payload


@router.get("/cache/warmup/season/{year}")
def warmup_season(year: int) -> Dict[str, Any]:
    payload = _ensure_season(year)
    return {
        "status": "ok",
        "season": year,
        "drivers": len(payload.get("drivers", {})),
        "schema_version": compare_router.SCHEMA_VERSION,
    }


@router.get("/cache/warmup/races/{year}")
def warmup_races(year: int) -> Dict[str, Any]:
    rounds = _enumerate_rounds(year)
    done = 0
    failed: List[int] = []
    for rnd in rounds:
        try:
            race_router.race_overview(year, rnd, refresh=True)  # writes to cache
            done += 1
        except Exception:
            failed.append(rnd)
    return {"status": "ok", "season": year, "rounds": rounds, "cached": done, "failed": failed}


@router.get("/cache/warmup/driver-races/{year}")
def warmup_driver_races(year: int, codes: str | None = Query(None, description="Optional CSV of driver codes to limit")) -> Dict[str, Any]:
    season = _ensure_season(year)
    rounds = _enumerate_rounds(year)
    driver_codes: List[str] = list((season.get("drivers") or {}).keys())
    if codes:
        include = [c.strip().upper() for c in codes.split(',') if c.strip()]
        driver_codes = [c for c in driver_codes if c in include]
    total = 0
    cached = 0
    errors: List[Dict[str, Any]] = []
    for rnd in rounds:
        for code in driver_codes:
            total += 1
            try:
                race_driver_router.race_driver_details(year, rnd, code, refresh=True)  # writes to cache
                cached += 1
            except Exception as exc:
                errors.append({"round": rnd, "code": code, "error": str(exc)})
    return {"status": "ok", "season": year, "rounds": rounds, "drivers": driver_codes, "cached": cached, "total": total, "errors": errors[:10]}


@router.get("/cache/warmup/driver-races")
def warmup_driver_races_range(
    start: int = Query(2018, description="Start season (inclusive)"),
    end: int = Query(2025, description="End season (inclusive)"),
    codes: str | None = Query(None, description="Optional CSV of driver codes to limit (applied per-season)"),
) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"seasons": []}
    total = 0
    cached_total = 0
    for year in range(start, end + 1):
        try:
            season = _ensure_season(year)
        except Exception as exc:
            summary["seasons"].append({"season": year, "error": str(exc)})
            continue
        rounds = _enumerate_rounds(year)
        driver_codes: List[str] = list((season.get("drivers") or {}).keys())
        if codes:
            include = [c.strip().upper() for c in codes.split(',') if c.strip()]
            driver_codes = [c for c in driver_codes if c in include]
        cached = 0
        errs: List[Dict[str, Any]] = []
        for rnd in rounds:
            for code in driver_codes:
                total += 1
                try:
                    race_driver_router.race_driver_details(year, rnd, code, refresh=True)
                    cached += 1
                    cached_total += 1
                except Exception as exc:
                    errs.append({"round": rnd, "code": code, "error": str(exc)})
        summary["seasons"].append({
            "season": year,
            "rounds": rounds,
            "drivers": driver_codes,
            "cached": cached,
            "total": len(rounds) * len(driver_codes),
            "errors": errs[:10],
        })
    summary["summary"] = {"cached": cached_total, "total": total}
    return summary


@router.get("/cache/warmup/tracks")
def warmup_tracks(enhanced: bool = Query(True)) -> Dict[str, Any]:
    return track_router.warmup_all_tracks(enhanced=enhanced)


@router.get("/cache/warmup/all")
def warmup_all(start: int = Query(2018), end: int = Query(2025), drivers: bool = Query(True), tracks: bool = Query(True)) -> Dict[str, Any]:
    seasons = list(range(start, end + 1))
    summary: Dict[str, Any] = {"seasons": []}
    for year in seasons:
        season_info = {"season": year}
        try:
            s = warmup_season(year)
            season_info["season_ok"] = True
            rounds = _enumerate_rounds(year)
            r = warmup_races(year)
            season_info["races"] = r
            if drivers:
                d = warmup_driver_races(year)
                season_info["driver_races"] = {"cached": d.get("cached"), "total": d.get("total")}
        except Exception as exc:
            season_info["error"] = str(exc)
        summary["seasons"].append(season_info)
    if tracks:
        try:
            summary["tracks"] = warmup_tracks()
        except Exception as exc:
            summary["tracks_error"] = str(exc)
    return summary
