import os
import threading
import time
import json
from collections import defaultdict
from typing import Dict, Any, List, Optional

import fastf1
from fastf1.ergast import Ergast, interface as ergast_interface
import pandas as pd
from fastapi import APIRouter, HTTPException, Response

from app.services.cache_utils import load_season as cache_load, save_season as cache_save
from app.services.f1_utils import load_results_strict
from app.config import resolve_forced_debug_driver

router = APIRouter(prefix="/f1", tags=["fastf1"])
# Increment when output structure changes; 10 adds optional debug + sprint optimization
SCHEMA_VERSION = 10

# ---- Cache (nur hier einmal) -------------------------------------------------
default_cache = "C:/Users/claud/.fastf1_cache" if os.name == "nt" else "/data/fastf1_cache"
cache_dir = os.getenv("FASTF1_CACHE", default_cache)
os.makedirs(cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(cache_dir)

ERGAST_BASE_URL = os.getenv("ERGAST_BASE_URL", "https://api.jolpi.ca/ergast/f1")
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


def _fallback_grid_positions(year: int, rnd: int) -> Dict[str, int]:
    """Fallback grid positions by using qualifying results when race data lacks them."""
    try:
        ses_q = fastf1.get_session(year, rnd, "Q", backend="fastf1")
        ses_q.load(laps=False, telemetry=False, weather=False, messages=False)
        qres = ses_q.results
        if qres is None or qres.empty:
            return {}
        qres = qres.copy()
        qres = _ensure_abbreviation(qres)
        if "Position" not in qres.columns:
            return {}
        qres["Position"] = pd.to_numeric(qres["Position"], errors="coerce")
        qres = qres.dropna(subset=["Position", "Abbreviation"])
        qres = qres.sort_values("Position")
        fallback: Dict[str, int] = {}
        for _, row in qres.iterrows():
            code = row.get("Abbreviation")
            pos = row.get("Position")
            if code and pd.notna(code) and pd.notna(pos):
                fallback[str(code)] = int(pos)
        return fallback
    except Exception:
        return {}


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


def _driver_metadata(year: int, rnd: int) -> Dict[str, Dict[str, str]]:
    meta: Dict[str, Dict[str, str]] = {}
    try:
        ses = fastf1.get_session(year, rnd, "R", backend="fastf1")
        ses.load(laps=False, telemetry=False, weather=False, messages=False)
        res = ses.results
        fallback_grid = _fallback_grid_positions(year, rnd)
        if res is None or res.empty:
            for code, pos in fallback_grid.items():
                meta[str(code)] = {
                    "full_name": "",
                    "team": "",
                    "team_color": "",
                    "grid_position": int(pos),
                }
            return meta
        for _, row in res.iterrows():
            code = row.get("Abbreviation")
            if not code or pd.isna(code):
                continue
            code_str = str(code)
            full_name = row.get("FullName") or row.get("BroadcastName") or row.get("Driver") or code_str
            team = row.get("TeamName") or ""
            color = _normalize_hex_color(row.get("TeamColor"))
            grid_val = row.get("GridPosition")
            if pd.isna(grid_val) and fallback_grid:
                grid_val = fallback_grid.get(code_str)
            meta[code_str] = {
                "full_name": str(full_name),
                "team": str(team),
                "team_color": color or "",
                "grid_position": int(grid_val) if grid_val is not None and not pd.isna(grid_val) else None,
            }
    except Exception:
        return meta
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




def _apply_sprint_points(year: int, rnd: int, results_by_driver: Dict[str, Dict[str, Any]], num_to_abbr: Dict[str, str] | None = None, collect: Optional[Dict[str, float]] = None):
    """Add sprint points to totals. Assumes DataFrame already normalized by loader.
    Does NOT affect wins/podiums/dnfs.
    Expects an already prepared sprint results DataFrame attached to results_by_driver via caller.
    """
    if "__SPTS__" not in results_by_driver.get("__SPRINT_TMP__", {}):
        # Guard: caller should supply sprint rows separately; keep backward compat if misused
        pass
    sres = results_by_driver.pop("__SPRINT_TMP__", None)  # type: ignore
    if sres is None or not isinstance(sres, pd.DataFrame) or sres.empty:
        return
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
        if collect is not None:
            collect[code] = collect.get(code, 0.0) + pts


# ---- Sprint round detection -------------------------------------------------
_SPRINT_ROUNDS_CACHE: dict[int, List[int]] = {}

def _load_sprint_results(year: int, rnd: int) -> tuple[pd.DataFrame | None, str | None]:
    """Return sprint results DataFrame preferring fastf1 then ergast.
    Normalizes Points -> float and adds __SPTS__ column (fallback if needed).
    Returns (df, backend_used)."""
    backends = ["fastf1", "ergast"]
    last_exc: Exception | None = None
    for be in backends:
        try:
            # Disable cache only for network path differences; keep disk caching for fastf1
            ses_s = fastf1.get_session(year, rnd, "S", backend=be)
            ses_s.load(laps=False, telemetry=False, weather=False, messages=False)
            sres = ses_s.results.copy() if ses_s.results is not None else None
            if sres is None or sres.empty:
                continue
            sres = _ensure_abbreviation(sres)
            if "Points" not in sres.columns:
                sres["Points"] = pd.NA
            sres["Points"] = pd.to_numeric(sres["Points"], errors="coerce").fillna(0.0)
            if "Position" in sres.columns:
                sres["Position"] = pd.to_numeric(sres["Position"], errors="coerce")
            # Fallback scoring
            use_fallback = (float(sres["Points"].sum()) <= 0.0)
            if use_fallback and "Position" in sres.columns:
                if year <= 2021:
                    sp_map = {1: 3, 2: 2, 3: 1}
                else:
                    sp_map = {1: 8, 2: 7, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1}
                sres["__SPTS__"] = sres["Position"].map(sp_map).fillna(0).astype(float)
            else:
                sres["__SPTS__"] = sres["Points"].astype(float)
            sres["__BACKEND__"] = be
            return sres, be
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
    return None, None

def _detect_sprint_rounds(year: int) -> List[int]:
    cached = _SPRINT_ROUNDS_CACHE.get(year)
    if cached is not None:
        return cached
    rounds: List[int] = []
    try:
        sched = fastf1.get_event_schedule(year, include_testing=False)
        if sched is None or sched.empty:
            _SPRINT_ROUNDS_CACHE[year] = rounds
            return rounds
        # Heuristics: any column value containing 'sprint' (case-insensitive) marks the round
        lowered_cols = {c: sched[c].astype(str).str.lower() for c in sched.columns}
        for idx, row in sched.iterrows():
            rn = row.get('RoundNumber')
            if pd.isna(rn):
                continue
            rn_int = int(rn)
            row_str = ' '.join(str(v).lower() for v in row.values if v is not None)
            if 'sprint' in row_str:
                rounds.append(rn_int)
        # Secondary heuristic: some schedules might list sessions separately; try get_session meta
        if not rounds:
            for idx, row in sched.iterrows():
                rn = row.get('RoundNumber')
                if pd.isna(rn):
                    continue
                rn_int = int(rn)
                try:
                    ev = fastf1.get_event(year, rn_int)
                    if hasattr(ev, 'format') and ev.format and 'sprint' in str(ev.format).lower():
                        rounds.append(rn_int)
                except Exception:
                    continue
        rounds = sorted(set(rounds))
    except Exception:
        rounds = []
    _SPRINT_ROUNDS_CACHE[year] = rounds
    return rounds

# ---- In-memory hot cache & build lock --------------------------------------
_MEM_SEASON: dict[int, dict] = {}
_MEM_TTL_SECONDS = int(os.getenv("SEASON_MEM_TTL", "21600"))  # 6h default
_BUILDING: set[int] = set()

def _mem_get(year: int) -> Optional[dict]:
    entry = _MEM_SEASON.get(year)
    if not entry:
        return None
    if time.time() - entry.get('ts', 0) > _MEM_TTL_SECONDS:
        _MEM_SEASON.pop(year, None)
        return None
    if entry.get('payload', {}).get('schema_version') != SCHEMA_VERSION:
        _MEM_SEASON.pop(year, None)
        return None
    return entry['payload']

def _mem_put(year: int, payload: dict):
    _MEM_SEASON[year] = {"payload": payload, "ts": time.time()}

# ---- Prewarm ---------------------------------------------------------------
def _prewarm():
    spec = os.getenv("PREWARM_SEASONS")
    if not spec:
        return
    try:
        years: List[int] = []
        for part in spec.split(','):
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                a, b = part.split('-', 1)
                ya, yb = int(a), int(b)
                if ya > yb:
                    ya, yb = yb, ya
                years.extend(range(ya, yb + 1))
            else:
                years.append(int(part))
        years = sorted(set(years))
    except Exception:
        return
    print(f"[prewarm] starting for seasons: {years}")
    for y in years:
        try:
            # Trigger lazy build without refresh; ignore if already cached
            if _mem_get(y):
                print(f"[prewarm] memory cache already warm for {y}")
                continue
            print(f"[prewarm] building season {y}")
            load_season(y, Response(), refresh=False)  # type: ignore
            if _mem_get(y):
                print(f"[prewarm] season {y} ready")
        except Exception:
            print(f"[prewarm] season {y} failed", flush=True)
            continue

if os.getenv("PREWARM_SEASONS"):
    threading.Thread(target=_prewarm, name="prewarm-fastf1", daemon=True).start()

# ---- Endpoint ----------------------------------------------------------------

@router.get("/season/{year}")
def load_season(year: int, response: Response, refresh: bool = False, debug_driver: Optional[str] = None) -> Dict[str, Any]:
    """
    Aggregiert pro Fahrer:
      total_points, wins, podiums, dnfs, avg_finish, poles

    - nutzt load_results_strict (fastf1 -> ergast -> derived) für verlässliche Ergebnisse
    - persistenter JSON-Cache
    - Poles: GridPosition==1; Fallback via Quali/SQ (ergast)
    """
    try:
        # 0. In-memory cache
        if not refresh:
            mem_hit = _mem_get(year)
            if mem_hit:
                response.headers["Cache-Control"] = "public, max-age=86400"
                response.headers["X-Season-Cache"] = "memory"
                return mem_hit
        # Avoid stampede: if another thread is building and caller didn't force refresh
        if year in _BUILDING and not refresh:
            # Lightweight 202 response (client can retry soon)
            response.status_code = 202
            return {"season": year, "status": "building"}
        if not refresh:
            cached = _load_from_cache(year)
            if cached and isinstance(cached, dict):
                if cached.get("schema_version") == SCHEMA_VERSION and cached.get("drivers"):
                    _mem_put(year, cached)
                    response.headers["Cache-Control"] = "public, max-age=86400"
                    response.headers["X-Season-Cache"] = "disk"
                    return cached

        schedule = fastf1.get_event_schedule(year, include_testing=False)
        # Determine sprint rounds once
        sprint_rounds = set(_detect_sprint_rounds(year)) if os.getenv("ENABLE_SPRINT_POINTS", "1").lower() not in ("0", "false") else set()
        # Precedence: query param > forced (config/env/file) > none
        forced = resolve_forced_debug_driver()
        debug_code = (debug_driver or forced or "").strip().upper()
        debug_points: Dict[str, List[Dict[str, Any]]] = {}
        _BUILDING.add(year)
        # Compute poles from race grid positions per round
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

            metadata = _driver_metadata(year, rnd)

            # Normalisieren
            # Typical columns in df after load_results_strict:
            # ['Abbreviation', 'Position', 'Points', 'Status', 'GridPosition', 'TeamName',
            #  'TeamColor', 'FullName', 'BroadcastName', 'DriverNumber', ...]
            for need in ("Points", "Position"):
                if need not in df.columns:
                    df[need] = pd.NA
            if "GridPosition" not in df.columns:
                df["GridPosition"] = pd.NA

            df["Points"] = pd.to_numeric(df["Points"], errors="coerce").fillna(0.0)
            df["Position"] = pd.to_numeric(df["Position"], errors="coerce")
            df["GridPosition"] = pd.to_numeric(df["GridPosition"], errors="coerce")
            if df["GridPosition"].isna().all():
                fallback_grid = _fallback_grid_positions(year, rnd)
                if fallback_grid:
                    df["GridPosition"] = df["Abbreviation"].map(fallback_grid)

            # Count pole for this round from GridPosition == 1
            try:
                gp = pd.to_numeric(df["GridPosition"], errors="coerce")
                pole_rows = df[gp == 1]
                if pole_rows is not None and not pole_rows.empty:
                    pole_abbr = pole_rows.iloc[0].get("Abbreviation")
                    if pole_abbr is not None and pd.notna(pole_abbr):
                        code = str(pole_abbr)
                        pole_counts[code] += 1
                        pole_rounds[code].append(rnd)
            except Exception:
                pass

            race_points_this_round: Dict[str, float] = {}
            # Aggregation pro Fahrer
            for _, row in df.iterrows():
                code = row.get("Abbreviation")
                if not code or pd.isna(code):
                    continue
                code = str(code)
                meta_entry = metadata.get(code, {})
                full_name = meta_entry.get("full_name") or row.get("FullName") or row.get("BroadcastName") or row.get("Driver") or code
                team_name = meta_entry.get("team") or row.get("TeamName") or row.get("ConstructorName") or ""
                team_color = meta_entry.get("team_color") or _normalize_hex_color(row.get("TeamColor"))
                grid_pos = meta_entry.get("grid_position")
                grid_numeric = None
                if grid_pos is not None and not pd.isna(grid_pos):
                    try:
                        grid_numeric = int(grid_pos)
                    except (TypeError, ValueError):
                        grid_numeric = None
                d = results_by_driver.setdefault(code, {
                    "code": code,
                    "full_name": str(full_name),
                    "team": str(team_name),
                    "team_color": team_color or "",
                    "grid_position": grid_numeric,
                    "points": 0.0,
                    "wins": 0,
                    "podiums": 0,
                    "dnfs": 0,
                    "positions": [],
                    "poles": 0,
                    "pole_rounds": [],
                })
                d["code"] = code
                d["full_name"] = str(full_name)
                d["team"] = str(team_name)
                if team_color is not None:
                    d["team_color"] = team_color or ""
                if grid_numeric is not None:
                    d["grid_position"] = grid_numeric

                pts_add = float(row["Points"])
                d["points"] += pts_add
                race_points_this_round[code] = race_points_this_round.get(code, 0.0) + pts_add

                pos = row.get("Position")
                if pd.notna(pos):
                    ipos = int(pos)
                    d["positions"].append(ipos)
                    if ipos == 1:
                        d["wins"] += 1
                    if ipos <= 3:
                        d["podiums"] += 1

                # DNF from load_results_strict (added in f1_utils)
                try:
                    dnf_raw = row.get("DNF")
                    is_dnf = False
                    if pd.notna(dnf_raw):
                        if isinstance(dnf_raw, str):
                            is_dnf = dnf_raw.strip().lower() in ("1", "true", "yes", "y", "t")
                        else:
                            is_dnf = bool(dnf_raw)
                    if is_dnf:
                        d["dnfs"] += 1
                except Exception:
                    pass

            # Build DriverNumber -> Abbreviation map from race df (ensures consistent keys)
            num_to_abbr: Dict[str, str] = {}
            if "DriverNumber" in df.columns and "Abbreviation" in df.columns:
                for _, rr in df[["DriverNumber", "Abbreviation"]].dropna().iterrows():
                    num_to_abbr[str(rr["DriverNumber"])] = str(rr["Abbreviation"])
            # Sprint points: prefer fastf1, fallback ergast
            sprint_added: Dict[str, float] = {}
            sprint_df: pd.DataFrame | None = None
            sprint_backend: str | None = None
            if os.getenv("ENABLE_SPRINT_POINTS", "1").lower() not in ("0", "false"):
                if rnd in sprint_rounds:
                    sprint_df, sprint_backend = _load_sprint_results(year, rnd)
                else:
                    # Lazy probe: attempt load; if success add to sprint_rounds
                    sprint_df, sprint_backend = _load_sprint_results(year, rnd)
                    if sprint_df is not None and not sprint_df.empty:
                        sprint_rounds.add(rnd)
                if sprint_df is not None and not sprint_df.empty:
                    # Temporarily store DataFrame for _apply_sprint_points to consume
                    results_by_driver["__SPRINT_TMP__"] = sprint_df  # type: ignore
                    _apply_sprint_points(year, rnd, results_by_driver, num_to_abbr, collect=sprint_added)
                if sprint_backend:
                    # Accumulate backend provenance in debug (later exposed in payload sprint_backends)
                    debug_points.setdefault("__SPRINT_BACKENDS__", []).append({"round": rnd, "backend": sprint_backend})
            # Debug accumulation
            if debug_code:
                for code_dbg in set(list(race_points_this_round.keys()) + list(sprint_added.keys())):
                    if code_dbg.upper() != debug_code:
                        continue
                    seg = {
                        "round": rnd,
                        "race_points": race_points_this_round.get(code_dbg, 0.0),
                        "sprint_points": sprint_added.get(code_dbg, 0.0),
                        "cumulative": results_by_driver.get(code_dbg, {}).get("points", 0.0)
                    }
                    debug_points.setdefault(code_dbg.upper(), []).append(seg)

        # Stelle sicher, dass auch reine Polesetter im Ergebnis auftauchen
        for code, count in pole_counts.items():
            entry = results_by_driver.get(code)
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
                    "pole_rounds": pole_rounds.get(code, []).copy(),
                }
            else:
                entry["poles"] = int(count)
                entry["pole_rounds"] = pole_rounds.get(code, []).copy()

        # DNFs are already counted per round from the DataFrame's DNF column

        # Finalisieren
        out: Dict[str, Any] = {}
        for code, d in results_by_driver.items():
            positions = d["positions"]
            avg = float(pd.Series(positions).mean()) if positions else None
            full_name = str(d.get("full_name") or code)
            team_name = str(d.get("team") or "")
            team_color = d.get("team_color") or ""
            raw_grid = d.get("grid_position")
            grid_position: int | None
            if raw_grid is not None and not pd.isna(raw_grid):
                try:
                    grid_position = int(raw_grid)
                except (TypeError, ValueError):
                    grid_position = None
            else:
                grid_position = None
            out[code] = {
                # 'name' kept for compatibility with older frontend builds
                "code": code,
                "full_name": full_name,
                "name": full_name,
                "team": team_name,
                "team_color": team_color,
                "grid_position": grid_position,
                "total_points": float(d["points"]),
                "wins": int(d["wins"]),
                "podiums": int(d["podiums"]),
                "dnfs": int(d["dnfs"]),
                "avg_finish": (float(avg) if avg is not None else None),
                "poles": int(pole_counts.get(code, d.get("poles", 0))),
                "pole_rounds": list(d.get("pole_rounds", [])),
            }
        payload: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "season": year,
            "drivers": out,
        }
        if debug_code and debug_points.get(debug_code):
            payload["debug_driver_points"] = debug_points.get(debug_code)
        # Include sprint rounds for transparency
        payload["sprint_rounds"] = sorted(list(sprint_rounds))
        # Include sprint backend provenance if gathered
        if debug_points.get("__SPRINT_BACKENDS__"):
            payload["sprint_backends"] = debug_points.get("__SPRINT_BACKENDS__")
        _save_to_cache(year, payload)
        _mem_put(year, payload)
        response.headers["Cache-Control"] = "public, max-age=86400"
        response.headers["X-Season-Cache"] = "built"
        response.headers["X-Sprint-Rounds"] = ",".join(str(r) for r in sorted(list(sprint_rounds)))
        return payload

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _BUILDING.discard(year)


