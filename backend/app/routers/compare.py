from fastapi import APIRouter, HTTPException
import fastf1
import pandas as pd
from typing import Dict, Any
from app.services.f1_utils import load_results_strict

router = APIRouter(prefix="/f1", tags=["fastf1"])
fastf1.Cache.enable_cache("C:/Users/claud/.fastf1_cache")

@router.get("/season/{year}")
def load_season(year: int) -> Dict[str, Any]:
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        results_by_driver: Dict[str, Dict[str, Any]] = {}

        for _, ev in schedule.iterrows():
            rnd = ev.get("RoundNumber")
            if pd.isna(rnd) or int(rnd) <= 0:
                continue
            rnd = int(rnd)

            try:
                source, df = load_results_strict(year, rnd)
            except Exception:
                continue
            if df is None or df.empty:
                continue

            # numerisch + Defaults
            if "Points" not in df.columns: df["Points"] = 0.0
            if "Position" not in df.columns: df["Position"] = pd.NA
            df["Points"] = pd.to_numeric(df["Points"], errors="coerce").fillna(0.0)
            df["Position"] = pd.to_numeric(df["Position"], errors="coerce")

            # Name/Team/Status optional beibehalten, falls vorhanden
            for _, row in df.iterrows():
                code = row.get("Abbreviation")
                if not code or pd.isna(code):
                    continue
                d = results_by_driver.setdefault(code, {
                    "name": row.get("FullName") or row.get("BroadcastName") or code,
                    "team": row.get("TeamName"),
                    "points": 0.0,
                    "wins": 0,
                    "podiums": 0,
                    "dnfs": 0,
                    "positions": [],
                })

                d["points"] += float(row["Points"])

                pos = row.get("Position")
                if pd.notna(pos):
                    ipos = int(pos)
                    d["positions"].append(ipos)
                    if ipos == 1: d["wins"] += 1
                    if ipos <= 3: d["podiums"] += 1

                status = (row.get("Status") or "").strip()
                if status and status not in ("Finished", "") and not str(status).startswith("+"):
                    d["dnfs"] += 1

        # finalize -> native Python Types
        out: Dict[str, Any] = {}
        for code, d in results_by_driver.items():
            avg = float(pd.Series(d["positions"]).mean()) if d["positions"] else None
            out[code] = {
                "name": str(d["name"]) if d["name"] else code,
                "team": (str(d["team"]) if d["team"] else None),
                "total_points": float(d["points"]),
                "wins": int(d["wins"]),
                "podiums": int(d["podiums"]),
                "dnfs": int(d["dnfs"]),
                "avg_finish": (float(avg) if avg is not None else None),
                "poles": 0,
            }

        return {"season": year, "drivers": out}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
