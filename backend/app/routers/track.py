import os
import time
from typing import Any, Dict, List, Tuple

import fastf1
import pandas as pd
from fastapi import APIRouter, HTTPException
import numpy as np

# Ensure FastF1 cache is enabled (reuses same location as other routers)
default_cache = "C:/Users/claud/.fastf1_cache" if os.name == "nt" else "/data/fastf1_cache"
cache_dir = os.getenv("FASTF1_CACHE", default_cache)
os.makedirs(cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(cache_dir)

router = APIRouter(prefix="/f1", tags=["fastf1-tracks"])

# --- In-memory caches -------------------------------------------------------
# Track list cache: years_spec -> {"data": list, "ts": epoch_seconds}
_TRACK_LIST_CACHE: dict[str, Dict[str, Any]] = {}
_TRACK_LIST_TTL_SECONDS = int(os.getenv("TRACK_LIST_CACHE_TTL", "43200"))  # 12h default

# Track map cache: (year, round_number) -> {"data": payload, "ts": epoch_seconds}
_TRACK_MAP_CACHE: dict[Tuple[int, int], Dict[str, Any]] = {}
_TRACK_MAP_TTL_SECONDS = int(os.getenv("TRACK_MAP_CACHE_TTL", "43200"))  # 12h default
_TRACK_MAP_MAX_ITEMS = int(os.getenv("TRACK_MAP_CACHE_MAX", "200"))

def _track_map_cache_get(year: int, rnd: int) -> Dict[str, Any] | None:
    entry = _TRACK_MAP_CACHE.get((year, rnd))
    if not entry:
        return None
    ts = entry.get("ts")
    if isinstance(ts, (int, float)) and (time.time() - float(ts) <= _TRACK_MAP_TTL_SECONDS):
        return entry.get("data")  # type: ignore
    # stale -> delete
    _TRACK_MAP_CACHE.pop((year, rnd), None)
    return None

def _track_map_cache_put(year: int, rnd: int, data: Dict[str, Any]) -> None:
    # Simple size cap (FIFO-ish) to avoid unbounded growth
    if len(_TRACK_MAP_CACHE) >= _TRACK_MAP_MAX_ITEMS:
        # remove oldest by ts
        oldest_key = None
        oldest_ts = 1e18
        for k, v in _TRACK_MAP_CACHE.items():
            ts = v.get("ts", time.time())
            if ts < oldest_ts:
                oldest_ts = ts
                oldest_key = k
        if oldest_key is not None:
            _TRACK_MAP_CACHE.pop(oldest_key, None)
    _TRACK_MAP_CACHE[(year, rnd)] = {"data": data, "ts": time.time()}


def _safe_str(val: Any) -> str:
    return "" if val is None or (isinstance(val, float) and pd.isna(val)) else str(val)


@router.get("/tracks")
def list_tracks() -> List[Dict[str, Any]]:
    """Return a unique list of tracks for configured seasons.

    Environment variable FASTF1_TRACK_YEARS can be like:
      - "2019-2025" (inclusive range)
      - "2022" (single year)
      - "2018,2020,2024" (comma separated list)
    Fallback default: 2018-2025.
    Cached in-memory until process restart or different FASTF1_TRACK_YEARS value.
    """
    years_env = os.getenv("FASTF1_TRACK_YEARS", "2018-2025").strip()
    
    # Check cache first
    cached_entry = _TRACK_LIST_CACHE.get(years_env)
    if cached_entry:
        ts = cached_entry.get("ts", 0)
        if time.time() - float(ts) <= _TRACK_LIST_TTL_SECONDS:
            return cached_entry.get("data", [])  # Fast cache hit
    
    # Parse years spec
    years: list[int] = []
    try:
        if "," in years_env:
            years = [int(p) for p in years_env.split(",") if p.strip().isdigit()]
        elif "-" in years_env:
            a, b = years_env.split("-", 1)
            ya, yb = int(a), int(b)
            if ya > yb:
                ya, yb = yb, ya
            years = list(range(ya, yb + 1))
        else:
            years = [int(years_env)]
    except Exception:
        years = list(range(2018, 2026))
    if not years:
        years = list(range(2018, 2026))

    # Safety clamp
    years = [y for y in years if 2000 <= y <= 2100]

    # Use a stable per-circuit key: CircuitShortName + Country
    seen_keys: dict[str, Dict[str, Any]] = {}
    for year in years:
        try:
            schedule = fastf1.get_event_schedule(year, include_testing=False)
        except Exception:
            continue
        if schedule is None or schedule.empty:
            continue

        for _, ev in schedule.iterrows():
            rnd = ev.get("RoundNumber")
            if pd.isna(rnd) or int(rnd) <= 0:
                continue
            rnd = int(rnd)
            circuit = _safe_str(ev.get("CircuitShortName")) or _safe_str(ev.get("Location"))
            country = _safe_str(ev.get("Country"))
            if not circuit and not country:
                key = f"{year}-{rnd}"
            else:
                key = f"{circuit}|{country}".strip('|')

            # Build a display name that doesn't include the year
            display_name = circuit or (_safe_str(ev.get("EventName")) or key)

            prev = seen_keys.get(key)
            # Keep the latest year/round for this circuit
            if not prev or year > int(prev.get("year", 0)) or (year == int(prev.get("year", 0)) and rnd > int(prev.get("round", 0))):
                seen_keys[key] = {
                    "key": key,
                    "name": display_name,
                    "year": year,
                    "round": rnd,
                    "country": country,
                    "location": _safe_str(ev.get("Location")),
                }

    items = list(seen_keys.values())
    # Sort by name for nicer UI
    items.sort(key=lambda x: (x.get("name") or ""))
    
    # Cache the result
    _TRACK_LIST_CACHE[years_env] = {"data": items, "ts": time.time()}
    return items


@router.get("/trackmap/{year}/{round_number}")
def get_track_map(year: int, round_number: int) -> Dict[str, Any]:
    """Build a simple track map for the selected event.

    Returns a TrackMap-like structure: { track: [{x,y,distance}], corners: [] }
    Corners are left empty for now; can be enhanced later if circuit data is available.
    """
    # Serve from cache first
    cached = _track_map_cache_get(year, round_number)
    if cached is not None:
        return cached
    def _rotate(xy: list[float] | tuple[float, float], *, angle: float) -> list[float]:
        # Rotation matrix [[cos, sin], [-sin, cos]] used in the example
        c = float(np.cos(angle))
        s = float(np.sin(angle))
        x, y = float(xy[0]), float(xy[1])
        return [x * c + y * s, -x * s + y * c]

    def _build_from_session(ses) -> Dict[str, Any] | None:
        try:
            # Preferred: use CircuitInfo centerline and corners (as shown in FastF1 docs)
            try:
                ci = ses.get_circuit_info()
            except Exception:
                ci = None

            if ci is not None:
                # Track rotation (degrees -> radians)
                try:
                    track_angle = float(getattr(ci, "rotation", 0.0)) / 180.0 * float(np.pi)
                except Exception:
                    track_angle = 0.0
                center = None
                # Try common attribute and method names
                for attr in ("centerline", "center_line", "center"):
                    try:
                        df = getattr(ci, attr)
                        if isinstance(df, pd.DataFrame) and not df.empty:
                            center = df
                            break
                    except Exception:
                        pass
                if center is None and hasattr(ci, "get_centerline"):
                    try:
                        df = ci.get_centerline()
                        if isinstance(df, pd.DataFrame) and not df.empty:
                            center = df
                    except Exception:
                        center = None

                if center is not None and {"X", "Y"}.issubset(set(center.columns)):
                    cdf = center.copy()
                    if "Distance" not in cdf.columns:
                        dx = (cdf["X"].diff()**2 + cdf["Y"].diff()**2) ** 0.5
                        cdf["Distance"] = dx.fillna(0).cumsum()
                    track: List[Dict[str, Any]] = []
                    zs = cdf["Z"] if "Z" in cdf.columns else pd.Series([None] * len(cdf))
                    for x, y, z, d in zip(cdf["X"], cdf["Y"], zs, cdf["Distance"]):
                        if pd.notna(x) and pd.notna(y):
                            rx, ry = _rotate([float(x), float(y)], angle=track_angle)
                            item = {"x": rx, "y": ry, "distance": float(d)}
                            if z is not None and not (isinstance(z, float) and pd.isna(z)):
                                try:
                                    item["z"] = float(z)
                                except Exception:
                                    pass
                            track.append(item)

                    # Corners (if available)
                    corners_out: List[Dict[str, Any]] = []
                    corners_df = None
                    try:
                        df = getattr(ci, "corners")
                        if isinstance(df, pd.DataFrame) and not df.empty:
                            corners_df = df
                    except Exception:
                        corners_df = None
                    if corners_df is not None and not corners_df.empty:
                        # Use schema from FastF1 example
                        offset_vector = [500.0, 0.0]
                        for _, corner in corners_df.iterrows():
                            try:
                                num = corner.get("Number")
                                letter = corner.get("Letter") if "Letter" in corners_df.columns else ""
                                angle_deg = float(corner.get("Angle")) if "Angle" in corners_df.columns and pd.notna(corner.get("Angle")) else 0.0
                                cx = float(corner.get("X"))
                                cy = float(corner.get("Y"))
                                name_val = corner.get("Name") if "Name" in corners_df.columns else corner.get("Description")
                                corner_name = _safe_str(name_val)
                                # Offset for readable label placement
                                offset_angle = angle_deg / 180.0 * float(np.pi)
                                offx, offy = _rotate(offset_vector, angle=offset_angle)
                                text_x = cx + offx
                                text_y = cy + offy
                                # Rotate both label and track positions with track angle
                                tx, ty = _rotate([text_x, text_y], angle=track_angle)
                                px, py = _rotate([cx, cy], angle=track_angle)
                                cnum = f"{int(num)}{str(letter) if letter is not None and not pd.isna(letter) else ''}" if num is not None and pd.notna(num) else ""
                                corners_out.append({
                                    "corner_number": cnum,
                                    "corner_name": corner_name,
                                    "text_position": [tx, ty],
                                    "track_position": [px, py]
                                })
                            except Exception:
                                continue

                    return {"track": track, "corners": corners_out}

            # If centerline is not available, try to load session data including telemetry for fallback
            ses.load(laps=True, telemetry=True, weather=False, messages=False)

            # Fallback: build from a fast lap's position data or telemetry
            laps = ses.laps
            if laps is None or laps.empty:
                return None
            # Pick the fastest valid lap
            try:
                fastest = laps.pick_fastest()
            except Exception:
                fastest = None
            if fastest is None or fastest.empty:
                # fallback: take the first complete timed lap
                timed = laps.dropna(subset=["LapTime"])
                if timed is None or timed.empty:
                    return None
                fastest = timed.iloc[0]

            # Use high-resolution position data (includes X, Y, Z)
            pos = fastest.get_pos_data()
            if pos is None or pos.empty:
                # Fallback to telemetry if pos data is unavailable for this event
                tel = fastest.get_telemetry()
                if tel is None or tel.empty:
                    return None
                if hasattr(tel, "add_distance"):
                    try:
                        tel = tel.add_distance()
                    except Exception:
                        pass
                # Ensure columns exist
                if not {"X", "Y"}.issubset(set(tel.columns)):
                    return None
                # Rotation
                try:
                    ci2 = ses.get_circuit_info()
                    track_angle2 = float(getattr(ci2, "rotation", 0.0)) / 180.0 * float(np.pi)
                except Exception:
                    track_angle2 = 0.0
                # Compute distance if missing
                if "Distance" not in tel.columns:
                    dx = (tel["X"].diff()**2 + tel["Y"].diff()**2) ** 0.5
                    tel = tel.copy()
                    tel["Distance"] = dx.fillna(0).cumsum()
                # Build simple track
                track = []
                for x, y, d in zip(tel["X"], tel["Y"], tel["Distance"]):
                    if pd.notna(x) and pd.notna(y):
                        rx, ry = _rotate([float(x), float(y)], angle=track_angle2)
                        track.append({"x": rx, "y": ry, "distance": float(d)})
                return {"track": track, "corners": []}
            # add distance if method exists
            if hasattr(pos, "add_distance"):
                try:
                    pos = pos.add_distance()
                except Exception:
                    pass

            # Ensure at least X and Y exist; Z is optional
            cols = set(pos.columns)
            if not {"X", "Y"}.issubset(cols):
                return None

            # Rotation
            try:
                ci3 = ses.get_circuit_info()
                track_angle3 = float(getattr(ci3, "rotation", 0.0)) / 180.0 * float(np.pi)
            except Exception:
                track_angle3 = 0.0

            # Compute distance if missing
            if "Distance" not in pos.columns:
                dx = (pos["X"].diff()**2 + pos["Y"].diff()**2) ** 0.5
                pos = pos.copy()
                pos["Distance"] = dx.fillna(0).cumsum()

            # Build track array with optional Z
            zs = pos["Z"] if "Z" in pos.columns else pd.Series([None] * len(pos))
            track = []
            for x, y, z, d in zip(pos["X"], pos["Y"], zs, pos["Distance"]):
                if pd.notna(x) and pd.notna(y):
                    rx, ry = _rotate([float(x), float(y)], angle=track_angle3)
                    item = {"x": rx, "y": ry, "distance": float(d)}
                    if z is not None and not (isinstance(z, float) and pd.isna(z)):
                        try:
                            item["z"] = float(z)
                        except Exception:
                            pass
                    track.append(item)

            # Corners enhancement can be added later; for now keep empty list
            return {"track": track, "corners": []}
        except Exception:
            return None

    # Try a few sessions in order of preference for the requested event
    def _extract_event_meta(sess, default_year: int, default_round: int) -> tuple[int, int]:
        event = getattr(sess, "event", None)
        src_year = default_year
        src_round = default_round
        if event is not None:
            try:
                src_year = int(getattr(event, "year", default_year) or default_year)
            except Exception:
                src_year = default_year
            round_candidate = getattr(event, "RoundNumber", None) or getattr(event, "round", None)
            if round_candidate is not None and not pd.isna(round_candidate):
                try:
                    src_round = int(round_candidate)
                except Exception:
                    src_round = default_round
        return src_year, src_round

    def _try_event(y: int, r: int, names: List[str] | None = None) -> tuple[Dict[str, Any], int, int] | None:
        codes = ("R", "Q", "S", "FP3", "FP2", "FP1")
        # Try by candidate venue names first (e.g., "Silverstone", "Hungary", "Hungarian Grand Prix")
        if names:
            for code in codes:
                for nm in names:
                    if not nm:
                        continue
                    try:
                        ses_local = fastf1.get_session(y, nm, code)
                        res_local = _build_from_session(ses_local)
                        if res_local:
                            src_year, src_round = _extract_event_meta(ses_local, y, r)
                            return res_local, src_year, src_round
                    except Exception:
                        continue
        # Fallback to round number
        for code in codes:
            try:
                ses_local = fastf1.get_session(y, r, code)
                res_local = _build_from_session(ses_local)
                if res_local:
                    src_year, src_round = _extract_event_meta(ses_local, y, r)
                    return res_local, src_year, src_round
            except Exception:
                continue
        return None

    def _get_race_winner(y: int, r: int, names: List[str] | None = None) -> Dict[str, Any] | None:
        identifiers: List[Any] = []
        if r is not None and not pd.isna(r):
            identifiers.append(r)
        if names:
            identifiers.extend([nm for nm in names if nm])

        seen: set[Any] = set()
        for identifier in identifiers:
            if identifier in seen:
                continue
            seen.add(identifier)
            try:
                ses_race = fastf1.get_session(y, identifier, "R")
            except Exception:
                continue
            try:
                ses_race.load(laps=False, telemetry=False, weather=False, messages=False)
            except Exception:
                continue
            results = getattr(ses_race, "results", None)
            if results is None or results.empty:
                continue

            winner = results.iloc[0]
            driver = _safe_str(winner.get("FullName")) or _safe_str(winner.get("BroadcastName")) or _safe_str(winner.get("Driver")) or _safe_str(winner.get("DriverNumber"))
            team = _safe_str(winner.get("TeamName")) or _safe_str(winner.get("ConstructorName"))
            code = _safe_str(winner.get("Abbreviation")) or _safe_str(winner.get("DriverNumber"))

            event = getattr(ses_race, "event", None)
            if event is not None:
                try:
                    year_val = int(getattr(event, "year", y) or y)
                except Exception:
                    year_val = y
                round_candidate = getattr(event, "RoundNumber", None) or getattr(event, "round", None)
                try:
                    round_val = int(round_candidate) if round_candidate is not None and not pd.isna(round_candidate) else r
                except Exception:
                    round_val = r
                event_name = _safe_str(getattr(event, "EventName", ""))
            else:
                year_val = y
                round_val = r
                event_name = ""

            return {
                "year": year_val,
                "round": round_val,
                "driver": driver,
                "team": team,
                "code": code,
                "event": event_name,
            }

        return None

    # Build candidate names for this round (venue/circuit/event), improves odds vs round number only
    name_candidates: List[str] = []
    try:
        sched_now = fastf1.get_event_schedule(year, include_testing=False)
        if sched_now is not None and not sched_now.empty:
            ev_now = sched_now.loc[sched_now['RoundNumber'] == round_number]
            if ev_now is not None and not ev_now.empty:
                ev_now = ev_now.iloc[0]
                for col in ("CircuitShortName", "Location", "EventName", "OfficialEventName"):
                    val = _safe_str(ev_now.get(col))
                    if val:
                        name_candidates.append(val)
    except Exception:
        pass

    result_tuple = _try_event(year, round_number, name_candidates)
    winner_names: List[str] = list(name_candidates)
    source_year = year
    source_round = round_number

    if not result_tuple:
        # Fall back: find the same circuit in other years and try again
        try:
            sched = fastf1.get_event_schedule(year, include_testing=False)
            ev = None
            if sched is not None and not sched.empty:
                ev = sched.loc[sched['RoundNumber'] == round_number]
                if ev is not None and not ev.empty:
                    ev = ev.iloc[0]
        except Exception:
            ev = None

        if ev is not None:
            # Build multiple keys for robust matching across seasons
            circuit = _safe_str(ev.get("CircuitShortName")) or _safe_str(ev.get("Location"))
            country = _safe_str(ev.get("Country"))
            location = _safe_str(ev.get("Location"))
            event_name = _safe_str(ev.get("EventName"))
            keys_target = {
                f"{circuit}|{country}".strip('|'),
                f"{location}|{country}".strip('|'),
                event_name
            }

            for y in range(2025, 2017, -1):
                try:
                    sched_y = fastf1.get_event_schedule(y, include_testing=False)
                except Exception:
                    continue
                if sched_y is None or sched_y.empty:
                    continue
                for _, e2 in sched_y.iterrows():
                    r2 = e2.get("RoundNumber")
                    if pd.isna(r2) or int(r2) <= 0:
                        continue
                    r2 = int(r2)
                    circ2 = _safe_str(e2.get("CircuitShortName")) or _safe_str(e2.get("Location"))
                    ctry2 = _safe_str(e2.get("Country"))
                    loc2 = _safe_str(e2.get("Location"))
                    evn2 = _safe_str(e2.get("EventName"))
                    keys_candidate = {
                        f"{circ2}|{ctry2}".strip('|'),
                        f"{loc2}|{ctry2}".strip('|'),
                        evn2
                    }
                    if keys_target & keys_candidate:
                        fallback_names: List[str] = []
                        for col in ("CircuitShortName", "Location", "EventName", "OfficialEventName"):
                            val = _safe_str(e2.get(col))
                            if val:
                                fallback_names.append(val)
                        result_tuple = _try_event(y, r2, fallback_names)
                        if result_tuple:
                            winner_names = list(fallback_names)
                            break
                if result_tuple:
                    break

    if not result_tuple:
        raise HTTPException(status_code=404, detail="Track map not available for this event or circuit")

    data, source_year, source_round = result_tuple
    winner_info = _get_race_winner(source_year, source_round, winner_names)
    data["winner"] = winner_info

    # Store using the originally requested year/round, not the source (so lookup is stable)
    _track_map_cache_put(year, round_number, data)
    return data