import json
import os
import re
import unicodedata
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import fastf1
from fastf1.ergast import Ergast, interface as ergast_interface
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

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

TRACK_LIST_CACHE_VERSION = 3
TRACK_MAP_CACHE_VERSION = 4

_TRACK_CACHE_ROOT = Path(__file__).resolve().parent.parent / "tracks_cache"
_TRACK_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
_TRACK_LIST_PATH = _TRACK_CACHE_ROOT / "tracks_list.json"
_SEASON_CACHE_ROOT = Path(__file__).resolve().parent.parent / "season_cache"

_WINNER_CACHE: Dict[Tuple[int, int], Optional[Dict[str, Any]]] = {}
_ERGAST_RESULT_CACHE: Dict[Tuple[int, int], Optional[pd.DataFrame]] = {}
_ERGAST_FAILURES: set[Tuple[int, int]] = set()

_COUNTRY_CODE_ALIASES: Dict[str, str] = {
    "united_states": "us",
    "united_states_of_america": "us",
    "usa": "us",
    "great_britain": "gb",
    "united_kingdom": "gb",
    "uk": "gb",
    "united_arab_emirates": "ae",
    "abu_dhabi": "ae",
    "bahrain": "bh",
    "qatar": "qa",
    "mexico": "mx",
    "mexico_city": "mx",
    "miami": "us",
    "saudi_arabia": "sa",
    "australia": "au",
    "austria": "at",
    "azerbaijan": "az",
    "belgium": "be",
    "brazil": "br",
    "canada": "ca",
    "china": "cn",
    "france": "fr",
    "germany": "de",
    "hungary": "hu",
    "italy": "it",
    "japan": "jp",
    "monaco": "mc",
    "netherlands": "nl",
    "portugal": "pt",
    "singapore": "sg",
    "south_africa": "za",
    "spain": "es",
    "turkey": "tr",
    "argentina": "ar",
    "emilia_romagna": "it",
    "san_marino": "sm",
    "las_vegas": "us",
    "abu_dhabi_grand_prix": "ae",
}


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