@router.get("/season-cache")
def season_cache_status() -> Dict[str, Any]:
    """List cached season JSON files (disk + memory) for verification after deployment.
    Returns: { seasons: [ {year, source: memory|disk, drivers, schema_version, file_exists} ] }
    """
    seasons: Dict[int, Dict[str, Any]] = {}
    # Memory entries
    for y, entry in _MEM_SEASON.items():
        payload = entry.get("payload", {})
        seasons[y] = {
            "year": y,
            "source": "memory",
            "drivers": len(payload.get("drivers", {}) or {}),
            "schema_version": payload.get("schema_version"),
            "file_exists": False,
        }
    # Disk: try a reasonable range (could parse directory)
    # Determine cache directory using the same helper indirectly
    try:
        base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "season_cache")
        if os.path.isdir(base_dir):
            for name in os.listdir(base_dir):
                if not name.startswith("season_") or not name.endswith(".json"):
                    continue
                try:
                    year = int(name[len("season_"):-5])
                except Exception:
                    continue
                fpath = os.path.join(base_dir, name)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
                entry = seasons.get(year)
                disk_info = {
                    "year": year,
                    "source": "disk" if entry is None else entry.get("source"),
                    "drivers": len((data or {}).get("drivers", {}) or {}),
                    "schema_version": (data or {}).get("schema_version"),
                    "file_exists": True,
                }
                if entry is None:
                    seasons[year] = disk_info
                else:
                    # Merge: prefer memory but record disk file existence
                    entry["file_exists"] = True
                    entry.setdefault("drivers", disk_info["drivers"])
                    entry.setdefault("schema_version", disk_info["schema_version"])
    except Exception:
        pass
    out_list = sorted(seasons.values(), key=lambda x: x["year"])
    return {"seasons": out_list, "schema_version": SCHEMA_VERSION}
