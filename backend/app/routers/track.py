import os
from typing import Any, Dict, List

import fastf1
import pandas as pd
from fastapi import APIRouter, HTTPException
import numpy as np
from fastf1.ergast import Ergast, interface as ergast_interface

# Ensure FastF1 cache is enabled (reuses same location as other routers)
default_cache = "C:/Users/claud/.fastf1_cache" if os.name == "nt" else "/data/fastf1_cache"
cache_dir = os.getenv("FASTF1_CACHE", default_cache)
os.makedirs(cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(cache_dir)

router = APIRouter(prefix="/f1", tags=["fastf1-tracks"])

# Simple in-process cache for track list to avoid repeated schedule scans on cold start
_TRACK_CACHE: dict[str, Any] | None = None
_TRACK_CACHE_YEARS: str | None = None

ERGAST_BASE_URL = os.getenv("ERGAST_BASE_URL", "https://api.jolpi.ca/ergast/f1")
ergast_interface.BASE_URL = ERGAST_BASE_URL


def _safe_str(val: Any) -> str:
    return "" if val is None or (isinstance(val, float) and pd.isna(val)) else str(val)


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
    global _TRACK_CACHE, _TRACK_CACHE_YEARS
    years_env = os.getenv("FASTF1_TRACK_YEARS", "2018-2025").strip()
    if _TRACK_CACHE is not None and _TRACK_CACHE_YEARS == years_env:
        return _TRACK_CACHE["items"]  # type: ignore

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
    items.sort(key=lambda x: (x.get("name") or ""))
    _TRACK_CACHE = {"items": items}
    _TRACK_CACHE_YEARS = years_env
    return items


@router.get("/trackmap/{year}/{round_number}")
def get_track_map(year: int, round_number: int) -> Dict[str, Any]:
    """Build a simple track map for the selected event.

    Returns a TrackMap-like structure: { track: [{x,y,distance}], corners: [] }
    Corners are left empty for now; can be enhanced later if circuit data is available.
    """
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
        if r is None or pd.isna(r):
            return None
        try:
            ergast = Ergast()
            resp = ergast.get_race_results(season=int(y), round=int(r))
        except Exception:
            resp = None
        df = _ergast_to_dataframe(resp)
        if df is None or df.empty:
            return None

        df = df.copy()
        winner_row = None
        if "position" in df.columns:
            df["position"] = pd.to_numeric(df["position"], errors="coerce")
            pos_match = df[df["position"] == 1]
            if pos_match is not None and not pos_match.empty:
                winner_row = pos_match.iloc[0]
        if winner_row is None:
            winner_row = df.iloc[0]

        given = _safe_str(winner_row.get("driverGivenName"))
        family = _safe_str(winner_row.get("driverFamilyName"))
        driver = " ".join(part for part in [given, family] if part).strip()
        if not driver:
            driver = _safe_str(winner_row.get("driverFullName")) or _safe_str(winner_row.get("driverSurname")) or _safe_str(winner_row.get("driverId"))

        team = _safe_str(winner_row.get("constructorName")) or _safe_str(winner_row.get("ConstructorName"))
        code = _safe_str(winner_row.get("driverCode")) or _safe_str(winner_row.get("driverId"))
        event_name = _safe_str(winner_row.get("raceName"))
        if not event_name and names:
            event_name = next((nm for nm in names if nm), "")

        try:
            year_val = int(winner_row.get("season", y))
        except Exception:
            year_val = y
        try:
            round_val = int(winner_row.get("round", r))
        except Exception:
            round_val = r

        return {
            "year": year_val,
            "round": round_val,
            "driver": driver or code,
            "team": team,
            "code": code,
            "event": event_name,
        }

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
    return data