def _normalize_token(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", normalized)
    return normalized.strip("_").lower()


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    return str(val)


def _title_word(word: str) -> str:
    if not word:
        return word
    if word.isupper() and len(word) <= 3:
        return word
    return word.capitalize()


def _format_gp_name(event_name: str, country: str, location: str) -> str:
    base = (event_name or "").strip()
    if not base:
        base = (location or country or "Grand Prix").strip()
    normalized = base
    lowered = normalized.lower()
    if lowered.endswith(" gp"):
        normalized = normalized[:-3].rstrip()
    elif lowered.endswith("-gp"):
        normalized = normalized[:-3].rstrip()
    elif lowered.endswith("grand prix grand prix"):
        normalized = normalized[: -len(" grand prix")]
    if "grand prix" not in normalized.lower():
        normalized = f"{normalized} Grand Prix"
    if normalized.lower().endswith("grand prix"):
        prefix = normalized[:-10].strip()
        if prefix:
            words = [_title_word(part) for part in prefix.split()]
            normalized = " ".join(words + ["Grand Prix"])
        else:
            normalized = "Grand Prix"
    return normalized


def _canonical_country_code(country: str, fallback_location: str = "") -> Optional[str]:
    token = _normalize_token(country)
    if token in _COUNTRY_CODE_ALIASES:
        return _COUNTRY_CODE_ALIASES[token]
    if token:
        parts = token.split("_")
        if parts and parts[0] in _COUNTRY_CODE_ALIASES:
            return _COUNTRY_CODE_ALIASES[parts[0]]
    loc_token = _normalize_token(fallback_location)
    if loc_token in _COUNTRY_CODE_ALIASES:
        return _COUNTRY_CODE_ALIASES[loc_token]
    if token:
        return token[:2]
    if loc_token:
        return loc_token[:2]
    return None


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
    current_year = datetime.utcnow().year
    allowed_max = current_year + 1
    return sorted(year for year in years if year <= allowed_max)

def _parse_winner_years() -> Tuple[int, int]:
    spec = os.getenv("TRACK_WINNER_RANGE", "2018-2025").strip()
    current_year = datetime.utcnow().year
    start = 2018
    end = max(current_year, 2018)
    if spec:
        tokens = [token.strip() for token in spec.split(",") if token.strip()]
        if tokens:
            try:
                first = tokens[0]
                if "-" in first:
                    a, b = first.split("-", 1)
                    start = int(a.strip())
                    end = int(b.strip())
                else:
                    start = int(first)
                    end = start
            except Exception:
                start, end = 2018, max(current_year, 2018)
    if start > end:
        start, end = end, start
    end = max(min(end, current_year), start)
    return start, end


def _load_schedule(year: int) -> Optional[pd.DataFrame]:
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
    except Exception:
        return None
    if schedule is None or schedule.empty or "RoundNumber" not in schedule.columns:
        return None
    frame = schedule.copy()
    frame["RoundNumber"] = pd.to_numeric(frame["RoundNumber"], errors="coerce")
    frame = frame.dropna(subset=["RoundNumber"])
    frame["RoundNumber"] = frame["RoundNumber"].astype(int)
    return frame.sort_values("RoundNumber")


def _build_track_groups() -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for year in _parse_years():
        schedule = _load_schedule(year)
        if schedule is None:
            continue
        for _, row in schedule.iterrows():
            round_number = int(row["RoundNumber"])
            country_raw = _safe_str(row.get("Country"))
            location_raw = _safe_str(row.get("Location"))
            event_name_raw = _safe_str(row.get("EventName")) or _safe_str(row.get("OfficialEventName")) or f"Round {round_number}"
            display_name = _format_gp_name(event_name_raw, country_raw, location_raw)
            group_key = _normalize_token(display_name) or f"{_normalize_token(country_raw)}_{_normalize_token(location_raw)}"
            entry = groups.setdefault(group_key, {
                "display_name": display_name,
                "events": [],
                "name_counts": Counter(),
                "country": country_raw,
                "location": location_raw,
            })
            entry["events"].append({
                "year": year,
                "round": round_number,
                "event_name": display_name,
                "raw_event_name": event_name_raw,
                "country": country_raw,
                "location": location_raw,
                "circuit_short_name": _safe_str(row.get("CircuitShortName")),
            })
            entry["name_counts"][display_name] += 1
            if not entry.get("country"):
                entry["country"] = country_raw
            if not entry.get("location"):
                entry["location"] = location_raw
    return groups


def _load_track_index(refresh: bool = False) -> List[Dict[str, Any]]:
    if not refresh:
        cached = _read_json(_TRACK_LIST_PATH)
        if isinstance(cached, dict) and cached.get("version") == TRACK_LIST_CACHE_VERSION:
            tracks = cached.get("tracks")
            if isinstance(tracks, list):
                return tracks
    groups = _build_track_groups()
    tracks: List[Dict[str, Any]] = []
    for key, data in groups.items():
        events = sorted(data["events"], key=lambda item: (item["year"], item["round"]))
        if not events:
            continue
        latest = events[-1]
        years = sorted({ev["year"] for ev in events})
        display_name = data["name_counts"].most_common(1)[0][0]
        country_display = data.get("country") or ""
        location_display = data.get("location") or ""
        country_code = _canonical_country_code(country_display, location_display)
        rounds_payload = [{
            "year": ev["year"],
            "round": ev["round"],
            "event_name": ev["event_name"],
        } for ev in events]
        track_entry = {
            "key": key,
            "name": display_name,
            "display_name": display_name,
            "country": country_display,
            "country_code": country_code,
            "location": location_display,
            "latest_year": latest["year"],
            "latest_round": latest["round"],
            "years": years,
            "rounds": rounds_payload,
            "events": events,
        }
        tracks.append(track_entry)
    tracks.sort(key=lambda item: item["name"].lower())
    _write_json(_TRACK_LIST_PATH, {"version": TRACK_LIST_CACHE_VERSION, "tracks": tracks})
    return tracks


def _find_track_entry(year: int, round_number: int) -> Optional[Dict[str, Any]]:
    for entry in _load_track_index(refresh=False):
        for ref in entry.get("events", []):
            if ref.get("year") == year and ref.get("round") == round_number:
                return entry
    return None


def list_tracks(refresh: bool = False) -> List[Dict[str, Any]]:
    tracks = _load_track_index(refresh=refresh)
    sanitized: List[Dict[str, Any]] = []
    for entry in tracks:
        clone = {k: v for k, v in entry.items() if k != "events"}
        sanitized.append(clone)
    return sanitized


def _legacy_trackmap_cache_path(year: int, round_number: int) -> Path:
    return _TRACK_CACHE_ROOT / f"trackmap_{year}_{round_number}.json"


def _sanitize_cache_key(track_key: str) -> str:
    token = _normalize_token(track_key)
    if token:
        return token
    fallback = re.sub(r"[^a-z0-9]+", "_", (track_key or "track").lower()).strip("_")
    return fallback or "track"


def _trackmap_cache_path_for_track(track_key: str) -> Path:
    return _TRACK_CACHE_ROOT / f"trackmap_{_sanitize_cache_key(track_key)}.json"


def _track_cache_entry_key(year: int, round_number: int) -> str:
    return f"{int(year)}-{int(round_number)}"


def _sanitize_map_payload(payload: Dict[str, Any], include_metadata: bool = False) -> Optional[Dict[str, Any]]:
    """
    Sanitize track map payload for caching.
    
    Args:
        payload: Raw track map data
        include_metadata: If True, include winners, layout_variants, and layout_years for frontend
    """
    if not isinstance(payload, dict):
        return None
    track_points = payload.get("track") or []
    if not isinstance(track_points, list) or not track_points:
        return None
    sanitized: Dict[str, Any] = {
        "track": deepcopy(track_points),
        "corners": deepcopy(payload.get("corners") or []),
    }
    for key in ("layout_length", "layout_label", "layout_signature", "circuit_name"):
        if key in payload:
            sanitized[key] = payload.get(key)
    try:
        sanitized["year"] = int(payload.get("year"))
    except Exception:
        pass
    try:
        sanitized["round"] = int(payload.get("round"))
    except Exception:
        pass
    
    # Include metadata for enhanced frontend cache
    if include_metadata:
        if "winners" in payload:
            sanitized["winners"] = deepcopy(payload.get("winners"))
        if "winner" in payload:
            sanitized["winner"] = deepcopy(payload.get("winner"))
        if "layout_variants" in payload:
            sanitized["layout_variants"] = deepcopy(payload.get("layout_variants"))
        if "layout_years" in payload:
            sanitized["layout_years"] = deepcopy(payload.get("layout_years"))
    
    return sanitized


def _load_track_cache_bundle(track_key: str) -> Tuple[Dict[str, Any], Path]:
    path = _trackmap_cache_path_for_track(track_key)
    cached = _read_json(path)
    if isinstance(cached, dict) and cached.get("_cache_version") == TRACK_MAP_CACHE_VERSION:
        entries = cached.get("entries")
        if isinstance(entries, dict):
            cached.setdefault("track_key", track_key)
            return cached, path
    return {"track_key": track_key, "entries": {}}, path


def _store_track_cache_bundle(track_key: str, cache: Dict[str, Any]) -> None:
    clone = dict(cache)
    clone["track_key"] = track_key
    clone["_cache_version"] = TRACK_MAP_CACHE_VERSION
    _write_json(_trackmap_cache_path_for_track(track_key), clone)


def _load_cached_map_entry(track_key: str, year: int, round_number: int) -> Optional[Dict[str, Any]]:
    cache, _ = _load_track_cache_bundle(track_key)
    entries: Dict[str, Any] = cache.setdefault("entries", {})
    key = _track_cache_entry_key(year, round_number)
    entry = entries.get(key)
    if isinstance(entry, dict) and entry.get("track"):
        return deepcopy(entry)
    legacy = _read_json(_legacy_trackmap_cache_path(year, round_number))
    if isinstance(legacy, dict) and legacy.get("track"):
        legacy = dict(legacy)
        legacy.pop("_cache_version", None)
    sanitized = _sanitize_map_payload(legacy) if isinstance(legacy, dict) else None
    if sanitized:
        entries[key] = sanitized
        _store_track_cache_bundle(track_key, cache)
        return deepcopy(sanitized)
    return None


def _store_cached_map_entry(track_key: str, year: int, round_number: int, payload: Dict[str, Any]) -> None:
    sanitized = _sanitize_map_payload(payload)
    if not sanitized:
        return
    cache, _ = _load_track_cache_bundle(track_key)
    entries: Dict[str, Any] = cache.setdefault("entries", {})
    entries[_track_cache_entry_key(year, round_number)] = sanitized
    _store_track_cache_bundle(track_key, cache)
    legacy_path = _legacy_trackmap_cache_path(year, round_number)
    if legacy_path.exists():
        try:
            legacy_path.unlink()
        except Exception:  # pragma: no cover - best effort cleanup
            pass


def _ensure_corner_identifier(identifier: str, index: int) -> str:
    ident = (identifier or "").strip()
    return ident if ident else str(index + 1)


def _build_from_session(session) -> Optional[Dict[str, Any]]:
    def _rotate(xy: Tuple[float, float], *, angle: float) -> Tuple[float, float]:
        x, y = xy
        rx = x * float(np.cos(angle)) - y * float(np.sin(angle))
        ry = x * float(np.sin(angle)) + y * float(np.cos(angle))
        return rx, ry

    try:
        circuit_info = None
        try:
            circuit_info = session.get_circuit_info()
        except Exception:
            circuit_info = None

        rotation = 0.0
        if circuit_info is not None:
            try:
                rotation = float(getattr(circuit_info, "rotation", 0.0)) / 180.0 * float(np.pi)
            except Exception:
                rotation = 0.0

        track_points: List[Dict[str, Any]] = []
        corners_out: List[Dict[str, Any]] = []
        corners_df = None  # Declare at function scope so both paths can populate it

        def _append_points(df: pd.DataFrame) -> None:
            xs = df.get("X")
            ys = df.get("Y")
            distances = df.get("Distance")
            zs = df.get("Z") if "Z" in df.columns else pd.Series([None] * len(df))
            for x, y, z, dist in zip(xs, ys, zs, distances):
                if pd.notna(x) and pd.notna(y):
                    rx, ry = _rotate((float(x), float(y)), angle=rotation)
                    point: Dict[str, Any] = {"x": rx, "y": ry, "distance": float(dist)}
                    if z is not None and not (isinstance(z, float) and pd.isna(z)):
                        try:
                            point["z"] = float(z)
                        except Exception:
                            pass
                    track_points.append(point)

        if circuit_info is not None:
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
                _append_points(cdf)

                # Extract corners_df but don't process yet - will process at end
                try:
                    data = getattr(circuit_info, "corners")
                    if isinstance(data, pd.DataFrame) and not data.empty:
                        corners_df = data
                except Exception:
                    pass
        if not track_points:
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
                if hasattr(fastest, "get_telemetry"):
                    telemetry = fastest.get_telemetry()
                    if telemetry is not None and not telemetry.empty:
                        pos = telemetry
            if pos is None or pos.empty:
                return None
            if hasattr(pos, "add_distance"):
                try:
                    pos = pos.add_distance()
                except Exception:
                    pass
            if "Distance" not in pos.columns:
                dx = (pos["X"].diff() ** 2 + pos["Y"].diff() ** 2) ** 0.5
                pos = pos.copy()
                pos["Distance"] = dx.fillna(0).cumsum()
            # Update rotation and get corners from circuit_info if available
            try:
                ci = session.get_circuit_info()
                rotation = float(getattr(ci, "rotation", 0.0)) / 180.0 * float(np.pi)
                # Also try to get corners from circuit_info in fallback path
                try:
                    data = getattr(ci, "corners")
                    if isinstance(data, pd.DataFrame) and not data.empty:
                        corners_df = data
                except Exception:
                    pass
            except Exception:
                pass  # Keep rotation from earlier initialization
            zs = pos["Z"] if "Z" in pos.columns else pd.Series([None] * len(pos))
            for x, y, z, dist in zip(pos["X"], pos["Y"], zs, pos["Distance"]):
                if pd.notna(x) and pd.notna(y):
                    rx, ry = _rotate((float(x), float(y)), angle=rotation)
                    point: Dict[str, Any] = {"x": rx, "y": ry, "distance": float(dist)}
                    if z is not None and not (isinstance(z, float) and pd.isna(z)):
                        try:
                            point["z"] = float(z)
                        except Exception:
                            pass
                    track_points.append(point)

        # Process corners if we found them (works for both circuit_info and telemetry fallback paths)
        if corners_df is not None and not corners_df.empty:
            offset_vector = np.array([500.0, 0.0])
            for idx, corner in corners_df.iterrows():
                try:
                    corner_num = corner.get("Number")
                    letter = corner.get("Letter") if "Letter" in corners_df.columns else ""
                    angle = float(corner.get("Angle")) if "Angle" in corners_df.columns and pd.notna(corner.get("Angle")) else 0.0
                    cx = float(corner.get("X"))
                    cy = float(corner.get("Y"))
                    name_val = corner.get("Name") if "Name" in corners_df.columns else corner.get("Description")
                    corner_name = _safe_str(name_val)

                    offset_angle = angle / 180.0 * float(np.pi)
                    rot_matrix = np.array([
                        [np.cos(offset_angle), -np.sin(offset_angle)],
                        [np.sin(offset_angle), np.cos(offset_angle)],
                    ])
                    text_offset = rot_matrix @ offset_vector
                    text_x = cx + text_offset[0]
                    text_y = cy + text_offset[1]

                    tx, ty = _rotate((text_x, text_y), angle=rotation)
                    px, py = _rotate((cx, cy), angle=rotation)
                    identifier = ""
                    if corner_num is not None and not pd.isna(corner_num):
                        identifier = f"{int(corner_num)}{str(letter) if letter is not None and not pd.isna(letter) else ''}"
                    identifier = _ensure_corner_identifier(identifier, idx)

                    corners_out.append({
                        "corner_number": identifier,
                        "corner_name": corner_name,
                        "text_position": [tx, ty],
                        "track_position": [px, py],
                    })
                except Exception:
                    continue

        if not track_points:
            return None

        layout_distance = float(track_points[-1].get("distance", 0.0)) if track_points else 0.0
        layout_length = _calculate_layout_length(track_points)
        event = getattr(session, "event", None)
        event_name = _safe_str(getattr(event, "EventName", ""))
        circuit_short = _safe_str(getattr(event, "CircuitShortName", ""))
        circuit_location = _safe_str(getattr(event, "Location", ""))
        signature_name = circuit_short or circuit_location or event_name or "Unknown Circuit"
        display_name = event_name or circuit_short or circuit_location or signature_name
        layout_label = display_name
        if layout_length:
            layout_label = f"{display_name} ({layout_length:.3f} km)"
        layout_signature = f"{_normalize_token(signature_name) or 'layout'}:{int(round(layout_length * 1000)) if layout_length else 0}"

        return {
            "track": track_points,
            "corners": corners_out,
            "layout_length": layout_length or None,
            "layout_label": layout_label,
            "layout_signature": layout_signature,
            "circuit_name": signature_name,
        }
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
            if hasattr(season_candidate, "year"):
                year = int(season_candidate.year)
    except Exception:
        pass
    return year, round_number


def _try_event(year: int, round_number: int) -> Optional[Tuple[Dict[str, Any], int, int]]:
    for flag in ("R", "Q"):
        try:
            session = fastf1.get_session(year, round_number, flag, backend="fastf1")
        except Exception:
            continue
        built = _build_from_session(session)
        if built:
            src_year, src_round = _extract_event_meta(session, year, round_number)
            built["year"] = src_year
            built["round"] = src_round
            return built, src_year, src_round
    return None


def _build_track_map_from_source(year: int, round_number: int) -> Dict[str, Any]:
    built = _try_event(year, round_number)
    if not built:
        raise HTTPException(status_code=404, detail="Track map not available")
    data, src_year, src_round = built
    data["year"] = src_year
    data["round"] = src_round
    return data


def _load_track_map_core(track_key: str, year: int, round_number: int, refresh: bool = False) -> Dict[str, Any]:
    if not refresh:
        cached = _load_cached_map_entry(track_key, year, round_number)
        if cached:
            print(f"[CACHE HIT] Loaded {track_key} {year}-{round_number} from cache")
            return cached
        print(f"[CACHE MISS] Building {track_key} {year}-{round_number} from FastF1")
    else:
        print(f"[REFRESH] Rebuilding {track_key} {year}-{round_number} from FastF1")
    data = _build_track_map_from_source(year, round_number)
    sanitized = _sanitize_map_payload(data) or data
    src_year = sanitized.get("year", year) if isinstance(sanitized, dict) else year
    src_round = sanitized.get("round", round_number) if isinstance(sanitized, dict) else round_number
    _store_cached_map_entry(track_key, src_year, src_round, sanitized if isinstance(sanitized, dict) else data)
    print(f"[CACHE SAVE] Saved {track_key} {src_year}-{src_round} to cache")
    return sanitized if isinstance(sanitized, dict) else data


def _winner_from_season_cache(year: int, round_number: int) -> Optional[Dict[str, Any]]:
    season_path = _SEASON_CACHE_ROOT / f"season_{year}.json"
    season_payload = _read_json(season_path)
    if not isinstance(season_payload, dict):
        return None
    driver_index = season_payload.get("drivers") if isinstance(season_payload.get("drivers"), dict) else {}
    candidates: Iterable[Any] = season_payload.get("races") or season_payload.get("events") or season_payload.get("rounds") or []
    for race in candidates:
        if not isinstance(race, dict):
            continue
        round_value = race.get("round") or race.get("RoundNumber") or race.get("round_number")
        try:
            if round_value is None or int(round_value) != round_number:
                continue
        except Exception:
            continue
        winner_info = race.get("winner")
        if isinstance(winner_info, dict) and winner_info:
            driver = _safe_str(winner_info.get("driver")) or _safe_str(winner_info.get("Driver"))
            if not driver:
                given = _safe_str(winner_info.get("givenName"))
                family = _safe_str(winner_info.get("familyName"))
                driver = " ".join(part for part in [given, family] if part)
            team = _safe_str(winner_info.get("team")) or _safe_str(winner_info.get("constructor"))
            code = _safe_str(winner_info.get("code"))
            event_name = _safe_str(winner_info.get("event")) or _safe_str(race.get("event_name"))
            if driver or team:
                return {
                    "year": year,
                    "round": round_number,
                    "driver": _resolve_driver_full_name(driver, code, driver_index),
                    "team": team,
                    "code": code,
                    "event": event_name,
                }
        results = race.get("results") or race.get("classification") or race.get("finishers")
        if isinstance(results, list):
            winner_row = None
            for item in results:
                if not isinstance(item, dict):
                    continue
                pos = item.get("position") or item.get("Position")
                if str(pos).strip() in {"1", "1.0"}:
                    winner_row = item
                    break
            if winner_row is None and results:
                winner_row = results[0]
            if winner_row:
                given = _safe_str(winner_row.get("driverGivenName")) or _safe_str(winner_row.get("givenName"))
                family = _safe_str(winner_row.get("driverFamilyName")) or _safe_str(winner_row.get("familyName"))
                driver = " ".join(part for part in [given, family] if part).strip()
                if not driver:
                    driver = _safe_str(winner_row.get("driver")) or _safe_str(winner_row.get("driverFullName")) or _safe_str(winner_row.get("driverSurname"))
                team = _safe_str(winner_row.get("constructorName")) or _safe_str(winner_row.get("team"))
                code = _safe_str(winner_row.get("driverCode")) or _safe_str(winner_row.get("code"))
                event_name = _safe_str(winner_row.get("raceName")) or _safe_str(race.get("event_name"))
                if driver:
                    return {
                        "year": year,
                        "round": round_number,
                        "driver": _resolve_driver_full_name(driver, code, driver_index),
                        "team": team,
                        "code": code,
                        "event": event_name,
                    }
    return None


def _ergast_to_dataframe(resp: Any) -> Optional[pd.DataFrame]:
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


def _winner_from_ergast(year: int, round_number: int) -> Optional[Dict[str, Any]]:
    key = (year, round_number)
    if key in _ERGAST_RESULT_CACHE:
        df = _ERGAST_RESULT_CACHE[key]
    else:
        try:
            response = Ergast().get_race_results(season=year, round=round_number)
        except Exception:
            _ERGAST_FAILURES.add(key)
            _ERGAST_RESULT_CACHE[key] = None
            return None
        df = _ergast_to_dataframe(response)
        _ERGAST_RESULT_CACHE[key] = df
    if df is None or df.empty:
        return None
    winner_row = df[df.get("position") == "1"].head(1)
    if winner_row.empty:
        winner_row = df.head(1)
    if winner_row.empty:
        return None
    row = winner_row.iloc[0]
    given = _safe_str(row.get("driverGivenName"))
    family = _safe_str(row.get("driverFamilyName"))
    driver = " ".join(part for part in [given, family] if part).strip()
    if not driver:
        driver = _safe_str(row.get("driverFullName")) or _safe_str(row.get("driverSurname")) or _safe_str(row.get("driverId"))
    team = _safe_str(row.get("constructorName")) or _safe_str(row.get("ConstructorName"))
    code = _safe_str(row.get("driverCode")) or _safe_str(row.get("driverId"))
    event_name = _safe_str(row.get("raceName"))
    
    season_path = _SEASON_CACHE_ROOT / f"season_{year}.json"
    season_payload = _read_json(season_path)
    driver_index = season_payload.get("drivers") if isinstance(season_payload, dict) and isinstance(season_payload.get("drivers"), dict) else {}
    
    return {
        "year": int(row.get("season", year) or year),
        "round": int(row.get("round", round_number) or round_number),
        "driver": _resolve_driver_full_name(driver or code, code, driver_index),
        "team": team,
        "code": code,
        "event": event_name,
    }


def _get_race_winner(year: int, round_number: int, name_hints: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    key = (year, round_number)
    if key in _WINNER_CACHE:
        return _WINNER_CACHE[key]
    winner = _winner_from_season_cache(year, round_number)
    if winner:
        _WINNER_CACHE[key] = winner
        return winner
    winner = _winner_from_ergast(year, round_number)
    if winner:
        _WINNER_CACHE[key] = winner
        return winner
    if name_hints:
        placeholder = {
            "year": year,
            "round": round_number,
            "driver": f"Race not yet run ({year})",
            "team": "",
            "code": "",
            "event": next((hint for hint in name_hints if hint), ""),
        }
        _WINNER_CACHE[key] = placeholder
        return placeholder
    _WINNER_CACHE[key] = None
    return None


def _collect_winners(track_entry: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not track_entry:
        return []
    start, end = _parse_winner_years()
    winners: List[Dict[str, Any]] = []
    for event in track_entry.get("events", []):
        year = int(event.get("year"))
        if year < start or year > end:
            continue
        round_number = int(event.get("round"))
        name_hints = [event.get("event_name"), event.get("raw_event_name"), event.get("location"), event.get("country")]
        winner = _get_race_winner(year, round_number, name_hints)
        if winner:
            winners.append(winner)
    winners.sort(key=lambda item: (item.get("year", 0), item.get("round", 0)))
    return winners


def _collect_layout_variants(track_entry: Optional[Dict[str, Any]], current_signature: str) -> Tuple[List[Dict[str, Any]], List[int]]:
    """
    Collect layout variants from CACHE ONLY - no HTTP requests.
    This ensures the track maps work completely offline like driver comparison.
    """
    if not track_entry:
        return [], []
    
    track_key = track_entry.get("key")
    if not track_key:
        return [], []
    
    # Load cache bundle - ONLY use cached data
    cache_bundle, _ = _load_track_cache_bundle(track_key)
    cached_entries = cache_bundle.get("entries", {}) if isinstance(cache_bundle, dict) else {}
    
    variants: Dict[str, Dict[str, Any]] = {}
    
    # Only process events that exist in cache - skip missing ones silently
    for event in track_entry.get("events", []):
        year = int(event.get("year"))
        round_number = int(event.get("round"))
        entry_key = f"{year}-{round_number}"
        
        # Check if this event is cached
        cached_entry = cached_entries.get(entry_key)
        if not cached_entry or not isinstance(cached_entry, dict):
            # Skip events not in cache - no HTTP requests
            continue
        
        map_data = cached_entry
        signature = map_data.get("layout_signature") or f"{year}:{round_number}"
        info = variants.setdefault(signature, {
            "layout_signature": signature,
            "layout_label": map_data.get("layout_label"),
            "layout_length": map_data.get("layout_length"),
            "circuit_name": map_data.get("circuit_name"),
            "years": set(),
            "rounds": set(),
            "signatures": set(),
        })
        info.setdefault("layout_label", map_data.get("layout_label"))
        info.setdefault("layout_length", map_data.get("layout_length"))
        info.setdefault("circuit_name", map_data.get("circuit_name"))
        info["years"].add(year)
        info["rounds"].add((year, round_number))
        info["signatures"].add(signature)

    raw_variants: List[Dict[str, Any]] = []
    for signature, info in variants.items():
        years_sorted = sorted(info.get("years", []))
        rounds_sorted = sorted(info.get("rounds", []), key=lambda item: (item[0], item[1]))
        rounds_payload = [{"year": yr, "round": rnd} for yr, rnd in rounds_sorted]
        raw_variants.append({
            "layout_signature": signature,
            "layout_label": info.get("layout_label"),
            "layout_length": info.get("layout_length"),
            "circuit_name": info.get("circuit_name"),
            "years": years_sorted,
            "rounds": rounds_payload,
            "_aliases": info.get("signatures", {signature}),
        })

    collapsed_variants, layout_years = _collapse_layout_variants(raw_variants, current_signature)
    if not layout_years and current_signature:
        for variant in raw_variants:
            if variant.get("layout_signature") == current_signature:
                layout_years = variant.get("years", [])
                break
    return collapsed_variants, layout_years


def _finalize_map_payload(base: Dict[str, Any], track_entry: Optional[Dict[str, Any]], include_layouts: bool) -> Dict[str, Any]:
    data = dict(base)
    winners = _collect_winners(track_entry)
    data["winners"] = winners
    data["winner"] = winners[-1] if winners else None
    layout_variants: List[Dict[str, Any]] = []
    layout_years: List[int] = []
    if include_layouts and track_entry:
        layout_variants, layout_years = _collect_layout_variants(track_entry, data.get("layout_signature", ""))
    data["layout_variants"] = layout_variants if include_layouts else []
    if layout_years:
        data["layout_years"] = layout_years
    elif data.get("year"):
        data["layout_years"] = [data["year"]]
    return data


@router.get("/tracks")
def get_tracks(refresh: bool = False) -> List[Dict[str, Any]]:
    return list_tracks(refresh=refresh)


@router.get("/trackmap/{year}/{round}")
def get_track_map(year: int, round: int, refresh: bool = False, include_layouts: bool = Query(True, description="Include layout variants across seasons")) -> Dict[str, Any]:
    try:
        track_entry = _find_track_entry(year, round)
        track_key_hint = track_entry.get("key") if track_entry else None
        
        print(f"[GET TRACKMAP] Requested {year}-{round}, track_key_hint={track_key_hint}")
        
        base, resolved_entry, _ = _load_track_map_with_fallback(
            year,
            round,
            track_entry,
            refresh=refresh,
            track_key_hint=track_key_hint,
        )
        final_entry = resolved_entry or track_entry or _find_track_entry(base.get("year", year), base.get("round", round))
        enriched = _finalize_map_payload(base, final_entry, include_layouts=True)
        
        print(f"[GET TRACKMAP] Success for {year}-{round}")
        
        if not include_layouts:
            trimmed = dict(enriched)
            trimmed["layout_variants"] = []
            return trimmed
        return enriched
    except Exception as e:
        print(f"[GET TRACKMAP ERROR] Failed to load {year}-{round}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise


@router.get("/tracks/cache-status")
def check_cache_status() -> Dict[str, Any]:
    """Check which tracks have cache files"""
    tracks = _load_track_index(refresh=False)
    
    status = []
    for track in tracks:
        track_key = track.get("key")
        track_name = track.get("display_name", track_key)
        cache_path = _trackmap_cache_path_for_track(track_key)
        
        events = track.get("events", [])
        cached_count = 0
        
        if cache_path.exists():
            cache_bundle = _read_json(cache_path)
            if isinstance(cache_bundle, dict):
                cached_entries = cache_bundle.get("entries", {})
                cached_count = len(cached_entries)
        
        status.append({
            "track": track_name,
            "track_key": track_key,
            "total_events": len(events),
            "cached_events": cached_count,
            "cache_file_exists": cache_path.exists(),
            "cache_file_path": str(cache_path)
        })
    
    return {
        "total_tracks": len(tracks),
        "tracks": status
    }


@router.get("/tracks/warmup")
def warmup_all_tracks(enhanced: bool = True) -> Dict[str, Any]:
    """
    Pre-populate cache for ALL tracks and ALL layouts.
    This allows the app to work completely offline (like driver comparison).
    
    Args:
        enhanced: If True, also populate winners and layout metadata for frontend
    
    Call this endpoint manually before deployment to ensure all cache files are populated.
    Just open http://localhost:8000/api/f1/tracks/warmup in your browser.
    """
    print("\n" + "="*60)
    print(f"[WARMUP] Starting track cache warmup (enhanced={enhanced})...")
    print("="*60 + "\n")
    # Use _load_track_index instead of list_tracks to get events
    tracks = _load_track_index(refresh=False)
    print(f"[WARMUP] Found {len(tracks)} tracks to process\n")
    
    total_tracks = len(tracks)
    total_events = 0
    cached_events = 0
    loaded_events = 0
    enhanced_events = 0
    failed_events = 0
    
    results = []
    
    for track in tracks:
        track_key = track.get("key")
        track_name = track.get("display_name", track_key)
        events = track.get("events", [])
        total_events += len(events)
        
        track_result = {
            "track": track_name,
            "track_key": track_key,
            "total_events": len(events),
            "loaded": 0,
            "cached": 0,
            "enhanced": 0,
            "failed": 0,
            "errors": []
        }
        
        for event in events:
            year = int(event.get("year"))
            round_number = int(event.get("round"))
            
            try:
                # Try cache first
                cached = _load_cached_map_entry(track_key, year, round_number)
                if cached and not enhanced:
                    cached_events += 1
                    track_result["cached"] += 1
                    continue
                
                if cached and enhanced:
                    # Check if cache already has metadata
                    has_metadata = (
                        cached.get("winners") is not None or
                        cached.get("layout_variants") is not None
                    )
                    if has_metadata:
                        cached_events += 1
                        track_result["cached"] += 1
                        continue
                
                # Load from FastF1 and cache it
                map_data, _, _ = _load_track_map_with_fallback(
                    year, 
                    round_number, 
                    track, 
                    refresh=False, 
                    track_key_hint=track_key
                )
                
                if enhanced:
                    # Add metadata (winners, layout_variants, layout_years)
                    finalized = _finalize_map_payload(map_data, track, include_layouts=True)
                    # Re-save with metadata
                    sanitized_enhanced = _sanitize_map_payload(finalized, include_metadata=True)
                    if sanitized_enhanced:
                        src_year = sanitized_enhanced.get("year", year)
                        src_round = sanitized_enhanced.get("round", round_number)
                        _store_cached_map_entry(track_key, src_year, src_round, sanitized_enhanced)
                        enhanced_events += 1
                        track_result["enhanced"] += 1
                        print(f"[WARMUP] Enhanced {track_key} {year}-{round_number} with metadata")
                    else:
                        loaded_events += 1
                        track_result["loaded"] += 1
                else:
                    loaded_events += 1
                    track_result["loaded"] += 1
                
            except Exception as exc:
                failed_events += 1
                track_result["failed"] += 1
                error_msg = f"{year}-{round_number}: {str(exc)}"
                track_result["errors"].append(error_msg)
                print(f"[WARMUP ERROR] {track_name} {error_msg}")
        
        results.append(track_result)
        if enhanced:
            print(f"[WARMUP] {track_name}: {track_result['enhanced']} enhanced, {track_result['loaded']} loaded, {track_result['cached']} cached, {track_result['failed']} failed")
        else:
            print(f"[WARMUP] {track_name}: {track_result['loaded']} loaded, {track_result['cached']} cached, {track_result['failed']} failed")
    
    print("\n" + "="*60)
    if enhanced:
        print(f"[WARMUP] Completed! {enhanced_events} enhanced, {loaded_events} loaded, {cached_events} cached, {failed_events} failed")
    else:
        print(f"[WARMUP] Completed! {loaded_events} newly loaded, {cached_events} already cached, {failed_events} failed")
    print("="*60 + "\n")
    
    return {
        "status": "completed",
        "mode": "enhanced" if enhanced else "basic",
        "summary": {
            "total_tracks": total_tracks,
            "total_events": total_events,
            "already_cached": cached_events,
            "newly_loaded": loaded_events,
            "enhanced_with_metadata": enhanced_events if enhanced else 0,
            "failed": failed_events
        },
        "tracks": results
    }


def _normalize_driver_name(name: str) -> str:
    text = (name or "").strip()
    if not text:
        return ""
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text)
    tokens = text.split(" ")
    normalized_tokens: List[str] = []
    for token in tokens:
        piece = token.strip()
        if not piece:
            continue
        if piece.isupper() and len(piece) <= 4:
            normalized_tokens.append(piece)
        elif piece.isupper() or piece.islower():
            normalized_tokens.append(piece.capitalize())
        else:
            normalized_tokens.append(piece[0].upper() + piece[1:])
    return " ".join(normalized_tokens)


def _resolve_driver_full_name(
    raw_name: str,
    code: str,
    driver_index: Optional[Dict[str, Any]] = None,
) -> str:
    normalized = _normalize_driver_name(raw_name)
    if normalized and " " in normalized:
        return normalized

    code_token = (code or "").strip().upper()
    index = driver_index or {}
    if code_token and isinstance(index, dict):
        data = index.get(code_token)
        if isinstance(data, dict):
            candidate = _safe_str(data.get("full_name")) or _safe_str(data.get("name"))
            if candidate:
                return _normalize_driver_name(candidate)

    normalized_lower = normalized.lower()
    if normalized_lower and isinstance(index, dict):
        for entry in index.values():
            if not isinstance(entry, dict):
                continue
            candidate = _safe_str(entry.get("full_name")) or _safe_str(entry.get("name"))
            if not candidate:
                continue
            candidate_lower = candidate.lower()
            if normalized_lower == candidate_lower or normalized_lower in candidate_lower:
                return _normalize_driver_name(candidate)

    if code_token and code_token.isalpha() and len(code_token) == 3:
        # As a last resort, keep code-style uppercase tokens.
        return code_token

    return normalized


def _convert_distance_units(value: float) -> float:
    if value <= 0:
        return 0.0
    if value > 20000:
        return value / 10000.0
    if value > 200:
        return value / 1000.0
    return value


def _polyline_length(points: List[Dict[str, Any]]) -> float:
    if not points:
        return 0.0
    total = 0.0
    prev_x: Optional[float] = None
    prev_y: Optional[float] = None
    for point in points:
        try:
            x = float(point.get("x", 0.0))
            y = float(point.get("y", 0.0))
        except Exception:
            continue
        if prev_x is not None and prev_y is not None:
            total += float(np.hypot(x - prev_x, y - prev_y))
        prev_x, prev_y = x, y
    if prev_x is not None and prev_y is not None:
        try:
            first_x = float(points[0].get("x", prev_x))
            first_y = float(points[0].get("y", prev_y))
            closing = float(np.hypot(prev_x - first_x, prev_y - first_y))
            if closing > 1.0:
                total += closing
        except Exception:
            pass
    return total


def _calculate_layout_length(points: List[Dict[str, Any]]) -> float:
    if not points:
        return 0.0
    last_distance = 0.0
    for point in reversed(points):
        raw = point.get("distance")
        if isinstance(raw, (int, float)) and not pd.isna(raw):
            last_distance = float(raw)
            break
    length_candidate = _convert_distance_units(last_distance)
    if 1.0 <= length_candidate <= 15.0:
        return length_candidate
    polyline_distance = _polyline_length(points)
    converted_polyline = _convert_distance_units(polyline_distance)
    if converted_polyline > 0:
        return converted_polyline
    return max(length_candidate, 0.0)


def _quantize_layout_length(length: Optional[float]) -> int:
    if length is None:
        return 0
    try:
        value = float(length)
    except Exception:
        return 0
    if pd.isna(value) or value <= 0:
        return 0
    meters = value * 1000.0
    # Reduced bucket size from 25m to 10m to distinguish between Abu Dhabi 2019-2021 (5.233km) vs 2023-2025 (5.197km)
    bucket_size = 10.0
    return int(round(meters / bucket_size) * bucket_size)


def _collapse_layout_variants(
    variants: List[Dict[str, Any]],
    current_signature: str,
) -> Tuple[List[Dict[str, Any]], List[int]]:
    buckets: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for variant in variants:
        circuit_token = _normalize_token(variant.get("circuit_name") or "")
        quantized_length = _quantize_layout_length(variant.get("layout_length"))
        key = (circuit_token, quantized_length)
        bucket = buckets.setdefault(key, {
            "variants": [],
            "years": set(),
            "rounds": set(),
            "signatures": set(),
        })
        bucket["variants"].append(variant)
        aliases = variant.get("_aliases") or {variant.get("layout_signature")}
        bucket["signatures"].update(sig for sig in aliases if sig)
        bucket["years"].update(variant.get("years", []))
        bucket["rounds"].update((ref.get("year"), ref.get("round")) for ref in variant.get("rounds", []))

    collapsed: List[Dict[str, Any]] = []
    layout_years: set[int] = set()

    for bucket in buckets.values():
        entries = bucket["variants"]
        if not entries:
            continue
        signatures = [sig for sig in bucket["signatures"] if sig]
        canonical_signature = current_signature if current_signature in signatures else (signatures[0] if signatures else "")
        reference = next((item for item in entries if item.get("layout_signature") == canonical_signature), entries[0])
        combined_rounds = sorted({
            (int(year), int(round_number))
            for year, round_number in bucket["rounds"]
            if year is not None and round_number is not None
        })
        rounds_payload = [{"year": year, "round": round_number} for year, round_number in combined_rounds]
        years_sorted = sorted(bucket["years"])
        reference_label = reference.get("layout_label") or reference.get("circuit_name") or "Layout"
        if years_sorted:
            if len(years_sorted) == 1:
                era_text = f"{years_sorted[0]}"
            else:
                era_text = f"{years_sorted[0]}–{years_sorted[-1]}"
            if "•" in reference_label:
                layout_label = reference_label
            else:
                layout_label = f"{reference_label} • {era_text}"
        else:
            layout_label = reference_label
        collapsed.append({
            "layout_signature": canonical_signature or reference.get("layout_signature") or "",
            "layout_label": layout_label,
            "layout_length": reference.get("layout_length"),
            "circuit_name": reference.get("circuit_name"),
            "years": years_sorted,
            "rounds": rounds_payload,
        })
        if current_signature in signatures:
            layout_years.update(bucket["years"])

    collapsed.sort(key=lambda item: (
        item.get("layout_label") or "",
        item.get("layout_length") or 0,
    ))

    return collapsed, sorted(layout_years)


def _iter_map_candidates(preferred_year: int, preferred_round: int, track_entry: Optional[Dict[str, Any]]) -> Iterable[Tuple[int, int]]:
    seen: set[Tuple[int, int]] = set()
    if preferred_year is not None:
        seen.add((preferred_year, preferred_round))
        yield preferred_year, preferred_round
    if not track_entry:
        return
    events = sorted(
        track_entry.get("events", []),
        key=lambda item: (int(item.get("year", 0)), int(item.get("round", 0))),
        reverse=True,
    )
    for event in events:
        candidate = (int(event.get("year", 0)), int(event.get("round", 0)))
        if candidate in seen:
            continue
        seen.add(candidate)
        yield candidate


def _load_track_map_with_fallback(
    preferred_year: int,
    preferred_round: int,
    track_entry: Optional[Dict[str, Any]],
    *,
    refresh: bool,
    track_key_hint: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], str]:
    last_exc: Optional[HTTPException] = None
    resolved_entry = track_entry
    resolved_key = track_key_hint or (track_entry.get("key") if track_entry else None) or f"track_{preferred_year}_{preferred_round}"
    for cand_year, cand_round in _iter_map_candidates(preferred_year, preferred_round, track_entry):
        candidate_entry = resolved_entry
        if candidate_entry is None:
            candidate_entry = _find_track_entry(cand_year, cand_round)
        candidate_key = track_key_hint or (candidate_entry.get("key") if candidate_entry else None)
        if not candidate_key:
            candidate_key = f"track_{cand_year}_{cand_round}"
        try:
            use_refresh = refresh
            data = _load_track_map_core(candidate_key, cand_year, cand_round, refresh=use_refresh)
            resolved_entry = candidate_entry or resolved_entry
            resolved_key = candidate_key
            return data, resolved_entry, resolved_key
        except HTTPException as exc:  # pragma: no cover - fastf1 dependent
            last_exc = exc
            if exc.status_code != 404:
                raise
            continue
    if last_exc is not None:
        raise last_exc
    raise HTTPException(status_code=404, detail="Track map not available")
