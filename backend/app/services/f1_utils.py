from typing import Tuple
import pandas as pd
import os
import fastf1

# Default je nach Betriebssystem
default_cache = (
    "C:/Users/claud/.fastf1_cache" if os.name == "nt" else "/data/fastf1_cache"
)

# Entweder Umgebungsvariable oder Default nehmen
cache_dir = os.getenv("FASTF1_CACHE", default_cache)

# Ordner sicherstellen
os.makedirs(cache_dir, exist_ok=True)

print(">>> Using FastF1 cache dir:", cache_dir)
fastf1.Cache.enable_cache(cache_dir)

def _to_numeric(df: pd.DataFrame, cols=("Position","Points")) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def _norm_abbreviation(df: pd.DataFrame, ses) -> pd.DataFrame:
    """Sorge dafür, dass es eine Spalte 'Abbreviation' gibt."""
    df = df.copy()
    if "Abbreviation" in df.columns:
        return df
    # Fallbacks: manchmal gibt's 'Driver' (3-letter) oder 'DriverNumber'
    if "Driver" in df.columns:
        df["Abbreviation"] = df["Driver"]
        return df
    if "DriverNumber" in df.columns:
        try:
            # mappe DriverNumber -> Abbreviation via Session
            mp = {}
            for num in pd.unique(df["DriverNumber"].dropna()):
                try:
                    info = ses.get_driver(int(num))

                    if info and "Abbreviation" in info:
                        mp[num] = info["Abbreviation"]
                except Exception:
                    pass
            df["Abbreviation"] = df["DriverNumber"].map(mp)
            return df
        except Exception:
            pass
    # letzter Ausweg: lege leere Spalte an
    df["Abbreviation"] = None
    return df


def _enrich_from_source(base: pd.DataFrame, source: pd.DataFrame | None) -> pd.DataFrame:
    if source is None or source.empty:
        return base
    join_cols: list[str] = []
    if "Abbreviation" in base.columns and "Abbreviation" in source.columns:
        join_cols.append("Abbreviation")
    if not join_cols and "DriverNumber" in base.columns and "DriverNumber" in source.columns:
        join_cols.append("DriverNumber")
    if not join_cols:
        return base

    desired_cols = [
        "Status",
        "GridPosition",
        "TeamName",
        "ConstructorName",
        "TeamColor",
        "FullName",
        "BroadcastName",
        "Driver",
        "DriverNumber",
    ]
    avail_cols = [c for c in desired_cols if c in source.columns]
    if not avail_cols:
        return base

    extras = source[join_cols + avail_cols].drop_duplicates(subset=join_cols)
    merged = base.merge(extras, on=join_cols, how="left", suffixes=("", "__src"))

    for col in avail_cols:
        src_col = f"{col}__src"
        if src_col not in merged.columns:
            continue
        if col in merged.columns:
            merged[col] = merged[col].combine_first(merged[src_col])
            merged = merged.drop(columns=[src_col])
        else:
            merged.rename(columns={src_col: col}, inplace=True)
    return merged

def _build_dnf_maps(ses) -> tuple[dict[str, bool], dict[str, bool]]:
    """Create DNF maps keyed by Abbreviation and DriverNumber from a FastF1 session.
    Falls back to Status when explicit dnf is missing. We treat 'not classified' as DNF.
    """
    by_abbr: dict[str, bool] = {}
    by_num: dict[str, bool] = {}
    try:
        res = getattr(ses, "results", None)
        if res is None or res.empty:
            return by_abbr, by_num
        for _, row in res.iterrows():
            abbr = row.get("Abbreviation") or row.get("Driver")
            num = row.get("DriverNumber")
            info = None
            if pd.notna(num):
                try:
                    info = ses.get_driver(int(num))
                except Exception:
                    info = None
            dnf_val = None
            if isinstance(info, dict):
                if "dnf" in info:
                    dnf_val = info.get("dnf")
                elif "DNF" in info:
                    dnf_val = info.get("DNF")
            if dnf_val is None:
                status = str(row.get("Status") or "").strip().lower()
                if status:
                    finish_like = status.startswith("+") or status in ("finished", "lapped")
                    # treat 'not classified' as DNF, so do not exclude it
                    excluded = status in ("disqualified", "did not start", "excluded")
                    dnf_val = (not finish_like) and (not excluded)
                else:
                    dnf_val = False
            if abbr and pd.notna(abbr):
                by_abbr[str(abbr)] = bool(dnf_val)
            if pd.notna(num):
                by_num[str(int(num))] = bool(dnf_val)
    except Exception:
        pass
    return by_abbr, by_num

def _apply_dnf_column(df: pd.DataFrame | None, dnf_by_abbr: dict[str, bool], dnf_by_num: dict[str, bool]) -> pd.DataFrame | None:
    if df is None or df.empty:
        return df
    df = df.copy()
    if "Abbreviation" in df.columns:
        df["DNF"] = df["Abbreviation"].map(lambda x: bool(dnf_by_abbr.get(str(x), False)))
    elif "DriverNumber" in df.columns:
        df["DNF"] = df["DriverNumber"].map(lambda x: bool(dnf_by_num.get(str(x), False)))
    else:
        # default False
        df["DNF"] = False
    return df

