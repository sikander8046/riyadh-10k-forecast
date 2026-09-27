"""Small geodesy helpers (no external dependency)."""

from __future__ import annotations

import numpy as np

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1, lon1, lat2, lon2):
    """Vectorised great-circle distance in metres."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def cumulative_distance_m(lat, lon) -> np.ndarray:
    """Cumulative distance along a track; NaN positions contribute zero."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    if len(lat) == 0:
        return np.array([], dtype=float)
    step = haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:])
    step = np.nan_to_num(step, nan=0.0)
    return np.concatenate([[0.0], np.cumsum(step)])
