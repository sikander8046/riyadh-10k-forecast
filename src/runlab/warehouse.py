"""Build the DuckDB warehouse: raw (from Parquet) -> staging -> marts."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import duckdb

from runlab.config import Config

LAYERS = ("staging", "marts")

_EMPTY_RECORDS = """
CREATE OR REPLACE TABLE raw.records (
    activity_id BIGINT, ts TIMESTAMP, lat DOUBLE, lon DOUBLE, altitude_m DOUBLE,
    hr DOUBLE, cadence DOUBLE, distance_m DOUBLE, speed_mps DOUBLE, had_gps BOOLEAN
)
"""

_EMPTY_WEATHER = """
CREATE OR REPLACE TABLE raw.weather_hourly (
    lat_r DOUBLE, lon_r DOUBLE, hour_utc TIMESTAMP, temp_c DOUBLE, humidity_pct DOUBLE,
    dew_point_c DOUBLE, feels_like_c DOUBLE, wind_mps DOUBLE
)
"""


def connect(cfg: Config, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    cfg.warehouse.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(cfg.warehouse), read_only=read_only)


def _sql_files(layer: str) -> list[tuple[str, str]]:
    folder = resources.files("runlab") / "sql" / layer
    files = sorted((f for f in folder.iterdir() if f.name.endswith(".sql")), key=lambda f: f.name)
    return [(f.name, f.read_text()) for f in files]


def load_raw(con: duckdb.DuckDBPyConnection, cfg: Config) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    interim = cfg.interim_dir
    con.execute(
        "CREATE OR REPLACE TABLE raw.activities AS SELECT * FROM read_parquet(?)",
        [str(interim / "activities.parquet")],
    )
    con.execute(
        "CREATE OR REPLACE TABLE raw.ingest_log AS SELECT * FROM read_parquet(?)",
        [str(interim / "ingest_log.parquet")],
    )
    record_files = sorted(str(p) for p in (interim / "records").glob("*.parquet"))
    if record_files:
        con.execute(
            "CREATE OR REPLACE TABLE raw.records AS SELECT * FROM read_parquet(?, union_by_name = true)",
            [record_files],
        )
    else:
        con.execute(_EMPTY_RECORDS)
    weather = interim / "weather_hourly.parquet"
    if weather.exists():
        con.execute(
            "CREATE OR REPLACE TABLE raw.weather_hourly AS SELECT * FROM read_parquet(?)",
            [str(weather)],
        )
    else:
        con.execute(_EMPTY_WEATHER)


def load_params(con: duckdb.DuckDBPyConnection, cfg: Config) -> None:
    a, b = cfg.trimp_coefficients
    con.execute("CREATE SCHEMA IF NOT EXISTS staging")
    con.execute(
        """
        CREATE OR REPLACE TABLE staging.params AS
        SELECT ?::DOUBLE AS hr_max, ?::DOUBLE AS hr_rest, ?::DOUBLE AS trimp_a,
               ?::DOUBLE AS trimp_b, ?::DOUBLE AS hr_min_valid, ?::DOUBLE AS hr_max_margin,
               ?::DOUBLE AS max_run_speed_mps, ?::DOUBLE AS pause_gap_s,
               ?::DOUBLE AS duplicate_window_s
        """,
        [
            cfg.hr_max,
            cfg.hr_rest,
            a,
            b,
            cfg.hr_min_valid,
            cfg.hr_max_margin,
            cfg.max_run_speed_mps,
            cfg.pause_gap_s,
            cfg.duplicate_window_s,
        ],
    )


def build(cfg: Config) -> list[str]:
    """Rebuild every layer. Returns the model names executed, in order."""
    if not (cfg.interim_dir / "activities.parquet").exists():
        raise FileNotFoundError("No ingested data found. Run `runlab ingest` first.")
    executed = []
    with connect(cfg) as con:
        load_raw(con, cfg)
        load_params(con, cfg)
        for layer in LAYERS:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {layer}")
            for name, sql in _sql_files(layer):
                con.execute(sql)
                executed.append(f"{layer}.{Path(name).stem}")
        from runlab.models.load import build_fitness_table

        build_fitness_table(con)
        executed.append("marts.fct_fitness")
    return executed