def load_results_strict(year: int, round_number: int) -> Tuple[str, pd.DataFrame]:
    """
    Robust:
      - Lade FastF1-Results
      - Lade Ergast-Results (cache disabled)
      - Wähle die Variante mit validen Points; wenn F1 Positions ok aber Points leer -> Points aus Ergast mergen
      - Notfall: aus Laps provisorisch ableiten
    Rückgabe: (source, DataFrame mit Abbreviation, Position, Points[, evtl. Name/Team/Status])
    """
    # 1) FastF1 Results
    ses_f1 = fastf1.get_session(year, round_number, "R", backend="fastf1")
    ses_f1.load(laps=False, telemetry=False, weather=False, messages=False)
    f1 = ses_f1.results.copy() if ses_f1.results is not None else None
    if f1 is not None and not f1.empty:
        f1 = _to_numeric(_norm_abbreviation(f1, ses_f1))
        if "Points" not in f1.columns:
            f1["Points"] = pd.NA

    # 2) Ergast Results
    er = None
    try:
        with fastf1.Cache.disabled():
            ses_er = fastf1.get_session(year, round_number, "R", backend="ergast")
            ses_er.load(laps=False, telemetry=False, weather=False, messages=False)
            er = ses_er.results.copy() if ses_er.results is not None else None
        if er is not None and not er.empty:
            er = _to_numeric(_norm_abbreviation(er, ses_er))
            if "Points" not in er.columns:
                er["Points"] = pd.NA
    except Exception:
        pass

    def has_points(df: pd.DataFrame) -> bool:
        return df is not None and not df.empty and "Points" in df.columns and pd.to_numeric(df["Points"], errors="coerce").fillna(0).sum() > 0

    def has_positions(df: pd.DataFrame) -> bool:
        return df is not None and not df.empty and "Position" in df.columns and pd.to_numeric(df["Position"], errors="coerce").notna().any()

    # 2a) wenn FastF1 schon gültige Punkte hat -> nimm F1
    if f1 is not None and has_points(f1):
        dnf_abbr, dnf_num = _build_dnf_maps(ses_f1)
        enriched = _enrich_from_source(f1, er)
        enriched = _apply_dnf_column(enriched, dnf_abbr, dnf_num)
        return "fastf1", enriched

    # 2b) sonst wenn Ergast Punkte hat -> nimm Ergast
    if er is not None and has_points(er):
        dnf_abbr, dnf_num = _build_dnf_maps(ses_f1)
        enriched = _enrich_from_source(er, f1)
        enriched = _apply_dnf_column(enriched, dnf_abbr, dnf_num)
        return "ergast", enriched

    # 2c) wenn F1 Positionen hat, aber Points leer: versuche Points aus Ergast zu mergen
    if f1 is not None and has_positions(f1) and er is not None:
        # Join über Abbreviation; falls dort NaN: versuche DriverNumber
        join_cols = []
        if "Abbreviation" in f1.columns and "Abbreviation" in er.columns:
            join_cols = ["Abbreviation"]
        elif "DriverNumber" in f1.columns and "DriverNumber" in er.columns:
            join_cols = ["DriverNumber"]
        if join_cols:
            merged = f1.merge(er[join_cols + ["Points"]], on=join_cols, how="left", suffixes=("", "_er"))
            # fülle fehlende Points aus Ergast
            if "Points_er" in merged.columns:
                merged["Points"] = merged["Points"].fillna(merged["Points_er"])
                merged = merged.drop(columns=["Points_er"])
            merged["Points"] = pd.to_numeric(merged["Points"], errors="coerce").fillna(0)
            merged = _enrich_from_source(merged, er)
            merged = _enrich_from_source(merged, f1)
            dnf_abbr, dnf_num = _build_dnf_maps(ses_f1)
            merged = _apply_dnf_column(merged, dnf_abbr, dnf_num)
            return "f1+ergast_points", merged

    # 3) Notlösung: Laps ableiten
    ses3 = fastf1.get_session(year, round_number, "R", backend="fastf1")
    ses3.load(laps=True, telemetry=False, weather=False, messages=False)
    laps = ses3.laps
    if laps is None or laps.empty:
        return "derived_empty", pd.DataFrame(columns=["Abbreviation","Position","Points"])

    laps = laps.sort_values(["Driver", "LapNumber"])
    last = laps.groupby("Driver").last(numeric_only=False).reset_index()
    last["PositionNum"] = pd.to_numeric(last.get("Position"), errors="coerce")
    df = last.sort_values(["PositionNum", "LapNumber"], ascending=[True, False]).reset_index(drop=True)
    df["ProvisionalPosition"] = df.index + 1
    points_map = {1:25,2:18,3:15,4:12,5:10,6:8,7:6,8:4,9:2,10:1}
    df["ProvisionalPoints"] = df["ProvisionalPosition"].map(points_map).fillna(0).astype(int)
    df_res = pd.DataFrame({
        "Abbreviation": df["Driver"],
        "Position": df["ProvisionalPosition"],
        "Points": df["ProvisionalPoints"],
    })
    df_res = _enrich_from_source(df_res, er)
    df_res = _enrich_from_source(df_res, f1)
    dnf_abbr, dnf_num = _build_dnf_maps(ses3)
    df_res = _apply_dnf_column(df_res, dnf_abbr, dnf_num)
    return "derived", df_res