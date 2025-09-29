import os
from collections import defaultdict
from pathlib import Path
import pickle
from typing import Any, Dict

import fastf1
from fastf1.ergast import Ergast, interface as ergast_interface
import pandas as pd
from fastapi import APIRouter, HTTPException, Response

from app.services.cache_utils import load_season as cache_load, save_season as cache_save
from app.services.f1_utils import load_results_strict

router = APIRouter(prefix="/f1", tags=["fastf1"])
SCHEMA_VERSION = 11

_DEFAULT_FASTF1_CACHE = "C:/Users/claud/.fastf1_cache" if os.name == "nt" else "/data/fastf1_cache"
_cache_dir = os.getenv("FASTF1_CACHE", _DEFAULT_FASTF1_CACHE)
os.makedirs(_cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(_cache_dir)
ERGAST_BASE_URL = os.getenv("ERGAST_BASE_URL")
if ERGAST_BASE_URL:
    ergast_interface.BASE_URL = ERGAST_BASE_URL
else:
    ergast_interface.BASE_URL = "https://api.jolpi.ca/ergast/f1"

_FINISH_KEYWORDS = {"finished", "finish", "lapped"}
_NON_DNF_EXCLUDE = {"disqualified", "did not start", "excluded"}


def _ensure_abbreviation(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "Abbreviation" in df.columns:
        return df
    if "Driver" in df.columns:
        df["Abbreviation"] = df["Driver"]
        return df
    if "DriverNumber" in df.columns:
        df["Abbreviation"] = df["DriverNumber"].astype(str)
        return df
    df["Abbreviation"] = None
    return df


def _normalize_hex_color(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not text.startswith("#"):
        text = f"#{text}"
    if len(text) == 4:
        text = "#" + "".join(ch * 2 for ch in text[1:])
    if len(text) != 7:
        return None
    return text.upper()


def _fallback_grid_positions(year: int, rnd: int) -> Dict[str, int]:
    try:
        session = fastf1.get_session(year, rnd, "Q", backend="fastf1")
        session.load(laps=False, telemetry=False, weather=False, messages=False)
    except Exception:
        return {}

    results = session.results
    if results is None or results.empty:
        return {}

    qdf = _ensure_abbreviation(results)
    if "Position" not in qdf.columns:
        return {}

    qdf["Position"] = pd.to_numeric(qdf["Position"], errors="coerce")
    qdf = qdf.dropna(subset=["Position", "Abbreviation"])

    fallback: Dict[str, int] = {}
    for _, row in qdf.iterrows():
        code = row.get("Abbreviation")
        pos = row.get("Position")
        if pd.notna(code) and pd.notna(pos):
            fallback[str(code).upper()] = int(pos)
    return fallback


def _load_extended_grid_positions(year: int, rnd: int) -> Dict[str, int]:
    try:
        session = fastf1.get_session(year, rnd, "R", backend="fastf1")
        session.load(laps=False, telemetry=False, weather=False, messages=False)
    except Exception:
        return {}

    session_subpath = getattr(session, "api_path", None)
    if not session_subpath:
        return {}
    cache_root = Path(fastf1.Cache._CACHE_DIR)
    base_path = cache_root / session_subpath.lstrip('/static/')
    ext_path = base_path / '_extended_timing_data.ff1pkl'
    drv_path = base_path / 'driver_info.ff1pkl'
    if not ext_path.exists() or not drv_path.exists():
        return {}

    try:
        with ext_path.open('rb') as fp:
            ext_payload = pickle.load(fp)
        with drv_path.open('rb') as fp:
            drv_payload = pickle.load(fp)
    except Exception:
        return {}

    positions = None
    if isinstance(ext_payload, dict):
        data_tuple = ext_payload.get('data')
        if isinstance(data_tuple, tuple) and len(data_tuple) >= 2:
            positions = data_tuple[1]
    if not isinstance(positions, pd.DataFrame) or positions.empty:
        return {}

    driver_codes: Dict[str, str] = {}
    if isinstance(drv_payload, dict):
        info_data = drv_payload.get('data')
        if isinstance(info_data, dict):
            for num, info in info_data.items():
                if isinstance(info, dict):
                    code = info.get('Tla') or info.get('RacingNumber') or num
                    if code:
                        driver_codes[str(num)] = str(code).upper()

    grid_map: Dict[str, int] = {}
    first_positions = positions.sort_values('Time').groupby('Driver').first()
    for drv_id, row in first_positions.iterrows():
        code = driver_codes.get(str(drv_id))
        if not code:
            continue
        pos = row.get('Position')
        if pos is None or pd.isna(pos):
            continue
        try:
            grid_map[code] = int(pos)
        except (TypeError, ValueError):
            continue
    return grid_map


def _ergast_to_dataframe(resp: Any) -> pd.DataFrame | None:
    if resp is None:
        return None
    if isinstance(resp, pd.DataFrame):
        return resp
    content = getattr(resp, "content", None)
    if not content:
        return None
    frames: list[pd.DataFrame] = []
    for item in content:
        if item is None:
            continue
        if isinstance(item, pd.DataFrame):
            frames.append(item)
        else:
            try:
                frames.append(pd.DataFrame(item))
            except Exception:
                continue
    if not frames:
        return None
    if len(frames) == 1:
        return frames[0].copy()
    return pd.concat(frames, ignore_index=True, copy=False)


def _season_pole_stats(year: int) -> Dict[str, Dict[str, Any]]:
    try:
        response = Ergast().get_qualifying_results(season=year)
    except Exception:
        return {}
    df = _ergast_to_dataframe(response)
    if df is None or df.empty:
        return {}
    df = df.copy()
    df["position"] = pd.to_numeric(df.get("position"), errors="coerce")
    df = df[df["position"] == 1]
    if df.empty:
        return {}
    results: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        code = row.get("driverCode") or row.get("driverId") or row.get("driverSurname")
        if not code or pd.isna(code):
            continue
        code_str = str(code).upper()
        info = results.setdefault(code_str, {"count": 0, "rounds": []})
        info["count"] += 1
        try:
            rnd_int = int(row.get("round"))
        except Exception:
            continue
        info["rounds"].append(rnd_int)
    for info in results.values():
        info["rounds"].sort()
    return results


def _is_dnf(row: pd.Series, status_lookup: Dict[str, str] | None = None) -> bool:
    dnf_val = row.get("DNF")
    if pd.notna(dnf_val):
        if isinstance(dnf_val, str):
            text = dnf_val.strip().lower()
            if text in {"1", "true", "yes", "y", "t"}:
                return True
            if text in {"0", "false", "no", "n"}:
                return False
        else:
            try:
                if bool(dnf_val):
                    return True
            except Exception:
                pass
    status = row.get("Status")
    if (status is None or (isinstance(status, float) and pd.isna(status))) and status_lookup:
        code_val = row.get("Abbreviation")
        if code_val and not pd.isna(code_val):
            status = status_lookup.get(str(code_val).upper())
    if status is None or (isinstance(status, float) and pd.isna(status)):
        return False
    text = str(status).strip().lower()
    if not text:
        return False
    if text.startswith("+"):
        return False
    if any(keyword in text for keyword in _FINISH_KEYWORDS) and "not" not in text:
        return False
    if "lap" in text and not text.startswith("not"):
        return False
    if any(ex in text for ex in _NON_DNF_EXCLUDE):
        return False
    return True


def _load_ergast_status(year: int, rnd: int) -> Dict[str, str]:
    try:
        response = Ergast().get_race_results(season=year, round=rnd)
    except Exception:
        return {}
    df = _ergast_to_dataframe(response)
    if df is None or df.empty:
        return {}
    status_map: Dict[str, str] = {}
    for _, row in df.iterrows():
        code = row.get("driverCode") or row.get("driverId") or row.get("driverSurname")
        if not code or pd.isna(code):
            continue
        status = row.get("status") or row.get("Status")
        if status is None or (isinstance(status, float) and pd.isna(status)):
            continue
        status_map[str(code).upper()] = str(status)
    return status_map


def _make_driver_entry(code: str) -> Dict[str, Any]:
    return {
        "code": code,
        "full_name": code,
        "team": "",
        "team_color": "",
        "grid_position": None,
        "points": 0.0,
        "wins": 0,
        "podiums": 0,
        "dnfs": 0,
        "positions": [],
        "poles": 0,
        "pole_rounds": [],
    }


def _apply_sprint_points(year: int, rnd: int, results: Dict[str, Dict[str, Any]]) -> bool:
    try:
        sprint = fastf1.get_session(year, rnd, "S", backend="fastf1")
        sprint.load(laps=False, telemetry=False, weather=False, messages=False)
    except Exception:
        return False

    sres = sprint.results
    if sres is None or sres.empty:
        return False

    df = _ensure_abbreviation(sres)
    if "Points" not in df.columns:
        return False

    df["Points"] = pd.to_numeric(df["Points"], errors="coerce").fillna(0.0)
    added = False
    for _, row in df.iterrows():
        points = float(row.get("Points") or 0.0)
        if points <= 0:
            continue
        code_val = row.get("Abbreviation")
        if not code_val or pd.isna(code_val):
            continue
        code = str(code_val).upper()
        entry = results.setdefault(code, _make_driver_entry(code))
        if entry["full_name"] == code:
            entry["full_name"] = str(row.get("FullName") or row.get("BroadcastName") or row.get("Driver") or code)
        if not entry["team"]:
            entry["team"] = str(row.get("TeamName") or row.get("ConstructorName") or "")
        color = _normalize_hex_color(row.get("TeamColor"))
        if color:
            entry["team_color"] = color
        entry["points"] += points
        added = True
    return added


def _build_season_payload(year: int) -> Dict[str, Any]:
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if schedule is None or schedule.empty:
        raise HTTPException(status_code=404, detail="Season schedule not available")

    schedule = schedule.copy()
    if "RoundNumber" not in schedule.columns:
        raise HTTPException(status_code=500, detail="Schedule data missing round information")

    schedule["RoundNumber"] = pd.to_numeric(schedule["RoundNumber"], errors="coerce")
    schedule = schedule.dropna(subset=["RoundNumber"])
    schedule = schedule.sort_values("RoundNumber")

    results_by_driver: Dict[str, Dict[str, Any]] = {}
    pole_counts: defaultdict[str, int] = defaultdict(int)
    pole_rounds: defaultdict[str, list[int]] = defaultdict(list)
    sprint_rounds: set[int] = set()

    for _, event in schedule.iterrows():
        rnd_raw = event.get("RoundNumber")
        if pd.isna(rnd_raw):
            continue
        rnd = int(rnd_raw)
        try:
            _, df = load_results_strict(year, rnd)
        except Exception:
            continue
        if df is None or df.empty:
            continue

        df = _ensure_abbreviation(df)
        df["Points"] = pd.to_numeric(df.get("Points"), errors="coerce").fillna(0.0)
        df["Position"] = pd.to_numeric(df.get("Position"), errors="coerce")
        df["GridPosition"] = pd.to_numeric(df.get("GridPosition"), errors="coerce")

        fallback_grid = _fallback_grid_positions(year, rnd)
        if fallback_grid:
            mask = df["GridPosition"].isna()
            if mask.any():
                df.loc[mask, "GridPosition"] = df.loc[mask, "Abbreviation"].map(lambda v: fallback_grid.get(str(v).upper()))

        pole_rows = df[df["GridPosition"] == 1]
        if not pole_rows.empty:
            pole_code = str(pole_rows.iloc[0].get("Abbreviation") or "").upper()
            if pole_code:
                pole_counts[pole_code] += 1
                pole_rounds[pole_code].append(rnd)

        extended_grid = _load_extended_grid_positions(year, rnd)
        status_lookup = _load_ergast_status(year, rnd)
        if extended_grid:
            for code_ext, pos_ext in extended_grid.items():
                if pos_ext == 1:
                    pole_counts[code_ext] += 1
                    pole_rounds[code_ext].append(rnd)

        for _, row in df.iterrows():
            code_val = row.get("Abbreviation")
            if not code_val or pd.isna(code_val):
                continue
            code = str(code_val).upper()
            entry = results_by_driver.setdefault(code, _make_driver_entry(code))

            full_name = row.get("FullName") or row.get("BroadcastName") or row.get("Driver")
            if full_name:
                entry["full_name"] = str(full_name)
            team_name = row.get("TeamName") or row.get("ConstructorName")
            if team_name:
                entry["team"] = str(team_name)
            color = _normalize_hex_color(row.get("TeamColor"))
            if color:
                entry["team_color"] = color

            grid_val = row.get("GridPosition")
            if grid_val is not None and not pd.isna(grid_val):
                entry["grid_position"] = int(grid_val)
            elif extended_grid:
                mapped = extended_grid.get(code)
                if mapped is not None:
                    entry["grid_position"] = int(mapped)

            entry["points"] += float(row.get("Points") or 0.0)

            pos_val = row.get("Position")
            if pos_val is not None and not pd.isna(pos_val):
                pos_int = int(pos_val)
                entry["positions"].append(pos_int)
                if pos_int == 1:
                    entry["wins"] += 1
                if pos_int <= 3:
                    entry["podiums"] += 1

            if _is_dnf(row, status_lookup):
                entry["dnfs"] += 1

        if _apply_sprint_points(year, rnd, results_by_driver):
            sprint_rounds.add(rnd)

    if pole_counts:
        for code, count in pole_counts.items():
            entry = results_by_driver.setdefault(code, _make_driver_entry(code))
            entry["poles"] = count
            entry["pole_rounds"] = sorted(pole_rounds.get(code, []))
    else:
        pole_stats = _season_pole_stats(year)
        for code, info in pole_stats.items():
            entry = results_by_driver.setdefault(code, _make_driver_entry(code))
            entry["poles"] = int(info.get("count", 0))
            entry["pole_rounds"] = list(info.get("rounds", []))

    drivers_payload: Dict[str, Dict[str, Any]] = {}
    for code, entry in results_by_driver.items():
        positions = entry.pop("positions")
        avg_finish = float(pd.Series(positions).mean()) if positions else None
        drivers_payload[code] = {
            "code": code,
            "full_name": entry["full_name"],
            "name": entry["full_name"],
            "team": entry["team"],
            "team_color": entry["team_color"],
            "grid_position": entry["grid_position"],
            "total_points": float(entry["points"]),
            "wins": entry["wins"],
            "podiums": entry["podiums"],
            "dnfs": entry["dnfs"],
            "avg_finish": avg_finish,
            "poles": entry["poles"],
            "pole_rounds": entry["pole_rounds"],
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "season": year,
        "drivers": drivers_payload,
        "sprint_rounds": sorted(sprint_rounds),
    }


@router.get("/season/{year}")
def load_season(year: int, response: Response, refresh: bool = False) -> Dict[str, Any]:
    if not refresh:
        cached = _load_from_cache(year)
        if cached and cached.get("schema_version") == SCHEMA_VERSION and cached.get("drivers"):
            response.headers["Cache-Control"] = "public, max-age=86400"
            return cached

    payload = _build_season_payload(year)
    _save_to_cache(year, payload)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return payload


def _load_from_cache(year: int) -> Dict[str, Any] | None:
    try:
        return cache_load(__file__, year)
    except Exception:
        return None


def _save_to_cache(year: int, payload: Dict[str, Any]) -> None:
    try:
        cache_save(__file__, year, payload)
    except Exception:
        pass
