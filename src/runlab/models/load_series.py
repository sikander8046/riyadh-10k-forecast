"""Daily training-load series, shared by the analysis chapters.

For every day from the first recorded load up to today it builds:

  run_load    measured running TRIMP, plus estimated TRIMP for runs recorded with no
              heart-rate sensor (predicted from a pace -> heart-rate fit on the
              athlete's own HR-validated runs)
  walk_load   estimated TRIMP of walks and hikes that have heart rate
  total_load  run_load + walk_load

and runs the fitness-fatigue model (CTL 42-day, ATL 7-day) on running alone and on
the total. Days after the last recorded activity are rest days: fitness keeps
decaying through them, so "today" always means today.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

from runlab.config import Config
from runlab.models.load import fitness_fatigue

REAL_HR_QUERY = """
SELECT pace_s_per_km, avg_hr
FROM marts.fct_runs
WHERE has_gps AND NOT is_treadmill AND hr_coverage IS NOT NULL
  AND pace_s_per_km IS NOT NULL AND avg_hr IS NOT NULL
"""

MISSING_HR_QUERY = """
SELECT local_date, moving_s, pace_s_per_km
FROM marts.fct_runs
WHERE has_gps AND NOT is_treadmill AND hr_coverage IS NULL
  AND moving_s > 0 AND pace_s_per_km IS NOT NULL
"""

DAILY_QUERY = "SELECT day, trimp, km FROM marts.fct_daily_load ORDER BY day"

WALK_QUERY = "SELECT local_date, moving_s, distance_m, trimp_est FROM marts.fct_walks"

MIN_RUNS_FOR_HR_FIT = 8


@dataclass
class LoadSeries:
    days: pd.Index  # one entry per calendar day (datetime.date), first load to today
    run_measured: pd.Series  # running TRIMP from heart rate
    estimated: pd.Series  # running TRIMP estimated for runs with no HR sensor
    walk_load: pd.Series  # walking and hiking TRIMP
    ff_measured: pd.DataFrame  # fitness-fatigue on measured running only
    ff_run: pd.DataFrame  # fitness-fatigue on running incl. estimates
    ff_total: pd.DataFrame  # fitness-fatigue on running + walking
    last_run_day: dt.date
    walks: pd.DataFrame  # every walk/hike row
    walks_counted: pd.DataFrame  # those with a load estimate
    hr_fit: tuple[float, float, int] | None  # (intercept, slope, n) of pace -> HR

    @property
    def run_load(self) -> pd.Series:
        return self.run_measured + self.estimated

    @property
    def total_load(self) -> pd.Series:
        return self.run_load + self.walk_load

    @property
    def estimated_days(self) -> pd.Index:
        return self.days[self.estimated > 0]


def to_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.date


def estimate_missing_trimp(
    cfg: Config, real_hr: pd.DataFrame, missing: pd.DataFrame
) -> tuple[pd.Series, tuple[float, float, int] | None]:
    """Predicted-HR TRIMP per date for runs with a pace but no heart-rate sensor."""
    if len(missing) == 0 or len(real_hr) < MIN_RUNS_FOR_HR_FIT:
        return pd.Series(dtype=float), None

    slope, intercept = np.polyfit(real_hr["pace_s_per_km"], real_hr["avg_hr"], 1)
    predicted_hr = np.clip(intercept + slope * missing["pace_s_per_km"], cfg.hr_rest + 5, cfg.hr_max - 1)
    hrr = (predicted_hr - cfg.hr_rest) / (cfg.hr_max - cfg.hr_rest)
    a, b = cfg.trimp_coefficients
    trimp_est = (missing["moving_s"] / 60.0) * hrr * a * np.exp(b * hrr)
    return trimp_est.groupby(missing["local_date"]).sum(), (float(intercept), float(slope), len(real_hr))


def build_load_series(
    con: duckdb.DuckDBPyConnection, cfg: Config, today: dt.date | None = None
) -> LoadSeries:
    today = today or dt.date.today()
    real_hr = con.execute(REAL_HR_QUERY).df()
    missing = con.execute(MISSING_HR_QUERY).df()
    daily = con.execute(DAILY_QUERY).df()
    try:
        walks = con.execute(WALK_QUERY).df()
    except duckdb.CatalogException:
        walks = pd.DataFrame(columns=["local_date", "moving_s", "distance_m", "trimp_est"])
    if daily.empty:
        raise ValueError("No daily load found; run `runlab build` first.")

    daily["day"] = to_dates(daily["day"])
    daily = daily.set_index("day")
    missing["local_date"] = to_dates(missing["local_date"])
    walks["local_date"] = to_dates(walks["local_date"])
    walks_counted = walks.dropna(subset=["trimp_est"])

    last_run_day = daily.index.max()
    start_day = daily.index.min()
    end_day = max(today, last_run_day)
    if len(walks):
        end_day = max(end_day, walks["local_date"].max())
    if len(walks_counted):
        start_day = min(start_day, walks_counted["local_date"].min())
    days = pd.Index(pd.date_range(start_day, end_day, freq="D").date)
    daily = daily.reindex(days)

    run_measured = daily["trimp"].fillna(0.0)
    walk_load = walks_counted.groupby("local_date")["trimp_est"].sum().reindex(days, fill_value=0.0)
    estimated, hr_fit = estimate_missing_trimp(cfg, real_hr, missing)
    estimated = estimated.reindex(days, fill_value=0.0) if len(estimated) else pd.Series(0.0, index=days)

    run_load = run_measured + estimated
    return LoadSeries(
        days=days,
        run_measured=run_measured,
        estimated=estimated,
        walk_load=walk_load,
        ff_measured=fitness_fatigue(run_measured),
        ff_run=fitness_fatigue(run_load),
        ff_total=fitness_fatigue(run_load + walk_load),
        last_run_day=last_run_day,
        walks=walks,
        walks_counted=walks_counted,
        hr_fit=hr_fit,
    )
