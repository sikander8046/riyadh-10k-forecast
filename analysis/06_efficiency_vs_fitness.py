"""Forecast groundwork: does efficiency follow fitness?

Chapter 3 found no reliable straight-line trend in efficiency (EF, speed per
heartbeat) over the calendar -- unsurprising, because training came in bursts and
fitness built and faded. This tests the better question: is EF higher when fitness
(CTL, from the training-load model) is higher?

For each comparable run, fitness is the value the day BEFORE the run (so the run's
own load cannot leak into it). Two versions are compared: total aerobic fitness
(running + walking) and running-only fitness. Each is fitted on its own and with
dew point and average heart rate held constant.

Limits worth stating: runs on nearby days share almost the same fitness, so the
reported margins are optimistic; and the history cannot tell whether walking
fitness carries over to running, because there are no runs during the walking-only
stretch since May 2026.

Usage: python analysis/06_efficiency_vs_fitness.py [--config config.yaml]
Output: reports/figures/efficiency_vs_fitness.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from runlab.config import load_config
from runlab.models.load_series import build_load_series, to_dates
from runlab.warehouse import connect

REF_HR = 150

BASE = """
SELECT r.local_date, r.ef, r.avg_hr, {dew} AS dew_point_c
FROM marts.fct_runs AS r
{join}
WHERE r.has_gps AND NOT r.is_treadmill AND r.hr_coverage IS NOT NULL
  AND r.distance_m > 3000 AND r.ef IS NOT NULL
ORDER BY r.local_date
"""
QUERY = BASE.format(dew="c.dew_point_c", join="LEFT JOIN marts.fct_run_conditions AS c USING (activity_id)")
QUERY_NO_WEATHER = BASE.format(dew="NULL::DOUBLE", join="")


def ols(y: np.ndarray, columns: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray, float]:
    """Least squares with intercept: coefficients, standard errors, R-squared."""
    x = np.column_stack([np.ones(len(y)), *columns])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    sigma2 = resid @ resid / (len(y) - x.shape[1])
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv(x.T @ x)))
    r2 = 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))
    return beta, se, float(r2)


def seconds_per_km_gain(median_ef: float, delta_ef: float) -> float:
    return 60000 / (REF_HR * median_ef) - 60000 / (REF_HR * (median_ef + delta_ef))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)

    with connect(cfg, read_only=True) as con:
        series = build_load_series(con, cfg)
        try:
            runs = con.execute(QUERY).df()
        except duckdb.CatalogException:
            runs = con.execute(QUERY_NO_WEATHER).df()

    runs["local_date"] = to_dates(runs["local_date"])
    runs["ctl_total"] = series.ff_total["ctl"].shift(1).reindex(runs["local_date"]).to_numpy()
    runs["ctl_run"] = series.ff_run["ctl"].shift(1).reindex(runs["local_date"]).to_numpy()
    df = runs.dropna(subset=["ctl_total", "ctl_run", "dew_point_c"]).reset_index(drop=True)
    if len(df) < 15:
        raise SystemExit(f"Only {len(df)} runs with fitness and weather; need at least 15.")

    y = df["ef"].to_numpy()
    hr_term = ((df["avg_hr"] - REF_HR) / 10).to_numpy()
    dew = df["dew_point_c"].to_numpy()
    median_ef = float(np.median(y))

    lo, mid, hi = df["ctl_total"].min(), df["ctl_total"].median(), df["ctl_total"].max()
    print(
        f"  {len(df)} comparable runs; fitness before each run: min {lo:.1f}, median {mid:.1f}, max {hi:.1f}"
    )
    print(
        f"  simple correlation with EF: total fitness r = {np.corrcoef(df['ctl_total'], y)[0, 1]:+.2f}, "
        f"running-only fitness r = {np.corrcoef(df['ctl_run'], y)[0, 1]:+.2f}"
    )

    fits = {}
    for label, column in (("total (running + walking)", "ctl_total"), ("running only", "ctl_run")):
        beta, se, r2 = ols(y, [df[column].to_numpy(), dew, hr_term])
        fits[column] = (beta, se, r2)
        per10 = 10 * beta[1]
        gain = seconds_per_km_gain(median_ef, per10)
        print(
            f"  EF ~ {label} fitness + dew point + heart rate: {per10:+.3f} per +10 fitness points "
            f"(+/- {20 * se[1]:.3f}), R2 {r2:.2f}, about {gain:+.0f} s/km at {REF_HR} bpm"
        )
    print(
        f"  as of today, total fitness {series.ff_total['ctl'].iloc[-1]:.1f} and "
        f"running-only {series.ff_run['ctl'].iloc[-1]:.1f} (should match the training-load chart)"
    )

    beta, se, r2 = fits["ctl_total"]
    adjusted = y - beta[2] * (dew - dew.mean()) - beta[3] * (hr_term - hr_term.mean())
    x = df["ctl_total"].to_numpy()
    xs = np.linspace(x.min(), x.max(), 50)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.8))
    points = ax1.scatter(x, y, c=dew, cmap="viridis", s=28, alpha=0.85, edgecolor="none")
    fig.colorbar(points, ax=ax1, label="dew point (\u00b0C)", pad=0.02)
    raw_slope, raw_intercept = np.polyfit(x, y, 1)
    ax1.plot(xs, raw_slope * xs + raw_intercept, color="black", linewidth=1.5)
    ax1.set_xlabel("Total fitness (CTL) the day before the run")
    ax1.set_ylabel("Efficiency factor (speed per heartbeat)")
    ax1.set_title("Raw", fontsize=11)

    ax2.scatter(x, adjusted, color="#4c72b0", s=28, alpha=0.85, edgecolor="none")
    ax2.plot(xs, beta[1] * xs + (adjusted.mean() - beta[1] * x.mean()), color="black", linewidth=1.5)
    ax2.set_xlabel("Total fitness (CTL) the day before the run")
    ax2.set_ylabel(f"EF adjusted to average dew point and {REF_HR} bpm")
    ax2.set_title("Adjusted for heat and effort", fontsize=11)
    ax2.text(
        0.02,
        0.97,
        f"n = {len(df)} runs\n{10 * beta[1]:+.3f} EF per +10 fitness points "
        f"(+/- {20 * se[1]:.3f})\nR2 {r2:.2f}",
        transform=ax2.transAxes,
        fontsize=8.5,
        va="top",
    )
    fig.suptitle("Does efficiency follow fitness?")
    fig.tight_layout()

    out_path = Path("reports/figures/efficiency_vs_fitness.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"  saved {out_path}")


if __name__ == "__main__":
    main()
