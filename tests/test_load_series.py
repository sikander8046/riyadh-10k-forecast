"""The shared load series: sensor-less runs estimated, walks added, decay through rest days."""

import datetime as dt
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from runlab.config import load_config
from runlab.models.load_series import build_load_series

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def warehouse():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA marts")
    rng = np.random.default_rng(0)
    first = dt.date(2026, 1, 1)
    run_days = [first + dt.timedelta(days=2 * i) for i in range(12)]
    no_sensor_day = run_days[-1] + dt.timedelta(days=2)
    rows = []
    for d in run_days:
        pace = float(rng.uniform(330, 430))
        rows.append((d, 2400.0, pace, 190 - 0.09 * pace + rng.normal(0, 1), True, False, 0.95))
    rows.append((no_sensor_day, 1800.0, 400.0, None, True, False, None))
    runs = pd.DataFrame(
        rows,
        columns=[
            "local_date",
            "moving_s",
            "pace_s_per_km",
            "avg_hr",
            "has_gps",
            "is_treadmill",
            "hr_coverage",
        ],
    )
    con.register("runs_df", runs)
    con.execute("CREATE TABLE marts.fct_runs AS SELECT * FROM runs_df")

    span = pd.date_range(first, no_sensor_day, freq="D").date
    daily = pd.DataFrame({"day": span, "trimp": [30.0 if d in run_days else 0.0 for d in span]})
    daily["km"] = daily["trimp"] / 6
    con.register("daily_df", daily)
    con.execute("CREATE TABLE marts.fct_daily_load AS SELECT * FROM daily_df")

    walks = pd.DataFrame(
        {
            "local_date": [no_sensor_day + dt.timedelta(days=3), no_sensor_day + dt.timedelta(days=4)],
            "moving_s": [3600.0, 3000.0],
            "distance_m": [5000.0, 4000.0],
            "trimp_est": [50.0, np.nan],
        }
    )
    con.register("walks_df", walks)
    con.execute("CREATE TABLE marts.fct_walks AS SELECT * FROM walks_df")
    return con, no_sensor_day


def test_series_runs_to_today_and_decays(warehouse):
    con, last_run = warehouse
    today = last_run + dt.timedelta(days=20)
    series = build_load_series(con, load_config(ROOT / "config.yaml"), today=today)

    assert series.days.max() == today
    assert series.last_run_day == last_run
    assert series.ff_run["ctl"].iloc[-1] < series.ff_run["ctl"].loc[last_run]


def test_sensorless_run_is_estimated_and_walks_are_added(warehouse):
    con, last_run = warehouse
    series = build_load_series(con, load_config(ROOT / "config.yaml"), today=last_run + dt.timedelta(days=10))

    assert list(series.estimated_days) == [last_run]
    assert series.estimated.sum() > 0
    assert series.hr_fit is not None and series.hr_fit[2] == 12
    assert len(series.walks) == 2 and len(series.walks_counted) == 1  # the walk with no HR is not counted
    assert series.walk_load.sum() == pytest.approx(50.0)
    assert (series.total_load - series.run_load - series.walk_load).abs().max() == 0
