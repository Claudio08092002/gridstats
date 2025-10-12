from __future__ import annotations

import os
from typing import Any, Dict, List

import fastf1
import re
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastf1.ergast import interface as ergast_interface
from fastf1.core import DataNotLoadedError

from app.services.f1_utils import load_results_strict, get_session_prefer_fastf1

router = APIRouter(prefix="/f1", tags=["race-stats"])

_DEFAULT_FASTF1_CACHE = "C:/Users/claud/.fastf1_cache" if os.name == "nt" else "/data/fastf1_cache"
_cache_dir = os.getenv("FASTF1_CACHE", _DEFAULT_FASTF1_CACHE)
os.makedirs(_cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(_cache_dir)
from pathlib import Path
import json

# JSON cache dir for race overview payloads
_RACE_CACHE_DIR = Path(__file__).resolve().parent.parent / "race_cache"
_RACE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _race_cache_path(year: int, round_number: int) -> Path:
    return _RACE_CACHE_DIR / f"race_{year}_{round_number}.json"

def _read_json(path: Path):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None

def _write_json(path: Path, payload: dict) -> None:
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

ERGAST_BASE_URL = os.getenv("ERGAST_BASE_URL")
if ERGAST_BASE_URL:
    ergast_interface.BASE_URL = ERGAST_BASE_URL
else:
    ergast_interface.BASE_URL = "https://api.jolpi.ca/ergast/f1"

TEAM_COLOR_FALLBACK = {
    # Current/common
    "MERCEDES": "#00D2BE",
    "FERRARI": "#E80020",
    "RED BULL": "#3671C6",
    "RED BULL RACING": "#3671C6",
    "MCLAREN": "#FF8000",
    "ALPINE": "#0090FF",
    "ASTON MARTIN": "#00665F",
    "WILLIAMS": "#005AFF",
    "HAAS": "#FFFFFF",
    # 2024/2025 naming
    "RB": "#6692FF",  # Visa Cash App RB
    "RACING BULLS": "#6692FF",
    "KICK SAUBER": "#00E100",  # Stake F1 Team Kick Sauber
    "SAUBER": "#00E100",
    # Historic/alternate
    "ALPHATAURI": "#469BFF",
    "ALPHA TAURI": "#469BFF",
    "ALFA ROMEO": "#9B0000",
}

def _to_ms(v: Any) -> int | None:
    if pd.isna(v) or v is None:
        return None
    if isinstance(v, pd.Timedelta):
        return int(v.total_seconds() * 1000)
    try:
        td = pd.to_timedelta(v)
        return int(td.total_seconds() * 1000)
    except Exception:
        return None


@router.get("/race/{year}/{round}")
def race_overview(year: int, round: int, refresh: bool = Query(False)) -> Dict[str, Any]:  # pragma: no cover - fastf1 dependent
    # Try cache first
    cache_path = _race_cache_path(year, round)
    if not refresh:
        cached = _read_json(cache_path)
        if isinstance(cached, dict) and cached.get("year") == year and cached.get("round") == round:
            return cached
    # Load race session and laps
    try:
        ses = get_session_prefer_fastf1(year, round, "R")
        ses.load(laps=True, telemetry=False, weather=False, messages=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load race session: {exc}")

    # Laps can sometimes be unavailable even after load; guard and retry once
    try:
        laps = ses.laps
    except DataNotLoadedError:
        try:
            ses.load(laps=True, telemetry=False, weather=False, messages=False)
            laps = ses.laps
        except Exception:
            laps = pd.DataFrame(columns=["Driver", "LapNumber", "LapTime", "Position"])  # empty fallback
    if laps is None or (hasattr(laps, "empty") and laps.empty):
        # Fallback: try Ergast backend for lap times (works well for older seasons)
        try:
            ses_er = fastf1.get_session(year, round, "R", backend="ergast")
            ses_er.load(laps=True, telemetry=False, weather=False, messages=False)
            elaps = getattr(ses_er, "laps", None)
            if elaps is not None and not elaps.empty:
                laps = elaps
        except Exception:
            pass
    if laps is None or (hasattr(laps, "empty") and laps.empty):
        laps = pd.DataFrame(columns=["Driver", "LapNumber", "LapTime", "Position"])  # empty fallback

    # Classification via robust utility (merges F1+Ergast as needed, includes DNF)
    src, results = load_results_strict(year, round)
    if results is None or results.empty:
        raise HTTPException(status_code=404, detail="No race results available")

    # Event meta
    event_name = None
    location = None
    country = None
    date_iso = None
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        if schedule is not None and not schedule.empty and "RoundNumber" in schedule.columns:
            row = schedule.loc[pd.to_numeric(schedule["RoundNumber"], errors="coerce") == round]
            if not row.empty:
                r0 = row.iloc[0]
                event_name = str(r0.get("EventName") or r0.get("OfficialEventName") or "") or None
                location = str(r0.get("Location") or "") or None
                country = str(r0.get("Country") or "") or None
                date_iso = None
                dt = r0.get("EventDate")
                if pd.notna(dt):
                    try:
                        date_iso = pd.to_datetime(dt).isoformat()
                    except Exception:
                        date_iso = None
    except Exception:
        pass
    # Fallback to session event
    try:
        ev = getattr(ses, "event", None)
        if ev is not None:
            event_name = event_name or getattr(ev, "EventName", None) or getattr(ev, "Name", None)
            location = location or getattr(ev, "Location", None)
            country = country or getattr(ev, "Country", None)
            if not date_iso and getattr(ev, "EventDate", None) is not None:
                try:
                    date_iso = pd.to_datetime(getattr(ev, "EventDate")).isoformat()
                except Exception:
                    pass
    except Exception:
        pass

    # Basic meta: laps & duration
    total_laps = 0
    duration_ms = None
    if not laps.empty:
        laps["LapNumber"] = pd.to_numeric(laps.get("LapNumber"), errors="coerce").fillna(0).astype(int)
        total_laps = int(laps["LapNumber"].max()) if not laps["LapNumber"].empty else 0
        # Duration: max(LapStartTime + LapTime)
        try:
            st = pd.to_timedelta(laps.get("LapStartTime")) if "LapStartTime" in laps.columns else None
            lt = pd.to_timedelta(laps.get("LapTime")) if "LapTime" in laps.columns else None
            if st is not None and lt is not None:
                finish = (st + lt).max()
            else:
                finish = pd.to_timedelta(laps.get("LapTime")).cumsum().max() if "LapTime" in laps.columns else None
            duration_ms = _to_ms(finish)
        except Exception:
            duration_ms = None
    # Fallback total laps from classification if lap data didn't yield a value
    if (not total_laps) and results is not None and not results.empty:
        try:
            laps_col = pd.to_numeric(results.get("Laps"), errors="coerce") if "Laps" in results.columns else None
            mx = int(laps_col.max()) if laps_col is not None and laps_col.notna().any() else 0
            if mx > 0:
                total_laps = mx
        except Exception:
            pass

    # Retirements
    retirements = 0
    if "DNF" in results.columns:
        retirements = int(pd.to_numeric(results["DNF"], errors="coerce").fillna(0).astype(bool).sum())
    else:
        # Fallback from Status
        statuses = results.get("Status")
        if statuses is not None:
            s = statuses.astype(str).str.lower()
            retirements = int((~s.str.contains("finish")).sum())

    # Fastest lap
    fastest = None
    try:
        fl = laps.pick_fastest()
        if fl is not None:
            fastest = {
                "driver": getattr(fl, "Driver", None),
                "lap": int(getattr(fl, "LapNumber", 0) or 0),
                "lap_time_ms": _to_ms(getattr(fl, "LapTime", None)),
            }
    except Exception:
        pass

    # Classification payload
    def norm_hex(v: Any) -> str | None:
        if v is None or pd.isna(v):
            return None
        s = str(v).strip()
        if not s:
            return None
        if not s.startswith("#"):
            s = f"#{s}"
        if len(s) == 4:
            s = "#" + "".join(ch * 2 for ch in s[1:])
        return s.upper() if len(s) == 7 else None

    def fallback_color(team: Any, cur: Any) -> str | None:
        # prefer explicit provided color if valid
        col = norm_hex(cur)
        if col:
            return col
        # heuristic mapping by team name substrings
        name = str(team or '').upper()
        if not name:
            return None
        if 'MERCEDES' in name:
            return TEAM_COLOR_FALLBACK.get('MERCEDES')
        if 'FERRARI' in name:
            return TEAM_COLOR_FALLBACK.get('FERRARI')
        if 'RED BULL' in name:
            return TEAM_COLOR_FALLBACK.get('RED BULL')
        if 'MCLAREN' in name:
            return TEAM_COLOR_FALLBACK.get('MCLAREN')
        if 'ALPINE' in name or 'RENAULT' in name:
            return TEAM_COLOR_FALLBACK.get('ALPINE')
        if 'ASTON MARTIN' in name or 'RACING POINT' in name:
            return TEAM_COLOR_FALLBACK.get('ASTON MARTIN')
        if 'WILLIAMS' in name:
            return TEAM_COLOR_FALLBACK.get('WILLIAMS')
        if 'HAAS' in name:
            return TEAM_COLOR_FALLBACK.get('HAAS')
        if 'ALPHATAURI' in name or 'ALPHA TAURI' in name:
            return TEAM_COLOR_FALLBACK.get('ALPHATAURI')
        if 'ALFA ROMEO' in name:
            return TEAM_COLOR_FALLBACK.get('ALFA ROMEO')
        if 'SAUBER' in name or 'KICK SAUBER' in name or 'STAKE' in name:
            return TEAM_COLOR_FALLBACK.get('KICK SAUBER')
        if name == 'RB' or ' RACING BULLS' in name:
            return TEAM_COLOR_FALLBACK.get('RB')
        # try exact fallback last
        return TEAM_COLOR_FALLBACK.get(name)

    results = results.copy()
    results["Position"] = pd.to_numeric(results.get("Position"), errors="coerce")
    results["GridPosition"] = pd.to_numeric(results.get("GridPosition"), errors="coerce")

    def simplify_status(raw: Any, dnf: bool) -> str | None:
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return "Retired" if dnf else "Finished"
        s = str(raw).strip().lower()
        if not s:
            return "Retired" if dnf else "Finished"
        if any(k in s for k in ["disqual", "excluded"]):
            return "DSQ"
        if "did not start" in s or s == "dns":
            return "DNS"
        if any(k in s for k in ["retired", "accident", "collision", "engine", "gearbox", "hydraulic", "electrical", "oil", "water", "brake", "suspension", "power unit"]):
            return "DNF"
        if "not classified" in s or s == "nc":
            return "NC"
        if "finished" in s or "lapped" in s or "+" in s:  # e.g., +1 Lap
            return "Finished"
        return "Finished" if not dnf else "DNF"

    classification: List[Dict[str, Any]] = []
    for _, row in results.sort_values("Position", na_position="last").iterrows():
        pos = row.get("Position")
        abbr = row.get("Abbreviation") or row.get("Driver")
        team = row.get("TeamName") or row.get("ConstructorName")
        grid = row.get("GridPosition")
        time_text = row.get("Time")
        status = row.get("Status")
        pts = row.get("Points")
        dnf = bool(row.get("DNF", False))
        team_color = fallback_color(team, row.get("TeamColor"))
        delta = None
        try:
            if pd.notna(grid) and pd.notna(pos):
                delta = int(grid) - int(pos)
        except Exception:
            delta = None
        classification.append({
            "position": int(pos) if pd.notna(pos) else None,
            "driver": str(abbr) if abbr is not None else None,
            "team": str(team) if team is not None else None,
            "grid": int(grid) if pd.notna(grid) else None,
            "grid_delta": delta,
            "time": str(time_text) if (time_text is not None and not pd.isna(time_text)) else None,
            "status": str(status) if status is not None else None,
            "status_simple": simplify_status(status, dnf),
            "points": float(pts) if pd.notna(pts) else 0.0,
            "dnf": dnf,
            "team_color": team_color,
        })

    # Position by lap series
    pos_series: List[Dict[str, Any]] = []
    if not laps.empty:
        laps2 = laps.copy()
        laps2["Position"] = pd.to_numeric(laps2.get("Position"), errors="coerce")
        laps2 = laps2.dropna(subset=["Position", "LapNumber", "Driver"])  # keep only valid
        # Build mapping helpers
        color_map: Dict[str, str | None] = {}
        if not results.empty:
            tmp = results.dropna(subset=["Abbreviation"]).drop_duplicates("Abbreviation")
            for _, r in tmp.iterrows():
                ab = r.get("Abbreviation") or r.get("Driver")
                tname = r.get("TeamName") or r.get("ConstructorName")
                color_map[str(ab)] = fallback_color(tname, r.get("TeamColor"))
        # Build driver mapping helpers: Driver -> Abbreviation, DriverNumber -> Abbreviation
        name_to_abbr: Dict[str, str] = {}
        try:
            if "Driver" in results.columns and "Abbreviation" in results.columns:
                for _, r in results.dropna(subset=["Driver"]).iterrows():
                    name_to_abbr[str(r.get("Driver"))] = str(r.get("Abbreviation") or r.get("Driver") or "")
        except Exception:
            pass

        # Map DriverNumber -> Abbreviation as fallback
        num_to_abbr: Dict[int, str] = {}
        try:
            if "DriverNumber" in results.columns:
                for _, r in results.dropna(subset=["DriverNumber"]).iterrows():
                    try:
                        num_to_abbr[int(r.get("DriverNumber"))] = str(r.get("Abbreviation") or r.get("Driver") or "")
                    except Exception:
                        pass
        except Exception:
            pass

        for drv, df in laps2.groupby("Driver"):
            df = df.sort_values("LapNumber")
            samples = [{"lap": int(ln), "position": int(p)} for ln, p in zip(df["LapNumber"], df["Position"]) if pd.notna(p)]
            team = None
            try:
                team = df.get("Team").dropna().iloc[-1]
            except Exception:
                team = None
            # Ensure driver code is a proper 3-letter abbreviation
            drv_code = str(drv)
            if not drv_code or len(drv_code) > 3:
                try:
                    num = int(df.get("DriverNumber").dropna().iloc[-1]) if "DriverNumber" in df.columns else None
                    if num is not None and num in num_to_abbr:
                        drv_code = num_to_abbr[num]
                except Exception:
                    pass
            # Try mapping by driver name to abbreviation
            if (not drv_code or len(drv_code) != 3) and name_to_abbr:
                drv_code = name_to_abbr.get(str(drv), drv_code)
            # Grid and final classified position
            grid_pos = None
            final_pos = None
            if not results.empty and "Abbreviation" in results.columns:
                try:
                    row = results.loc[results["Abbreviation"] == drv_code]
                    if not row.empty:
                        if "Position" in results.columns:
                            val = pd.to_numeric(row.iloc[0].get("Position"), errors="coerce")
                            final_pos = int(val) if pd.notna(val) else None
                        if "GridPosition" in results.columns:
                            gval = pd.to_numeric(row.iloc[0].get("GridPosition"), errors="coerce")
                            grid_pos = int(gval) if pd.notna(gval) else None
                except Exception:
                    final_pos = final_pos
            # Prepend lap 0 with grid position to reflect start order
            if grid_pos is not None:
                samples = ([{"lap": 0, "position": int(grid_pos)}] + samples)
            pos_series.append({
                "driver": drv_code,
                "team": str(team) if team is not None else None,
                "team_color": color_map.get(drv_code) or color_map.get(str(drv)),
                "laps": samples,
                "final_position": final_pos,
                "grid_position": grid_pos,
            })

    # Fallback: if no lap position series could be built, synthesize from grid -> finish
    if not pos_series and isinstance(results, pd.DataFrame) and not results.empty:
        total_laps = int(total_laps or 0)
        for _, row in results.iterrows():
            drv_code = str(row.get("Abbreviation") or row.get("Driver") or "")
            if not drv_code:
                continue
            grid_pos = row.get("GridPosition")
            final_pos = row.get("Position")
            try:
                grid_i = int(pd.to_numeric(grid_pos, errors="coerce")) if grid_pos is not None else None
            except Exception:
                grid_i = None
            try:
                fin_i = int(pd.to_numeric(final_pos, errors="coerce")) if final_pos is not None else None
            except Exception:
                fin_i = None
            samples = []
            if grid_i is not None:
                samples.append({"lap": 0, "position": grid_i})
            if fin_i is not None:
                samples.append({"lap": max(1, total_laps), "position": fin_i})
            tname = row.get("TeamName") or row.get("ConstructorName")
            tcolor = fallback_color(tname, row.get("TeamColor"))
            pos_series.append({
                "driver": drv_code,
                "team": str(tname) if tname is not None else None,
                "team_color": tcolor,
                "laps": samples,
                "final_position": fin_i,
                "grid_position": grid_i,
            })

    # Team pace ranking + boxplot stats (quick laps)
    team_pace: List[Dict[str, Any]] = []
    team_box: List[Dict[str, Any]] = []
    try:
        # Follow fastf1 doc more closely: prefer removing in/out box laps, then take quick laps
        base = laps
        if hasattr(laps, "pick_wo_box"):
            tmp = laps.pick_wo_box()
            if tmp is not None and not tmp.empty:
                base = tmp
        quick = base
        if hasattr(base, "pick_quicklaps"):
            tmp = base.pick_quicklaps()
            if tmp is not None and not tmp.empty:
                quick = tmp
            else:
                # fallback: use base without quick filter if quicklaps empty (e.g., missing LapTime)
                quick = base
        if quick is not None and not quick.empty:
            # keep all rows; we'll reconstruct LapTimeMs where missing
            quick = quick.copy()
            # trust only accurate timing if available
            if "IsAccurate" in quick.columns:
                try:
                    quick = quick.loc[quick["IsAccurate"] != False]
                except Exception:
                    pass
            # Ensure team info - support various Driver identifiers (abbr, name, number)
            if "Team" not in quick.columns and "TeamName" in results.columns:
                maps: Dict[str, Dict[Any, Any]] = {}
                if "Abbreviation" in results.columns:
                    maps["abbr"] = results.dropna(subset=["Abbreviation"]).set_index("Abbreviation")["TeamName"].to_dict()
                if "Driver" in results.columns:
                    maps["name"] = results.dropna(subset=["Driver"]).set_index("Driver")["TeamName"].to_dict()
                if "DriverNumber" in results.columns and "DriverNumber" in quick.columns:
                    maps["num"] = results.dropna(subset=["DriverNumber"]).set_index("DriverNumber")["TeamName"].to_dict()
                # Try to map by abbr from quick.Driver; then by full name; then by number
                team_series = None
                if "Driver" in quick.columns and "abbr" in maps:
                    team_series = quick["Driver"].map(maps["abbr"])  # type: ignore
                if team_series is None or team_series.isna().all():
                    if "Driver" in quick.columns and "name" in maps:
                        team_series = quick["Driver"].map(maps["name"])  # type: ignore
                if (team_series is None or team_series.isna().all()) and ("DriverNumber" in quick.columns and "num" in maps):
                    num_coerced = pd.to_numeric(quick.get("DriverNumber"), errors="coerce")
                    team_series = num_coerced.map(maps["num"])  # type: ignore
                if team_series is not None:
                    quick["Team"] = team_series
            # Colors map by team from results
            tcolor = {}
            if "TeamName" in results.columns and "TeamColor" in results.columns:
                base = results.dropna(subset=["TeamName"]).drop_duplicates("TeamName").set_index("TeamName")["TeamColor"].to_dict()
                tcolor = {team: fallback_color(team, col) for team, col in base.items()}

            # Use numeric milliseconds for robust stats
            def _lap_to_ms(val: Any) -> int | None:
                # Robust conversion: handle Timedelta, numeric seconds, strings like '1:34.867', '94.867', etc.
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return None
                # Timedelta typed values
                if isinstance(val, pd.Timedelta):
                    return int(val.total_seconds() * 1000)
                # Numeric values: interpret as seconds
                if isinstance(val, (int, float)):
                    try:
                        return int(float(val) * 1000)
                    except Exception:
                        pass
                # Strings: parse mm:ss.mmm or ss.mmm
                s = str(val).strip()
                # pandas parsing for ISO-like strings
                try:
                    td = pd.to_timedelta(s)
                    if pd.notna(td) and isinstance(td, pd.Timedelta):
                        return int(td.total_seconds() * 1000)
                except Exception:
                    pass
                m = re.match(r"^(?:(\d+):)?(\d+)(?:\.(\d+))?$", s)
                if m:
                    minutes = int(m.group(1) or 0)
                    seconds = int(m.group(2) or 0)
                    millis = int((m.group(3) or "0").ljust(3, "0")[:3])
                    return (minutes * 60 + seconds) * 1000 + millis
                return None

            quick_ms = quick.copy()
            # Primary conversion from LapTime
            quick_ms["LapTimeMs"] = quick_ms["LapTime"].apply(_lap_to_ms)
            # Fallback 1: sector sum
            if {"Sector1Time", "Sector2Time", "Sector3Time"}.issubset(set(quick_ms.columns)):
                def _sec_sum(row: pd.Series) -> int | None:
                    t1 = _lap_to_ms(row.get("Sector1Time"))
                    t2 = _lap_to_ms(row.get("Sector2Time"))
                    t3 = _lap_to_ms(row.get("Sector3Time"))
                    if t1 is None or t2 is None or t3 is None:
                        return None
                    return int(t1 + t2 + t3)
                mask = quick_ms["LapTimeMs"].isna() | (pd.to_numeric(quick_ms["LapTimeMs"], errors="coerce") <= 0)
                if mask.any():
                    sec_vals = quick_ms.apply(_sec_sum, axis=1)
                    quick_ms.loc[mask, "LapTimeMs"] = sec_vals[mask]
            # Fallback 2: start-time differences
            if "LapStartTime" in quick_ms.columns:
                lst = pd.to_timedelta(quick_ms.get("LapStartTime"), errors="coerce")
                next_lst = lst.shift(-1)
                diffs = (next_lst - lst).dt.total_seconds() * 1000
                mask = quick_ms["LapTimeMs"].isna() | (pd.to_numeric(quick_ms["LapTimeMs"], errors="coerce") <= 0)
                if mask.any():
                    quick_ms.loc[mask, "LapTimeMs"] = diffs[mask]
            # Final clean
            quick_ms["LapTimeMs"] = pd.to_numeric(quick_ms["LapTimeMs"], errors="coerce")
            quick_ms = quick_ms.dropna(subset=["LapTimeMs"])  # ensure numeric

            grp = quick_ms.groupby("Team")["LapTimeMs"]
            med = grp.median().sort_values()
            p25 = grp.quantile(0.25)
            cnt = grp.count()
            for team_name, median_td in med.items():
                if pd.isna(team_name):
                    continue
                team_pace.append({
                    "team": str(team_name),
                    "team_color": tcolor.get(team_name),
                    "median_ms": int(median_td) if pd.notna(median_td) else None,
                    "p25_ms": int(p25.get(team_name)) if pd.notna(p25.get(team_name)) else None,
                    "count": int(cnt.get(team_name) or 0),
                })

            # Boxplot stats
            desc = grp.describe(percentiles=[0.25, 0.5, 0.75])
            # desc columns: count, mean, std, min, 25%, 50%, 75%, max
            for team_name, row in desc.iterrows():
                if pd.isna(team_name):
                    continue
                team_box.append({
                    "team": str(team_name),
                    "team_color": tcolor.get(team_name),
                    "min_ms": int(row.get("min")) if pd.notna(row.get("min")) else None,
                    "q1_ms": int(row.get("25%")) if pd.notna(row.get("25%")) else None,
                    "median_ms": int(row.get("50%")) if pd.notna(row.get("50%")) else None,
                    "q3_ms": int(row.get("75%")) if pd.notna(row.get("75%")) else None,
                    "max_ms": int(row.get("max")) if pd.notna(row.get("max")) else None,
                    "count": int(row.get("count") or 0),
                })
    except Exception:
        team_pace = []
        team_box = []

    payload: Dict[str, Any] = {
        "year": year,
        "round": round,
        "event": {
            "name": event_name,
            "location": location,
            "country": country,
            "date": date_iso,
            "source": src,
        },
        "meta": {
            "total_laps": total_laps,
            "duration_ms": duration_ms,
            "retirements": retirements,
            "fastest_lap": fastest,
        },
        "classification": classification,
        "position_by_lap": {"drivers": pos_series},
        "team_pace": team_pace,
        "team_box": team_box,
    }

    _write_json(cache_path, payload)
    return payload
