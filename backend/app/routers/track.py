# ======== BEGIN: Caching fuer /f1/tracks (2018-2025) ========
# Du kannst diesen ganzen Block in backend/app/routers/track.py einfuegen.
# Er setzt deine alte list_tracks Funktion ausser Kraft und fuegt Dateicache hinzu.

# 1) Imports sicherstellen
from typing import Any, Dict, List
import os
import json
from pathlib import Path

# FastAPI und FastF1
try:
    from fastapi import Query, APIRouter
except ImportError:
    # Falls bereits importiert, ignorieren
    pass

import fastf1

# 2) Router wiederverwenden, falls er schon existiert
try:
    router  # type: ignore[name-defined]
except NameError:
    # Falls du diesen Block in eine neue Datei kopierst
    router = APIRouter(prefix="/f1", tags=["f1"])

# 3) Kleine Hilfsfunktionen
try:
    _safe_str  # type: ignore[name-defined]
except NameError:
    def _safe_str(v: Any) -> str | None:
        if v is None:
            return None
        s = str(v)
        s = s.strip()
        return s if s != "" and s.lower() != "nan" else None

def _parse_years(spec: str) -> list[int]:
    years: list[int] = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            years.extend(range(int(a), int(b) + 1))
        else:
            years.append(int(part))
    return sorted(set(years))

def _build_tracks(years: list[int]) -> list[Dict[str, Any]]:
    # Liste eindeutiger Strecken ueber mehrere Jahre.
    # Dedupliziere nach CircuitShortName | Country, nimm jeweils den aktuellsten Eintrag.
    seen: dict[str, dict[str, Any]] = {}

    for year in years:
        try:
            schedule = fastf1.get_event_schedule(year, include_testing=False)
        except Exception:
            continue
        if schedule is None or getattr(schedule, "empty", False):
            continue

        for _, ev in schedule.iterrows():
            # Runde ermitteln
            rnd = None
            for col in ("RoundNumber", "Round", "RoundNumberOfficial"):
                try:
                    val = ev.get(col)
                    if val is not None and str(val).strip() != "":
                        rnd = int(val)
                        break
                except Exception:
                    pass
            if rnd is None:
                continue

            circuit = _safe_str(ev.get("CircuitShortName")) or _safe_str(ev.get("Location"))
            country = _safe_str(ev.get("Country"))
            if not circuit and not country:
                key = f"{year}-{rnd}"
            else:
                key = f"{(circuit or '').strip()}|{(country or '').strip()}".strip("|")

            display_name = circuit or (_safe_str(ev.get("EventName")) or key)

            prev = seen.get(key)
            if not prev or (year > int(prev.get("year", 0)) or (year == int(prev.get("year", 0)) and rnd > int(prev.get("round", 0)))):
                seen[key] = {
                    "key": key,
                    "name": display_name,
                    "year": int(year),
                    "round": int(rnd),
                    "country": country,
                    "location": _safe_str(ev.get("Location")),
                }

    items = list(seen.values())
    items.sort(key=lambda x: (x.get("name") or ""))
    return items

# 4) Dateicache Pfade
CACHE_DIR = Path(os.getenv("SEASON_CACHE_DIR", "/app/app/season_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TRACKS_JSON = CACHE_DIR / "tracks.json"

# 5) Jahresbereich. Default deckt 2018-2025 ab. Per Env ueberschreibbar.
TRACK_LIST_YEARS = os.getenv("TRACK_LIST_YEARS", "2018-2025")

# 6) Die neue, gecachte Endpoint-Funktion. Diese ersetzt deine alte list_tracks.
@router.get("/tracks")
def list_tracks(refresh: bool = Query(False)) -> List[Dict[str, Any]]:
    """
    Liefert eine eindeutige Liste von F1-Strecken ueber die konfigurierten Jahre.
    Beim ersten Mal oder falls refresh=true wird neu berechnet und nach tracks.json geschrieben.
    Danach wird aus der Datei gelesen. Funktional bleibt alles identisch zur alten Logik.
    """
    if TRACKS_JSON.exists() and not refresh:
        try:
            return json.loads(TRACKS_JSON.read_text(encoding="utf-8"))
        except Exception:
            # Fallback: neu bauen, wenn Datei defekt ist
            pass

    years = _parse_years(TRACK_LIST_YEARS)
    items = _build_tracks(years)

    tmp = TRACKS_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    tmp.replace(TRACKS_JSON)

    return items

# ======== END: Caching fuer /f1/tracks ========
