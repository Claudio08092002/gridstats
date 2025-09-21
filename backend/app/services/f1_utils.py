from typing import Tuple
import pandas as pd
import os, fastf1
fastf1.Cache.enable_cache(os.getenv("FASTF1_CACHE", "/data/fastf1_cache"))

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
        return "fastf1", f1

    # 2b) sonst wenn Ergast Punkte hat -> nimm Ergast
    if er is not None and has_points(er):
        return "ergast", er

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
    return "derived", df_res