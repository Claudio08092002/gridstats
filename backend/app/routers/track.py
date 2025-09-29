import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import fastf1
from fastf1.ergast import Ergast, interface as ergast_interface
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/f1", tags=["fastf1-tracks"])

_DEFAULT_FASTF1_CACHE = "C:/Users/claud/.fastf1_cache" if os.name == "nt" else "/data/fastf1_cache"
_fastf1_cache_dir = os.getenv("FASTF1_CACHE", _DEFAULT_FASTF1_CACHE)
os.makedirs(_fastf1_cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(_fastf1_cache_dir)
ERGAST_BASE_URL = os.getenv("ERGAST_BASE_URL")
if ERGAST_BASE_URL:
    ergast_interface.BASE_URL = ERGAST_BASE_URL
else:
    ergast_interface.BASE_URL = "https://api.jolpi.ca/ergast/f1"

_TRACK_CACHE_ROOT = Path(__file__).resolve().parent.parent / "tracks_cache"
_TRACK_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
_TRACK_LIST_PATH = _TRACK_CACHE_ROOT / "tracks_list.json"


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _parse_years() -> List[int]:
    raw = os.getenv("FASTF1_TRACK_YEARS", "2018-2025").strip()
    years: set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            try:
                start_s, end_s = token.split("-", 1)
                start = int(start_s.strip())
                end = int(end_s.strip())
            except Exception:
                continue
            if start > end:
                start, end = end, start
            years.update(range(start, end + 1))
        else:
            try:
                years.add(int(token))
            except Exception:
                continue
    return sorted(years)


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    return str(val)


def _ergast_to_dataframe(resp: Any) -> pd.DataFrame | None:
    if resp is None:
        return None
    if isinstance(resp, pd.DataFrame):
        return resp
    content = getattr(resp, "content", None)
    if not content:
        return None
    frames: List[pd.DataFrame] = []
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


def _build_from_session(session) -> Dict[str, Any] | None:
    def _rotate(xy: List[float] | Tuple[float, float], *, angle: float) -> List[float]:
        x, y = xy
        rx = x * float(np.cos(angle)) - y * float(np.sin(angle))
        ry = x * float(np.sin(angle)) + y * float(np.cos(angle))
        return [rx, ry]

    try:
        circuit_info = None
        try:
            circuit_info = session.get_circuit_info()
        except Exception:
            circuit_info = None

        if circuit_info is not None:
            try:
                rotation = float(getattr(circuit_info, "rotation", 0.0)) / 180.0 * float(np.pi)
            except Exception:
                rotation = 0.0

            center_df = None
            for attr in ("centerline", "center_line", "center"):
                try:
                    data = getattr(circuit_info, attr)
                    if isinstance(data, pd.DataFrame) and not data.empty:
                        center_df = data
                        break
                except Exception:
                    continue
            if center_df is None and hasattr(circuit_info, "get_centerline"):
                try:
                    data = circuit_info.get_centerline()
                    if isinstance(data, pd.DataFrame) and not data.empty:
                        center_df = data
                except Exception:
                    center_df = None

            if center_df is not None and {"X", "Y"}.issubset(center_df.columns):
                cdf = center_df.copy()
                if "Distance" not in cdf.columns:
                    dx = (cdf["X"].diff() ** 2 + cdf["Y"].diff() ** 2) ** 0.5
                    cdf["Distance"] = dx.fillna(0).cumsum()
                track_points: List[Dict[str, Any]] = []
                zs = cdf["Z"] if "Z" in cdf.columns else pd.Series([None] * len(cdf))
                for x, y, z, dist in zip(cdf["X"], cdf["Y"], zs, cdf["Distance"]):
                    if pd.notna(x) and pd.notna(y):
                        rx, ry = _rotate([float(x), float(y)], angle=rotation)
                        point: Dict[str, Any] = {"x": rx, "y": ry, "distance": float(dist)}
                        if z is not None and not (isinstance(z, float) and pd.isna(z)):
                            try:
                                point["z"] = float(z)
                            except Exception:
                                pass
                        track_points.append(point)

                corners_out: List[Dict[str, Any]] = []
                corners_df = None
                try:
                    data = getattr(circuit_info, "corners")
                    if isinstance(data, pd.DataFrame) and not data.empty:
                        corners_df = data
                except Exception:
                    corners_df = None
                if corners_df is not None and not corners_df.empty:
                    offset_vector = [500.0, 0.0]
                    for _, corner in corners_df.iterrows():
                        try:
                            num = corner.get("Number")
                            letter = corner.get("Letter") if "Letter" in corners_df.columns else ""
                            angle = float(corner.get("Angle")) if "Angle" in corners_df.columns and pd.notna(corner.get("Angle")) else 0.0
                            cx = float(corner.get("X"))
                            cy = float(corner.get("Y"))
                            name_val = corner.get("Name") if "Name" in corners_df.columns else corner.get("Description")
                            corner_name = _safe_str(name_val)

                            offset_angle = angle / 180.0 * float(np.pi)
                            offx, offy = _rotate(offset_vector, angle=offset_angle)
                            text_x = cx + offx
                            text_y = cy + offy

                            tx, ty = _rotate([text_x, text_y], angle=rotation)
                            px, py = _rotate([cx, cy], angle=rotation)
                            identifier = ""
                            if num is not None and pd.notna(num):
                                identifier = f"{int(num)}{str(letter) if letter is not None and not pd.isna(letter) else ''}"

                            corners_out.append({
                                "corner_number": identifier,
                                "corner_name": corner_name,
                                "text_position": [tx, ty],
                                "track_position": [px, py],
                            })
                        except Exception:
                            continue

                return {"track": track_points, "corners": corners_out}

        try:
            session.load(laps=True, telemetry=True, weather=False, messages=False)
        except Exception:
            return None

        laps = session.laps
        if laps is None or laps.empty:
            return None
        try:
            fastest = laps.pick_fastest()
        except Exception:
            fastest = None
        if fastest is None or fastest.empty:
            timed = laps.dropna(subset=["LapTime"])
            if timed is None or timed.empty:
                return None
            fastest = timed.iloc[0]

        pos = fastest.get_pos_data()
        if pos is None or pos.empty:
            telemetry = fastest.get_telemetry()
            if telemetry is None or telemetry.empty:
                return None
            if hasattr(telemetry, "add_distance"):
                try:
                    telemetry = telemetry.add_distance()
                except Exception:
                    pass
            if not {"X", "Y"}.issubset(telemetry.columns):
                return None
            rotation = 0.0
            try:
                ci = session.get_circuit_info()
                rotation = float(getattr(ci, "rotation", 0.0)) / 180.0 * float(np.pi)
            except Exception:
                rotation = 0.0
            if "Distance" not in telemetry.columns:
                dx = (telemetry["X"].diff() ** 2 + telemetry["Y"].diff() ** 2) ** 0.5
                telemetry = telemetry.copy()
                telemetry["Distance"] = dx.fillna(0).cumsum()
            track_points = []
            for x, y, dist in zip(telemetry["X"], telemetry["Y"], telemetry["Distance"]):
                if pd.notna(x) and pd.notna(y):
                    rx, ry = _rotate([float(x), float(y)], angle=rotation)
                    track_points.append({"x": rx, "y": ry, "distance": float(dist)})
            return {"track": track_points, "corners": []}

        if hasattr(pos, "add_distance"):
            try:
                pos = pos.add_distance()
            except Exception:
                pass
        if not {"X", "Y"}.issubset(pos.columns):
            return None
        rotation = 0.0
        try:
            ci = session.get_circuit_info()
            rotation = float(getattr(ci, "rotation", 0.0)) / 180.0 * float(np.pi)
        except Exception:
            rotation = 0.0
        if "Distance" not in pos.columns:
            dx = (pos["X"].diff() ** 2 + pos["Y"].diff() ** 2) ** 0.5
            pos = pos.copy()
            pos["Distance"] = dx.fillna(0).cumsum()
        zs = pos["Z"] if "Z" in pos.columns else pd.Series([None] * len(pos))
        track_points = []
        for x, y, z, dist in zip(pos["X"], pos["Y"], zs, pos["Distance"]):
            if pd.notna(x) and pd.notna(y):
                rx, ry = _rotate([float(x), float(y)], angle=rotation)
                point: Dict[str, Any] = {"x": rx, "y": ry, "distance": float(dist)}
                if z is not None and not (isinstance(z, float) and pd.isna(z)):
                    try:
                        point["z"] = float(z)
                    except Exception:
                        pass
                track_points.append(point)
        return {"track": track_points, "corners": []}
    except Exception:
        return None


def _extract_event_meta(session, default_year: int, default_round: int) -> Tuple[int, int]:
    year = default_year
    round_number = default_round
    try:
        event = getattr(session, "event", None)
        if event is not None:
            round_candidate = getattr(event, "RoundNumber", round_number)
            if round_candidate is not None and not pd.isna(round_candidate):
                round_number = int(round_candidate)
            season_candidate = getattr(event, "EventDate", None)
            if season_candidate is not None:
                try:
                    year = int(getattr(event, "EventDate", year).year)
                except Exception:
                    year = int(getattr(event, "EventDate", year)) if isinstance(getattr(event, "EventDate", None), int) else year
    except Exception:
        pass
    return year, round_number


def _try_event(year: int, round_number: int) -> Tuple[Dict[str, Any], int, int] | None:
    for flag in ("R", "Q"):
        try:
            session = fastf1.get_session(year, round_number, flag, backend="fastf1")
        except Exception:
            continue
        built = _build_from_session(session)
        if built:
            src_year, src_round = _extract_event_meta(session, year, round_number)
            return built, src_year, src_round
    return None


def _get_race_winner(year: int, round_number: int, name_hints: List[str] | None = None) -> Dict[str, Any] | None:
    try:
        response = Ergast().get_race_results(season=year, round=round_number)
    except Exception:
        response = None
    df = _ergast_to_dataframe(response)
    if df is not None and not df.empty:
        winner_row = df[df.get("position") == "1"].head(1)
        if winner_row.empty:
            winner_row = df.head(1)
        if not winner_row.empty:
            row = winner_row.iloc[0]
            given = _safe_str(row.get("driverGivenName"))
            family = _safe_str(row.get("driverFamilyName"))
            driver = " ".join(part for part in [given, family] if part).strip()
            if not driver:
                driver = _safe_str(row.get("driverFullName")) or _safe_str(row.get("driverSurname")) or _safe_str(row.get("driverId"))
            team = _safe_str(row.get("constructorName")) or _safe_str(row.get("ConstructorName"))
            code = _safe_str(row.get("driverCode")) or _safe_str(row.get("driverId"))
            event_name = _safe_str(row.get("raceName"))
            return {
                "year": int(row.get("season", year) or year),
                "round": int(row.get("round", round_number) or round_number),
                "driver": driver or code,
                "team": team,
                "code": code,
                "event": event_name,
            }
    if name_hints:
        return {
            "year": year,
            "round": round_number,
            "driver": "",
            "team": "",
            "code": "",
            "event": next((name for name in name_hints if name), ""),
        }
    return None


@router.get("/tracks")
def list_tracks(refresh: bool = False) -> List[Dict[str, Any]]:
    if not refresh:
        cached = _read_json(_TRACK_LIST_PATH)
        if isinstance(cached, dict):
            items = cached.get("tracks")
        else:
            items = cached
        if isinstance(items, list) and items:
            return items

    tracks: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for year in _parse_years():
        try:
            schedule = fastf1.get_event_schedule(year, include_testing=False)
        except Exception:
            continue
        if schedule is None or schedule.empty:
            continue
        schedule = schedule.copy()
        if "RoundNumber" not in schedule.columns:
            continue
        schedule["RoundNumber"] = pd.to_numeric(schedule["RoundNumber"], errors="coerce")
        schedule = schedule.dropna(subset=["RoundNumber"])
        schedule = schedule.sort_values("RoundNumber")
        for _, row in schedule.iterrows():
            rnd_val = row.get("RoundNumber")
            if pd.isna(rnd_val):
                continue
            rnd = int(rnd_val)
            key = f"{year}-{rnd}"
            if key in seen:
                continue
            seen.add(key)
            name = _safe_str(row.get("EventName")) or _safe_str(row.get("OfficialEventName")) or f"Round {rnd}"
            tracks.append({
                "key": key,
                "year": year,
                "round": rnd,
                "name": name,
                "country": _safe_str(row.get("Country")),
                "location": _safe_str(row.get("Location")),
            })
    tracks.sort(key=lambda item: (item["year"], item["round"]))
    _write_json(_TRACK_LIST_PATH, {"tracks": tracks})
    return tracks


@router.get("/trackmap/{year}/{round}")
def get_track_map(year: int, round: int, refresh: bool = False) -> Dict[str, Any]:
    cache_path = _TRACK_CACHE_ROOT / f"trackmap_{year}_{round}.json"
    if not refresh:
        cached = _read_json(cache_path)
        if isinstance(cached, dict) and cached.get("track"):
            return cached

    name_candidates: List[str] = []
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        if schedule is not None and not schedule.empty:
            matches = schedule.loc[schedule["RoundNumber"] == round]
            if matches is not None and not matches.empty:
                match = matches.iloc[0]
                for col in ("CircuitShortName", "Location", "EventName", "OfficialEventName"):
                    val = _safe_str(match.get(col))
                    if val:
                        name_candidates.append(val)
    except Exception:
        pass

    built = _try_event(year, round)
    if not built:
        raise HTTPException(status_code=404, detail="Track map not available")

    data, src_year, src_round = built
    winner = _get_race_winner(src_year, src_round, name_candidates)
    if winner:
        data["winner"] = winner

    _write_json(cache_path, data)
    return data
