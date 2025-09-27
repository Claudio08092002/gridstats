import os
from collections import defaultdict
from typing import Dict, Any

import fastf1
import time
from fastf1.ergast import Ergast, interface as ergast_interface
import pandas as pd
from fastapi import APIRouter, HTTPException, Response

from app.services.cache_utils import load_season as cache_load, save_season as cache_save
from app.services.f1_utils import load_results_strict

router = APIRouter(prefix="/f1", tags=["fastf1"])
SCHEMA_VERSION = 5

# In-memory season cache to avoid recomputation after first heavy build.
# Key: year -> {"payload": dict, "ts": epoch_seconds}
_SEASON_CACHE: dict[int, dict[str, Any]] = {}
_SEASON_CACHE_TTL = int(os.getenv("SEASON_CACHE_TTL", "43200"))  # 12h default

# ---- Cache (nur hier einmal) -------------------------------------------------
default_cache = "C:/Users/claud/.fastf1_cache" if os.name == "nt" else "/data/fastf1_cache"
cache_dir = os.getenv("FASTF1_CACHE", default_cache)
os.makedirs(cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(cache_dir)

# Nutze den FastF1-Default für Ergast, außer eine Env-Var erzwingt etwas anderes.
ERGAST_BASE_URL = os.getenv("ERGAST_BASE_URL")
if ERGAST_BASE_URL:
    ergast_interface.BASE_URL = ERGAST_BASE_URL



def _load_from_cache(year: int) -> Dict[str, Any] | None:
    return cache_load(__file__, year)

def _save_to_cache(year: int, payload: Dict[str, Any]) -> None:
    cache_save(__file__, year, payload)

# ---- Hilfen --------------------------------------------------------
def _ensure_abbreviation(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure an Abbreviation column exists using fallbacks."""
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


def _fallback_grid_positions(year: int, rnd: int, ergast: Ergast | None = None) -> Dict[str, int]:
    """Fallback grid positions using Ergast qualifying results when race data lacks them."""
    try:
        client = ergast or Ergast()
        resp = client.get_qualifying_results(season=year, round=rnd)
    except Exception:
        return {}
    df = _ergast_to_dataframe(resp)
    if df is None or df.empty:
        return {}
    if "position" not in df.columns:
        return {}
    df = df.copy()
    df["position"] = pd.to_numeric(df["position"], errors="coerce")
    fallback: Dict[str, int] = {}
    for _, row in df.iterrows():
        pos = row.get("position")
        if pd.isna(pos):
            continue
        code = row.get("driverCode") or row.get("driverId") or row.get("driverSurname")
        if not code or pd.isna(code):
            continue
        fallback[str(code).upper()] = int(pos)
    return fallback


def _normalize_hex_color(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not s.startswith("#"):
        s = f"#{s}"
    if len(s) == 4:
        s = "#" + "".join(ch * 2 for ch in s[1:])
    if len(s) != 7:
        return None
    return s.upper()


def _driver_metadata(year: int, rnd: int, ergast: Ergast | None = None) -> Dict[str, Dict[str, str]]:
    meta: Dict[str, Dict[str, str]] = {}
    try:
        client = ergast or Ergast()
        resp = client.get_race_results(season=year, round=rnd)
    except Exception:
        return meta
    df = _ergast_to_dataframe(resp)
    if df is None or df.empty:
        return meta
    df = df.copy()
    if "grid" in df.columns:
        df["grid"] = pd.to_numeric(df["grid"], errors="coerce")
    for _, row in df.iterrows():
        code = row.get("driverCode") or row.get("driverId") or row.get("driverSurname")
        if not code or pd.isna(code):
            continue
        code_str = str(code).upper()
        given = row.get("driverGivenName") or ""
        family = row.get("driverFamilyName") or ""
        full_name = " ".join(part for part in [given, family] if part).strip() or row.get("driverFullName") or row.get("driverSurname") or code_str
        team = row.get("constructorName") or row.get("ConstructorName") or ""
        grid_val = row.get("grid")
        if grid_val is None or pd.isna(grid_val):
            grid_val = row.get("GridPosition")
        try:
            grid_numeric = int(grid_val) if grid_val is not None and not pd.isna(grid_val) else None
        except Exception:
            grid_numeric = None
        meta[code_str] = {
            "full_name": str(full_name),
            "team": str(team),
            "team_color": "",
            "grid_position": grid_numeric,
        }
    return meta


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


def _season_pole_stats(year: int, ergast: Ergast | None = None) -> tuple[Dict[str, int], Dict[str, list[int]]]:
    try:
        client = ergast or Ergast()
        resp = client.get_qualifying_results(season=year)
    except Exception:
        return {}, {}
    df = _ergast_to_dataframe(resp)
    if df is None or df.empty or "position" not in df.columns:
        return {}, {}
    poles = df.copy()
    poles["position"] = pd.to_numeric(poles["position"], errors="coerce")
    poles = poles[poles["position"] == 1]
    if poles.empty:
        return {}, {}

    counts: defaultdict[str, int] = defaultdict(int)
    rounds: defaultdict[str, list[int]] = defaultdict(list)

    for _, row in poles.iterrows():
        code = row.get("driverCode") or row.get("driverId") or row.get("driverSurname")
        if not code or pd.isna(code):
            continue
        code_str = str(code).upper()
        rnd_raw = row.get("round")
        try:
            rnd = int(rnd_raw)
        except (TypeError, ValueError):
            rnd = None
        counts[code_str] += 1
        if rnd is not None:
            rounds[code_str].append(rnd)

    return dict(counts), {k: sorted(v) for k, v in rounds.items()}


_FINISH_LIKE = {"finished", "lapped"}
# Consider these as non-DNF outcomes. Note: "not classified" will be treated as DNF.
_NON_DNF_EXCLUDE = {"disqualified", "did not start", "excluded"}


def _season_dnf_counts(year: int, ergast: Ergast | None = None) -> Dict[str, int]:
    try:
        client = ergast or Ergast()
        resp = client.get_race_results(season=year)
    except Exception:
        return {}
    df = _ergast_to_dataframe(resp)
    if df is None or df.empty or "status" not in df.columns:
        return {}

    status_raw = df["status"].astype(str).fillna("").str.strip()
    status_lower = status_raw.str.lower()
    is_finish = status_raw.str.startswith("+") | status_lower.isin(_FINISH_LIKE)
    is_excluded = status_lower.isin(_NON_DNF_EXCLUDE)
    mask = ~(is_finish | is_excluded)
    if not mask.any():
        return {}

    dnfs = df[mask]
    counts: defaultdict[str, int] = defaultdict(int)
    for _, row in dnfs.iterrows():
        code = row.get("driverCode") or row.get("driverId") or row.get("driverSurname")
        if not code or pd.isna(code):
            continue
        code_str = str(code).upper()
        counts[code_str] += 1
    return dict(counts)


def _apply_sprint_points(year: int, rnd: int, results_by_driver: Dict[str, Dict[str, Any]], num_to_abbr: Dict[str, str] | None = None):
    """Load sprint results (session 'S') via Ergast and add Points to totals.
    Does NOT affect wins/podiums/dnfs.
    """
    try:
        with fastf1.Cache.disabled():
            ses_s = fastf1.get_session(year, rnd, "S", backend="ergast")
            ses_s.load(laps=False, telemetry=False, weather=False, messages=False)
            sres = ses_s.results.copy() if ses_s.results is not None else None
    except Exception:
        sres = None
    if sres is None or sres.empty:
        return
    sres = _ensure_abbreviation(sres)
    # Normalize fields
    if "Points" not in sres.columns:
        sres["Points"] = pd.NA
    sres["Points"] = pd.to_numeric(sres["Points"], errors="coerce").fillna(0.0)
    if "Position" in sres.columns:
        sres["Position"] = pd.to_numeric(sres["Position"], errors="coerce")

    # If Ergast didn't return sprint points (rare), compute by rules:
    #  - 2021: top 3 get 3-2-1
    #  - 2022+: top 8 get 8-7-6-5-4-3-2-1
    use_fallback = (float(sres["Points"].sum()) <= 0.0)
    if use_fallback and "Position" in sres.columns:
        if year <= 2021:
            sp_map = {1: 3, 2: 2, 3: 1}
        else:
            sp_map = {1: 8, 2: 7, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1}
        sres["__SPTS__"] = sres["Position"].map(sp_map).fillna(0).astype(float)
    else:
        sres["__SPTS__"] = sres["Points"].astype(float)

    for _, row in sres.iterrows():
        pts = float(row.get("__SPTS__", 0.0) or 0.0)
        if pts <= 0:
            continue
        code_val = row.get("Abbreviation")
        # Normalize to 3-letter abbreviation using provided mapping if necessary
        code = None
        if code_val and pd.notna(code_val):
            code = str(code_val)
        else:
            drvnum = row.get("DriverNumber")
            if num_to_abbr and pd.notna(drvnum):
                code = num_to_abbr.get(str(drvnum))
        if not code:
            continue
        d = results_by_driver.setdefault(code, {
            "code": code,
            "full_name": str(row.get("FullName") or row.get("BroadcastName") or row.get("Driver") or code),
            "team": str(row.get("TeamName") or row.get("ConstructorName") or ""),
            "team_color": _normalize_hex_color(row.get("TeamColor")) or "",
            "grid_position": None,
            "points": 0.0,
            "wins": 0,
            "podiums": 0,
            "dnfs": 0,
            "positions": [],
            "poles": 0,
        })
        d["code"] = code
        if len(str(d.get("full_name", ""))) <= 3:
            d["full_name"] = str(row.get("FullName") or row.get("BroadcastName") or row.get("Driver") or code)
        if not d.get("team"):
            d["team"] = str(row.get("TeamName") or row.get("ConstructorName") or "")
        if not d.get("team_color"):
            d["team_color"] = _normalize_hex_color(row.get("TeamColor")) or ""
        d["points"] += pts

# ---- Endpoint ----------------------------------------------------------------


@router.get("/season/{year}")
def load_season(year: int, response: Response, refresh: bool = False) -> Dict[str, Any]:
    """
    Aggregiert pro Fahrer:
      total_points, wins, podiums, dnfs, avg_finish, poles

    - nutzt load_results_strict (fastf1 -> ergast -> derived) fuer verlaessliche Ergebnisse
    - persistenter JSON-Cache
    - Poles: GridPosition==1; Fallback via Quali/SQ (ergast)
    """
    try:
        # 1. In-memory hot cache first
        if not refresh:
            mem_entry = _SEASON_CACHE.get(year)
            if mem_entry:
                ts = mem_entry.get("ts", 0)
                if time.time() - float(ts) <= _SEASON_CACHE_TTL:
                    payload = mem_entry.get("payload")
                    if isinstance(payload, dict) and payload.get("schema_version") == SCHEMA_VERSION:
                        response.headers["Cache-Control"] = "public, max-age=86400"
                        return payload  # Fast in-memory hit

        # 2. Persistent JSON cache (disk)
        if not refresh:
            disk_cached = _load_from_cache(year)
            if disk_cached and isinstance(disk_cached, dict):
                if disk_cached.get("schema_version") == SCHEMA_VERSION and disk_cached.get("drivers"):
                    # Promote to in-memory cache
                    _SEASON_CACHE[year] = {"payload": disk_cached, "ts": time.time()}
                    response.headers["Cache-Control"] = "public, max-age=86400"
                    return disk_cached
        # If caches miss or refresh=True -> rebuild

        schedule = fastf1.get_event_schedule(year, include_testing=False)
        ergast_client = Ergast()

        pole_counts: defaultdict[str, int] = defaultdict(int)
        pole_rounds: defaultdict[str, list[int]] = defaultdict(list)
        results_by_driver: Dict[str, Dict[str, Any]] = {}

        for _, ev in schedule.iterrows():
            rnd = ev.get("RoundNumber")
            if pd.isna(rnd) or int(rnd) <= 0:
                continue
            rnd = int(rnd)

            # Race-Results (robust via helper)
            try:
                _, df = load_results_strict(year, rnd)
            except Exception:
                df = None
            if df is None or df.empty:
                continue

            metadata = _driver_metadata(year, rnd, ergast_client)

            for need in ("Points", "Position"):
                if need not in df.columns:
                    df[need] = pd.NA
            if "GridPosition" not in df.columns:
                df["GridPosition"] = pd.NA

            df["Points"] = pd.to_numeric(df["Points"], errors="coerce").fillna(0.0)
            df["Position"] = pd.to_numeric(df["Position"], errors="coerce")
            df["GridPosition"] = pd.to_numeric(df["GridPosition"], errors="coerce")

            codes_upper = df["Abbreviation"].astype(str).str.upper()
            if df["GridPosition"].isna().all():
                fallback_grid = _fallback_grid_positions(year, rnd, ergast_client)
                if fallback_grid:
                    df["GridPosition"] = codes_upper.map(fallback_grid)

            try:
                gp = pd.to_numeric(df["GridPosition"], errors="coerce")
                pole_rows = df[gp == 1]
                if pole_rows is not None and not pole_rows.empty:
                    pole_abbr = pole_rows.iloc[0].get("Abbreviation")
                    if pole_abbr is not None and not pd.isna(pole_abbr):
                        code = str(pole_abbr).upper()
                        pole_counts[code] += 1
                        pole_rounds[code].append(rnd)
            except Exception:
                pass

            for _, row in df.iterrows():
                code_val = row.get("Abbreviation")
                if not code_val or pd.isna(code_val):
                    continue
                code = str(code_val).upper()
                meta_entry = metadata.get(code, {})
                full_name = meta_entry.get("full_name") or row.get("FullName") or row.get("BroadcastName") or row.get("Driver") or code
                team_name = meta_entry.get("team") or row.get("TeamName") or row.get("ConstructorName") or ""
                team_color = _normalize_hex_color(row.get("TeamColor")) or meta_entry.get("team_color") or ""
                grid_val = row.get("GridPosition")
                if grid_val is None or pd.isna(grid_val):
                    grid_val = meta_entry.get("grid_position")
                try:
                    grid_numeric = int(grid_val) if grid_val is not None and not pd.isna(grid_val) else None
                except Exception:
                    grid_numeric = None

                driver_entry = results_by_driver.setdefault(code, {
                    "code": code,
                    "full_name": str(full_name),
                    "team": str(team_name),
                    "team_color": team_color,
                    "grid_position": grid_numeric,
                    "points": 0.0,
                    "wins": 0,
                    "podiums": 0,
                    "dnfs": 0,
                    "positions": [],
                    "poles": 0,
                    "pole_rounds": [],
                })
                driver_entry["code"] = code
                driver_entry["full_name"] = str(full_name)
                driver_entry["team"] = str(team_name)
                driver_entry["team_color"] = team_color
                if grid_numeric is not None:
                    driver_entry["grid_position"] = grid_numeric

                driver_entry["points"] += float(row["Points"])

                pos = row.get("Position")
                if pd.notna(pos):
                    ipos = int(pos)
                    driver_entry["positions"].append(ipos)
                    if ipos == 1:
                        driver_entry["wins"] += 1
                    if ipos <= 3:
                        driver_entry["podiums"] += 1

                try:
                    dnf_raw = row.get("DNF")
                    is_dnf = False
                    if pd.notna(dnf_raw):
                        if isinstance(dnf_raw, str):
                            is_dnf = dnf_raw.strip().lower() in ("1", "true", "yes", "y", "t")
                        else:
                            is_dnf = bool(dnf_raw)
                    if is_dnf:
                        driver_entry["dnfs"] += 1
                except Exception:
                    pass

            num_to_abbr: Dict[str, str] = {}
            if "DriverNumber" in df.columns and "Abbreviation" in df.columns:
                subset = df[["DriverNumber", "Abbreviation"]].dropna()
                for _, rr in subset.iterrows():
                    num_to_abbr[str(rr["DriverNumber"])] = str(rr["Abbreviation"]).upper()

            _apply_sprint_points(year, rnd, results_by_driver, num_to_abbr)

        for code, count in pole_counts.items():
            entry = results_by_driver.get(code)
            rounds = sorted(pole_rounds.get(code, []))
            if entry is None:
                results_by_driver[code] = {
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
                    "poles": int(count),
                    "pole_rounds": rounds,
                }
            else:
                entry["poles"] = int(count)
                entry["pole_rounds"] = rounds

        out: Dict[str, Any] = {}
        for code, data in results_by_driver.items():
            positions = data["positions"]
            avg = float(pd.Series(positions).mean()) if positions else None
            full_name = str(data.get("full_name") or code)
            team_name = str(data.get("team") or "")
            team_color = data.get("team_color") or ""
            raw_grid = data.get("grid_position")
            if raw_grid is not None and not pd.isna(raw_grid):
                try:
                    grid_position = int(raw_grid)
                except (TypeError, ValueError):
                    grid_position = None
            else:
                grid_position = None
            out[code] = {
                "code": code,
                "full_name": full_name,
                "name": full_name,
                "team": team_name,
                "team_color": team_color,
                "grid_position": grid_position,
                "total_points": float(data["points"]),
                "wins": int(data["wins"]),
                "podiums": int(data["podiums"]),
                "dnfs": int(data["dnfs"]),
                "avg_finish": (float(avg) if avg is not None else None),
                "poles": int(pole_counts.get(code, data.get("poles", 0))),
                "pole_rounds": list(data.get("pole_rounds", [])),
            }

        payload = {
            "schema_version": SCHEMA_VERSION,
            "season": year,
            "drivers": out,
        }
        # Persist to disk + memory
        _save_to_cache(year, payload)
        _SEASON_CACHE[year] = {"payload": payload, "ts": time.time()}
        response.headers["Cache-Control"] = "public, max-age=86400"
        return payload

    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(e))
