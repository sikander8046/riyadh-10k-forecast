"""Chapter 3: aerobic efficiency -- am I actually getting fitter?

Efficiency factor (EF) = speed per heartbeat. If EF rises across comparable
runs, the same heart rate buys more speed: aerobic fitness improved. Heat and
effort both move EF too, so the trend is estimated twice:

  A. on its own (EF against time), and
  B. holding dew point and average heart rate constant (a small regression),

and the two are shown side by side so the reader can see how much of the
"trend" is really weather or effort.

Also reports aerobic decoupling on long runs: how much heart rate drifts up
relative to pace between the first and second half (positive = drifted up).

Usage: python analysis/05_aerobic_efficiency.py [--config config.yaml]
Output: reports/figures/aerobic_efficiency.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from runlab.config import load_config
from runlab.warehouse import connect

REF_HR = 150  # heart rate used to translate an EF change into seconds per km
MIN_LONG_RUN_S = 40 * 60  # decoupling is only meaningful on runs of 40+ minutes

BASE = """
SELECT r.activity_id, r.local_date, r.ef, r.avg_hr, r.moving_s, r.decoupling_pct,
       {dew} AS dew_point_c
FROM marts.fct_runs AS r
{join}
WHERE r.has_gps AND NOT r.is_treadmill AND r.hr_coverage IS NOT NULL
  AND r.distance_m > 3000 AND r.ef IS NOT NULL
ORDER BY r.local_date
"""
QUERY = BASE.format(dew="c.dew_point_c", join="LEFT JOIN marts.fct_run_conditions AS c USING (activity_id)")
QUERY_NO_WEATHER = BASE.format(dew="NULL::DOUBLE", join="")


def ols(y: np.ndarray, columns: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Least squares with intercept; returns coefficients and standard errors."""
    x = np.column_stack([np.ones(len(y)), *columns])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    dof = len(y) - x.shape[1]
    sigma2 = resid @ resid / dof
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv(x.T @ x)))
    return beta, se


def seconds_per_km_gain(median_ef: float, slope: float) -> float:
    """How many seconds per km faster at REF_HR an EF change of `slope` is worth."""
    return 60000 / (REF_HR * median_ef) - 60000 / (REF_HR * (median_ef + slope))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)

    with connect(cfg, read_only=True) as con:
        try:
            df = con.execute(QUERY).df()
        except duckdb.CatalogException:
            df = con.execute(QUERY_NO_WEATHER).df()
            print("  (no weather table: run `make weather` to control for heat)")

    df["date"] = pd.to_datetime(df["local_date"])
    if len(df) < 8:
        raise SystemExit(f"Only {len(df)} qualifying runs; need at least 8 to estimate a trend.")

    df["years"] = (df["date"] - df["date"].min()).dt.days / 365.25
    median_ef = float(df["ef"].median())
    first, last = df["date"].min(), df["date"].max()
    print(f"  {len(df)} comparable runs (GPS, HR sensor, over 3 km): {first:%Y-%m-%d} to {last:%Y-%m-%d}")

    monthly = (
        df.assign(month=df["date"].dt.strftime("%Y-%m"))
        .groupby("month")
        .agg(
            runs=("ef", "size"),
            median_ef=("ef", "median"),
            median_hr=("avg_hr", "median"),
            dew=("dew_point_c", "median"),
        )
        .round(2)
    )
    print(monthly.to_string())

    beta_a, se_a = ols(df["ef"].to_numpy(), [df["years"].to_numpy()])
    gain_a = seconds_per_km_gain(median_ef, beta_a[1])
    print(
        f"  A. time only: EF {beta_a[1]:+.3f} per year (+/- {2 * se_a[1]:.3f}), "
        f"about {gain_a:+.0f} s/km faster at {REF_HR} bpm per year"
    )

    model_b = df.dropna(subset=["dew_point_c"])
    beta_b = se_b = None
    if len(model_b) >= 12:
        beta_b, se_b = ols(
            model_b["ef"].to_numpy(),
            [
                model_b["years"].to_numpy(),
                model_b["dew_point_c"].to_numpy(),
                ((model_b["avg_hr"] - REF_HR) / 10).to_numpy(),
            ],
        )
        gain_b = seconds_per_km_gain(median_ef, beta_b[1])
        print(
            f"  B. holding dew point and heart rate constant (n={len(model_b)}): "
            f"EF {beta_b[1]:+.3f} per year (+/- {2 * se_b[1]:.3f}), about {gain_b:+.0f} s/km per year"
        )
        print(
            f"     per +1 C dew point: EF {beta_b[2]:+.4f} (+/- {2 * se_b[2]:.4f});  "
            f"per +10 bpm average HR: EF {beta_b[3]:+.4f} (+/- {2 * se_b[3]:.4f})"
        )
    else:
        print("  B. skipped: too few runs with weather data to control for heat")

    long_runs = df[(df["moving_s"] >= MIN_LONG_RUN_S) & df["decoupling_pct"].notna()]
    if len(long_runs):
        median_drift = long_runs["decoupling_pct"].median()
        print(
            f"  decoupling on {len(long_runs)} runs of 40+ min: median {median_drift:+.1f}% "
            f"(over 5% suggests the aerobic base is the limiter)"
        )

    fig, axes = plt.subplots(
        2 if len(long_runs) >= 5 else 1,
        1,
        figsize=(9, 7 if len(long_runs) >= 5 else 4.8),
        sharex=True,
        squeeze=False,
    )
    ax = axes[0][0]
    has_dew = df["dew_point_c"].notna().any()
    points = ax.scatter(
        df["date"],
        df["ef"],
        c=df["dew_point_c"] if has_dew else "#4c72b0",
        cmap="viridis" if has_dew else None,
        s=28,
        alpha=0.85,
        edgecolor="none",
    )
    if has_dew:
        fig.colorbar(points, ax=ax, label="dew point (\u00b0C)", pad=0.02)
    monthly_med = df.groupby(df["date"].dt.to_period("M").dt.to_timestamp() + pd.Timedelta(days=14))["ef"]
    med = monthly_med.median()[monthly_med.size() >= 3]
    ax.plot(med.index, med.values, color="black", marker="o", linewidth=1.5, label="monthly median (3+ runs)")
    ax.set_ylabel("Efficiency factor (speed per heartbeat)")
    ax.set_title("Aerobic efficiency over time")
    ax.legend(loc="best", fontsize=8)
    summary = f"n = {len(df)} runs\ntime only: EF {beta_a[1]:+.3f}/yr (+/- {2 * se_a[1]:.3f})"
    if beta_b is not None:
        summary += f"\nheat + effort held constant: {beta_b[1]:+.3f}/yr (+/- {2 * se_b[1]:.3f})"
    ax.text(0.99, 0.03, summary, transform=ax.transAxes, ha="right", va="bottom", fontsize=8.5)

    if len(long_runs) >= 5:
        ax2 = axes[1][0]
        ax2.scatter(
            long_runs["date"],
            long_runs["decoupling_pct"],
            color="#c44e52",
            s=28,
            alpha=0.85,
            edgecolor="none",
        )
        ax2.axhline(5, color="black", linestyle=":", linewidth=1)
        ax2.axhline(0, color="#7f7f7f", linewidth=0.8)
        ax2.set_ylabel("Aerobic decoupling (%)")
        ax2.set_title("Cardiac drift on runs of 40+ minutes (above the dotted line: over 5%)", fontsize=10)
    fig.tight_layout()

    out_path = Path("reports/figures/aerobic_efficiency.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"  saved {out_path}")


if __name__ == "__main__":
    main()
