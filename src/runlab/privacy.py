"""Location privacy: remove coordinates near the start and end of every activity.

Most runs start and finish at home. Clipping the first and last N metres of GPS
(Strava calls this a privacy zone) means the published warehouse, dashboard and
any shared track never reveal where the athlete lives. This runs at ingestion,
so trimmed coordinates never reach the warehouse at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def trim_endpoints(records: pd.DataFrame, trim_m: float, keep_coordinates: bool = True) -> pd.DataFrame:
    out = records.copy()
    if not keep_coordinates:
        out["lat"] = np.nan
        out["lon"] = np.nan
        return out
    if trim_m <= 0 or out.empty or out["distance_m"].isna().all():
        return out
    dist = out["distance_m"].to_numpy(dtype=float)
    total = np.nanmax(dist)
    hide = (dist < trim_m) | (dist > total - trim_m) | np.isnan(dist)
    out.loc[hide, ["lat", "lon"]] = np.nan
    return out
