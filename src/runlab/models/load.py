"""Training-load models computed from daily TRIMP.

Fitness-fatigue (Banister impulse-response, exponentially weighted form):
    CTL  chronic training load, 42-day time constant   ("fitness")
    ATL  acute training load, 7-day time constant      ("fatigue")
    TSB  training stress balance = yesterday's CTL - ATL ("form")
Acute:chronic workload ratio (rolling-average form): 7-day mean / 28-day mean.

These are recursive, which SQL expresses poorly, so they live in Python.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

CTL_DAYS = 42
ATL_DAYS = 7


def fitness_fatigue(
    daily_load: pd.Series, ctl_days: int = CTL_DAYS, atl_days: int = ATL_DAYS
) -> pd.DataFrame:
    load = daily_load.fillna(0.0).to_numpy(dtype=float)
    ctl = np.zeros_like(load)
    atl = np.zeros_like(load)
    for i, x in enumerate(load):
        prev_ctl = ctl[i - 1] if i else 0.0
        prev_atl = atl[i - 1] if i else 0.0
        ctl[i] = prev_ctl + (x - prev_ctl) / ctl_days
        atl[i] = prev_atl + (x - prev_atl) / atl_days
    tsb = np.concatenate([[0.0], ctl[:-1] - atl[:-1]])
    return pd.DataFrame({"ctl": ctl, "atl": atl, "tsb": tsb}, index=daily_load.index)


def acwr(daily_load: pd.Series) -> pd.Series:
    acute = daily_load.rolling(7, min_periods=7).mean()
    chronic = daily_load.rolling(28, min_periods=28).mean()
    return (acute / chronic.replace(0, np.nan)).rename("acwr")


def build_fitness_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    daily = con.execute("SELECT day, trimp, km FROM marts.fct_daily_load ORDER BY day").df()
    if daily.empty:
        out = pd.DataFrame(columns=["day", "trimp", "km", "ctl", "atl", "tsb", "acwr"])
    else:
        daily = daily.set_index("day")
        out = pd.concat([daily, fitness_fatigue(daily["trimp"]), acwr(daily["trimp"])], axis=1)
        out = out.reset_index()
    con.register("fitness_df", out)
    con.execute("CREATE OR REPLACE TABLE marts.fct_fitness AS SELECT * FROM fitness_df")
    con.unregister("fitness_df")
    return out
