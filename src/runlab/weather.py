"""Historical hourly weather for every run, from Open-Meteo (free, no API key).

One request per location (rounded to 0.1 degree) covering all its run dates.
Responses are cached in data/interim/weather, so rebuilds never re-download.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from runlab.config import Config
from runlab.warehouse import connect

API = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = {
    "temperature_2m": "temp_c",
    "relative_humidity_2m": "humidity_pct",
    "dew_point_2m": "dew_point_c",
    "apparent_temperature": "feels_like_c",
    "wind_speed_10m": "wind_mps",
}


def fetch_location(lat: float, lon: float, start: str, end: str, cache_dir: Path) -> pd.DataFrame:
    cache = cache_dir / f"{lat:+.1f}_{lon:+.1f}_{start}_{end}.json"
    if cache.exists():
        data = json.loads(cache.read_text())
    else:
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start,
            "end_date": end,
            "hourly": ",".join(VARIABLES),
            "timezone": "GMT",
            "wind_speed_unit": "ms",
        }
        url = f"{API}?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=120) as response:
            data = json.load(response)
        cache.write_text(json.dumps(data))
        time.sleep(1)  # be polite to a free service
    hourly = pd.DataFrame(data["hourly"]).rename(columns={"time": "hour_utc", **VARIABLES})
    hourly["hour_utc"] = pd.to_datetime(hourly["hour_utc"])
    hourly.insert(0, "lon_r", lon)
    hourly.insert(0, "lat_r", lat)
    return hourly


def run_weather(cfg: Config) -> str:
    cache_dir = cfg.interim_dir / "weather"
    cache_dir.mkdir(parents=True, exist_ok=True)
    with connect(cfg, read_only=True) as con:
        locations = con.execute(
            """
            SELECT lat_r, lon_r,
                   strftime(min(start_utc)::DATE - 1, '%Y-%m-%d') AS start_date,
                   strftime(max(start_utc)::DATE + 1, '%Y-%m-%d') AS end_date,
                   count(*) AS runs
            FROM staging.stg_run_locations
            WHERE lat_r IS NOT NULL
            GROUP BY lat_r, lon_r
            ORDER BY runs DESC
            """
        ).fetchall()
    frames = []
    for lat, lon, start, end, runs in locations:
        print(f"  {lat:+.1f}, {lon:+.1f}  {start} to {end}  ({runs} runs)")
        frames.append(fetch_location(lat, lon, start, end, cache_dir))
    if not frames:
        return "no run locations found; run `runlab build` first"
    hourly = pd.concat(frames, ignore_index=True)
    hourly.to_parquet(cfg.interim_dir / "weather_hourly.parquet", index=False)
    return f"{len(locations)} locations, {len(hourly):,} hourly rows saved"
