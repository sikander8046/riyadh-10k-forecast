"""Chapter 2: training load -- fitness, fatigue and form, from running AND walking.

Load is TRIMP: heart-rate-weighted training minutes (Banister). Two things in a
real training history would distort it if left alone:

  1. Some runs have no heart-rate data (a phone-only stretch), so they carry no
     TRIMP and would count as rest days. Their load is estimated from a simple
     pace -> heart-rate fit on the athlete's HR-validated runs, and those days
     are shaded on the chart so measured and inferred load are never mixed
     silently.
  2. Running is not the only aerobic work. Walks and hikes recorded with heart
     rate (marts.fct_walks) are added to give TOTAL aerobic load, drawn next to
     running-only fitness. Walking builds the aerobic base but not the impact
     tolerance of running, so the two curves are kept apart.

CTL/ATL are exponential averages of daily load (42-day and 7-day time
constants), so the model runs through every day up to today: days with no
recorded training are rest days, and fitness keeps decaying through them.

Usage:
  python analysis/02_training_load.py
  python analysis/02_training_load.py --full-history
Output: reports/figures/training_load.png
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

from runlab.config import load_config
from runlab.models.load import acwr, fitness_fatigue
from runlab.warehouse import connect

RACE_DATE = dt.date(2027, 1, 30)

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


def to_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.date


def estimate_missing_trimp(cfg, real_hr: pd.DataFrame, missing: pd.DataFrame) -> pd.Series:
    """Predicted-HR TRIMP for runs with pace but no heart-rate sensor.

    Returns total estimated TRIMP per local_date (summed if more than one
    such run fell on the same day). Empty Series if there is nothing to fit
    or nothing to estimate.
    """
    if len(missing) == 0 or len(real_hr) < 8:
        return pd.Series(dtype=float)

    slope, intercept = np.polyfit(real_hr["pace_s_per_km"], real_hr["avg_hr"], 1)
    predicted_hr = np.clip(intercept + slope * missing["pace_s_per_km"], cfg.hr_rest + 5, cfg.hr_max - 1)
    hrr = (predicted_hr - cfg.hr_rest) / (cfg.hr_max - cfg.hr_rest)
    a, b = cfg.trimp_coefficients
    trimp_est = (missing["moving_s"] / 60.0) * hrr * a * np.exp(b * hrr)
    print(f"  pace -> HR fit: HR = {intercept:.1f} {slope:+.4f} * pace_s_per_km  (n={len(real_hr)})")
    return trimp_est.groupby(missing["local_date"]).sum()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--full-history",
        action="store_true",
        help="plot the entire history instead of zooming to the current training block",
    )
    args = parser.parse_args()
    cfg = load_config(args.config)

    with connect(cfg, read_only=True) as con:
        real_hr = con.execute(REAL_HR_QUERY).df()
        missing = con.execute(MISSING_HR_QUERY).df()
        daily = con.execute(DAILY_QUERY).df()
        try:
            walks = con.execute(WALK_QUERY).df()
        except duckdb.CatalogException:
            walks = pd.DataFrame(columns=["local_date", "moving_s", "distance_m", "trimp_est"])
            print("  (marts.fct_walks not found: run `runlab build` to include walks and hikes)")

    if daily.empty:
        raise SystemExit("No daily load found; run `runlab build` first.")

    daily["day"] = to_dates(daily["day"])
    daily = daily.set_index("day")
    missing["local_date"] = to_dates(missing["local_date"])
    walks["local_date"] = to_dates(walks["local_date"])
    walks_counted = walks.dropna(subset=["trimp_est"])

    # The daily table stops at the last recorded run. Build one continuous daily
    # spine from the first load to today, so rest days (and days after the last
    # activity) exist and CTL/ATL keep decaying through them.
    last_run_day = daily.index.max()
    today = dt.date.today()
    start_day = daily.index.min()
    end_day = max(today, last_run_day)
    if len(walks):
        end_day = max(end_day, walks["local_date"].max())
    if len(walks_counted):
        start_day = min(start_day, walks_counted["local_date"].min())
    daily = daily.reindex(pd.date_range(start_day, end_day, freq="D").date)
    daily["km"] = daily["km"].fillna(0.0)
    daily["trimp"] = daily["trimp"].fillna(0.0)

    walk_load = walks_counted.groupby("local_date")["trimp_est"].sum().reindex(daily.index, fill_value=0.0)
    walk_km = (
        (walks.groupby("local_date")["distance_m"].sum() / 1000.0)
        .reindex(daily.index, fill_value=0.0)
        .fillna(0.0)
    )

    estimated = estimate_missing_trimp(cfg, real_hr, missing)
    estimated = (
        estimated.reindex(daily.index, fill_value=0.0)
        if len(estimated)
        else pd.Series(0.0, index=daily.index)
    )
    estimated_days = daily.index[estimated > 0]

    run_measured = daily["trimp"].fillna(0.0)
    run_load = run_measured + estimated
    total_load = run_load + walk_load

    ff_measured = fitness_fatigue(run_measured)
    ff_run = fitness_fatigue(run_load)
    ff_total = fitness_fatigue(total_load)
    acwr_total = acwr(total_load)

    days_since_last_run = (today - last_run_day).days
    days_to_race = (RACE_DATE - today).days

    if len(estimated_days):
        check_day = min(last_run_day, estimated_days.max() + dt.timedelta(days=7))
        pos = daily.index.get_loc(check_day)
        print(
            f"  running fitness (CTL) right after the no-sensor fix ({check_day}): "
            f"{ff_measured['ctl'].iloc[pos]:.1f} measured-only -> {ff_run['ctl'].iloc[pos]:.1f} corrected"
        )
    print(f"  {len(estimated_days)} day(s) of running had load estimated from pace (no HR sensor)")
    print(
        f"  walks and hikes counted: {len(walks_counted)} sessions, "
        f"{walks_counted['moving_s'].sum() / 3600:.1f} h; "
        f"{len(walks) - len(walks_counted)} had no heart rate and are not counted"
    )

    pos_last = daily.index.get_loc(last_run_day)
    print(
        f"  as of your last recorded run ({last_run_day}): running fitness (CTL) "
        f"{ff_run['ctl'].iloc[pos_last]:.1f}, total {ff_total['ctl'].iloc[pos_last]:.1f}"
    )
    ctl_now, atl_now = ff_total["ctl"].iloc[-1], ff_total["atl"].iloc[-1]
    ctl_run_now = ff_run["ctl"].iloc[-1]
    tsb_now = ctl_now - atl_now
    peak_day = ff_total["ctl"].idxmax()
    peak = ff_total["ctl"].max()
    print(
        f"  today ({today}, {days_since_last_run} days after that run): total fitness (CTL) {ctl_now:.1f} "
        f"(running only {ctl_run_now:.1f}), fatigue (ATL) {atl_now:.1f}, form (TSB) {tsb_now:+.1f}"
    )
    print(
        f"  peak total fitness (CTL) {peak:.1f} on {peak_day}; today is {100 * ctl_now / peak:.0f}% of that"
        f"   |   ACWR today {acwr_total.iloc[-1]:.2f}"
    )
    print(f"  {days_to_race} days to the Riyadh Marathon 10K ({RACE_DATE}), counted from today")

    # Where the CURRENT continuous block of training starts: the most recent day
    # with activity preceded by at least 90 days with none. Long-past isolated
    # activities would otherwise stretch the chart across mostly-empty years.
    km_all = daily["km"] + walk_km
    trailing_90d = km_all.shift(1).rolling(90, min_periods=1).sum()
    fresh_starts = daily.index[(trailing_90d == 0) & (km_all > 0)]
    block_start = fresh_starts.max() if len(fresh_starts) else daily.index.min()
    earlier = daily.index[(daily.index < block_start) & (km_all > 0)]
    if len(earlier):
        gap_days = (block_start - earlier.max()).days
        print(
            f"  current training block began {block_start} (after a {gap_days}-day gap with no "
            f"recorded activity); the chart zooms to this block (use --full-history to see everything)"
        )

    fig, (ax_km, ax_load) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True, height_ratios=[1, 2.2])
    ax_km.bar(daily.index, daily["km"], color="#4c72b0", width=1.0, label="running")
    ax_km.bar(daily.index, walk_km, bottom=daily["km"], color="#9ecae1", width=1.0, label="walking / hiking")
    ax_km.set_ylabel("km/day")
    ax_km.legend(loc="upper left", fontsize=8)
    title = "Training load: fitness (CTL), fatigue (ATL) and form (TSB)"
    if not args.full_history:
        title += "  [current training block]"
        ax_load.set_xlim(
            pd.Timestamp(block_start) - pd.Timedelta(days=5),
            pd.Timestamp(max(today, RACE_DATE)) + pd.Timedelta(days=5),
        )
    ax_km.set_title(title)

    ax_load.plot(ff_total.index, ff_total["ctl"], label="Fitness (CTL): running + walking", color="black")
    ax_load.plot(
        ff_run.index, ff_run["ctl"], label="Fitness (CTL): running only", color="#7f7f7f", linestyle=":"
    )
    ax_load.plot(
        ff_total.index,
        ff_total["atl"],
        label="Fatigue (ATL): running + walking",
        color="#c44e52",
        linestyle="--",
    )
    for day in estimated_days:
        ax_load.axvspan(
            pd.Timestamp(day) - pd.Timedelta(hours=12),
            pd.Timestamp(day) + pd.Timedelta(hours=12),
            color="#dd8452",
            alpha=0.25,
        )
    ax_load.set_ylabel("TRIMP-based load")
    handles, labels = ax_load.get_legend_handles_labels()
    if len(estimated_days):
        handles.append(Patch(color="#dd8452", alpha=0.25))
        labels.append("Run load estimated (no HR sensor)")
    ax_load.legend(handles, labels, loc="upper left", fontsize=8)

    ax_load.axvline(pd.Timestamp(RACE_DATE), color="black", linestyle=":", linewidth=1)
    ax_load.text(
        pd.Timestamp(RACE_DATE) - pd.Timedelta(days=4),
        0.97,
        "race day",
        transform=ax_load.get_xaxis_transform(),
        ha="right",
        va="top",
        fontsize=8,
    )
    ax_load.text(
        0.74,
        0.95,
        f"today ({today}): total CTL {ctl_now:.1f} (running only {ctl_run_now:.1f})\n"
        f"ATL {atl_now:.1f}   TSB {tsb_now:+.1f}\n"
        f"peak total CTL {peak:.1f} on {peak_day}",
        transform=ax_load.transAxes,
        ha="right",
        va="top",
        fontsize=9,
    )
    fig.tight_layout()

    out_path = Path("reports/figures/training_load.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"  saved {out_path}")


if __name__ == "__main__":
    main()
