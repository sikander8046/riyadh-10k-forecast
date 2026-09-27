"""Parse per-activity stream files (FIT, GPX, TCX; optionally gzipped).

Every parser returns the same record-level frame:

    ts (UTC, naive) | lat | lon | altitude_m | hr | cadence | distance_m | speed_mps

Distance and speed are derived from GPS when the device did not record them.
Cadence is stored as recorded (FIT running cadence is per leg, i.e. half of
steps per minute); the staging layer normalises it.
"""

from __future__ import annotations

import gzip
import io
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from runlab.geo import cumulative_distance_m

COLUMNS = ["ts", "lat", "lon", "altitude_m", "hr", "cadence", "distance_m", "speed_mps"]
SEMICIRCLE_TO_DEG = 180.0 / 2**31


class UnsupportedFormat(ValueError):
    pass


def _read_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def detect_format(path: Path) -> str:
    name = path.name.lower().removesuffix(".gz")
    for ext in ("fit", "gpx", "tcx"):
        if name.endswith("." + ext):
            return ext
    raise UnsupportedFormat(f"Unsupported file type: {path.name}")


def parse_stream(path: Path) -> pd.DataFrame:
    fmt = detect_format(path)
    data = _read_bytes(path)
    parser = {"fit": _parse_fit, "gpx": _parse_gpx, "tcx": _parse_tcx}[fmt]
    df = parser(data)
    return finalise(df)


# ---------------------------------------------------------------- FIT


def _parse_fit(data: bytes) -> pd.DataFrame:
    import fitdecode

    rows = []
    with fitdecode.FitReader(io.BytesIO(data), check_crc=fitdecode.CrcCheck.WARN) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage) or frame.name != "record":
                continue

            def val(*names, _frame=frame):
                for n in names:
                    if _frame.has_field(n):
                        v = _frame.get_value(n)
                        if v is not None:
                            return v
                return None

            lat, lon = val("position_lat"), val("position_long")
            rows.append(
                {
                    "ts": val("timestamp"),
                    "lat": lat * SEMICIRCLE_TO_DEG if isinstance(lat, int) else lat,
                    "lon": lon * SEMICIRCLE_TO_DEG if isinstance(lon, int) else lon,
                    "altitude_m": val("enhanced_altitude", "altitude"),
                    "hr": val("heart_rate"),
                    "cadence": val("cadence"),
                    "distance_m": val("distance"),
                    "speed_mps": val("enhanced_speed", "speed"),
                }
            )
    return pd.DataFrame(rows, columns=COLUMNS)


# ---------------------------------------------------------------- GPX


def _parse_gpx(data: bytes) -> pd.DataFrame:
    import gpxpy

    gpx = gpxpy.parse(data.decode("utf-8", errors="replace"))
    rows = []
    for track in gpx.tracks:
        for segment in track.segments:
            for p in segment.points:
                hr = cad = None
                for ext in p.extensions:
                    for el in ext.iter():
                        tag = el.tag.rsplit("}", 1)[-1].lower()
                        if tag == "hr" and el.text:
                            hr = float(el.text)
                        elif tag in ("cad", "cadence") and el.text:
                            cad = float(el.text)
                rows.append(
                    {
                        "ts": p.time,
                        "lat": p.latitude,
                        "lon": p.longitude,
                        "altitude_m": p.elevation,
                        "hr": hr,
                        "cadence": cad,
                        "distance_m": None,
                        "speed_mps": None,
                    }
                )
    return pd.DataFrame(rows, columns=COLUMNS)


# ---------------------------------------------------------------- TCX


def _parse_tcx(data: bytes) -> pd.DataFrame:
    # Some devices write leading whitespace before the XML declaration.
    root = ET.fromstring(data.strip())

    def local(el):
        return el.tag.rsplit("}", 1)[-1]

    def child_text(el, name):
        for c in el.iter():
            if local(c) == name and c.text:
                return c.text
        return None

    rows = []
    for tp in root.iter():
        if local(tp) != "Trackpoint":
            continue
        hr_value = None
        for c in tp:
            if local(c) == "HeartRateBpm":
                hr_value = child_text(c, "Value")
        rows.append(
            {
                "ts": child_text(tp, "Time"),
                "lat": child_text(tp, "LatitudeDegrees"),
                "lon": child_text(tp, "LongitudeDegrees"),
                "altitude_m": child_text(tp, "AltitudeMeters"),
                "hr": hr_value,
                "cadence": child_text(tp, "RunCadence") or child_text(tp, "Cadence"),
                "distance_m": child_text(tp, "DistanceMeters"),
                "speed_mps": child_text(tp, "Speed"),
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)


# ---------------------------------------------------------------- common


def finalise(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce types, sort, de-duplicate timestamps and fill derived fields."""
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce").dt.tz_localize(None)
    for col in COLUMNS[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    df = df.dropna(subset=["ts"]).sort_values("ts").drop_duplicates("ts", keep="first")
    df = df.reset_index(drop=True)
    if df.empty:
        return df[COLUMNS]

    if df["distance_m"].isna().all() and df["lat"].notna().any():
        df["distance_m"] = cumulative_distance_m(df["lat"], df["lon"])
    elif df["distance_m"].notna().any():
        df["distance_m"] = df["distance_m"].ffill().fillna(0.0)

    # Some devices (notably some phone running apps) log a GPS fix and distance
    # every second but only report a speed value every few seconds. Filling
    # only the gaps -- rather than requiring every value to be missing --
    # recovers moving time on those seconds instead of losing it as "not
    # moving". A device's own speed reading is kept wherever it exists, since
    # it can be smoother (GPS Doppler) than a raw distance difference.
    if df["distance_m"].notna().sum() > 1 and df["speed_mps"].isna().any():
        dt = df["ts"].diff().dt.total_seconds()
        dd = df["distance_m"].diff()
        derived = (dd / dt).where(dt > 0)
        df["speed_mps"] = df["speed_mps"].fillna(derived)

    return df[COLUMNS]
