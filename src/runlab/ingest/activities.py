"""Parse activities.csv from a Strava bulk export.

Quirks this handles:
- The CSV repeats column names ("Elapsed Time", "Distance", "Max Heart Rate").
  The first "Distance" is kilometres, the repeated one is metres. pandas renames
  repeats to "Distance.1" etc.; the metric versions are preferred when present.
- "Activity Date" is UTC in a US format ("Mar 15, 2024, 6:12:03 AM"), sometimes
  with a narrow no-break space before AM/PM.
- Columns vary by account age and export date, so every optional column is
  looked up defensively.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from runlab.config import Config

RUN_TYPES = {"Run", "Trail Run", "Virtual Run"}

# target column -> candidate source columns, first match wins, with a unit factor
_NUMERIC_COLUMNS: dict[str, list[tuple[str, float]]] = {
    "distance_m": [("Distance.1", 1.0), ("Distance", 1000.0)],
    "elapsed_s": [("Elapsed Time.1", 1.0), ("Elapsed Time", 1.0)],
    "moving_s": [("Moving Time", 1.0)],
    "elev_gain_m": [("Elevation Gain", 1.0)],
    "avg_hr": [("Average Heart Rate", 1.0)],
    "max_hr": [("Max Heart Rate.1", 1.0), ("Max Heart Rate", 1.0)],
    "avg_cadence": [("Average Cadence", 1.0)],
    "calories": [("Calories", 1.0)],
    "relative_effort": [("Relative Effort", 1.0)],
}


def parse_activity_dates(values: pd.Series) -> pd.Series:
    cleaned = values.astype(str).str.replace("\u202f", " ", regex=False).str.strip()
    parsed = pd.to_datetime(cleaned, format="%b %d, %Y, %I:%M:%S %p", errors="coerce", utc=True)
    missing = parsed.isna()
    if missing.any():
        parsed[missing] = pd.to_datetime(cleaned[missing], format="mixed", errors="coerce", utc=True)
    return parsed


def _numeric(series: pd.Series) -> pd.Series:
    if series.dtype == object:
        series = series.astype(str).str.replace(",", "", regex=False).replace({"": np.nan, "nan": np.nan})
    return pd.to_numeric(series, errors="coerce")


def load_activities(cfg: Config, csv_path: Path | None = None) -> pd.DataFrame:
    csv_path = csv_path or cfg.export_dir / "activities.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"{csv_path} not found. Unzip your Strava export into {cfg.export_dir}.")
    raw = pd.read_csv(csv_path, dtype=str, keep_default_na=False)

    out = pd.DataFrame(
        {
            "activity_id": pd.to_numeric(raw["Activity ID"], errors="coerce").astype("Int64"),
            "start_utc": parse_activity_dates(raw["Activity Date"]),
            "name": raw.get("Activity Name", pd.Series("", index=raw.index)),
            "activity_type": raw.get("Activity Type", pd.Series("", index=raw.index)).str.strip(),
            "filename": raw.get("Filename", pd.Series("", index=raw.index)).str.strip(),
            "gear": raw.get("Activity Gear", pd.Series("", index=raw.index)),
        }
    )
    for target, candidates in _NUMERIC_COLUMNS.items():
        out[target] = np.nan
        for source, factor in candidates:
            if source in raw.columns:
                values = _numeric(raw[source]) * factor
                if values.notna().any():
                    out[target] = values
                    break

    # local time according to the configured timezone periods
    tz_names = [cfg.tz_for(ts) if pd.notna(ts) else None for ts in out["start_utc"]]
    out["timezone"] = tz_names
    out["start_local"] = [
        ts.tz_convert(ZoneInfo(tz)).tz_localize(None) if tz else pd.NaT
        for ts, tz in zip(out["start_utc"], tz_names, strict=True)
    ]
    out["start_local"] = pd.to_datetime(out["start_local"])
    out["start_utc"] = out["start_utc"].dt.tz_localize(None)  # store naive UTC
    out["is_run"] = out["activity_type"].isin(RUN_TYPES)
    out["filename"] = out["filename"].replace("", pd.NA)
    return out
