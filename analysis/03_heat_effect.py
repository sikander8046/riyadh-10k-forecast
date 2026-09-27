"""Chapter 3: does heat slow me down at the same effort?

Efficiency factor (EF) = speed / heart rate: a rough effort-adjusted pace. If
EF falls as some measure of heat rises across similar-effort runs, heat is
costing real pace, not just comfort.

Usage:
  python analysis/03_heat_effect.py --x temp_c
  python analysis/03_heat_effect.py --x humidity_pct
  python analysis/03_heat_effect.py --x dew_point_c
  python analysis/03_heat_effect.py --x temp_c --min-km 4 --max-km 6
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from runlab.config import load_config
from runlab.warehouse import connect

LABELS = {
    "temp_c": "Temperature (\u00b0C)",
    "humidity_pct": "Relative humidity (%)",
    "dew_point_c": "Dew point (\u00b0C)",
    "feels_like_c": "Apparent temperature (\u00b0C)",
}

QUERY = """
SELECT r.activity_id, r.local_date, round(r.distance_m / 1000, 2) AS km, r.ef,
       c.temp_c, c.humidity_pct, c.dew_point_c, c.feels_like_c
FROM marts.fct_runs r
JOIN marts.fct_run_conditions c USING (activity_id)
WHERE r.has_gps
  AND NOT r.is_treadmill
  AND r.hr_coverage IS NOT NULL
  AND r.distance_m > 3000
  AND c.temp_c IS NOT NULL
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--x", default="temp_c", choices=list(LABELS))
    parser.add_argument("--min-km", type=float, default=None)
    parser.add_argument("--max-km", type=float, default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)

    with connect(cfg, read_only=True) as con:
        df = con.execute(QUERY).df()

    tag = args.x
    if args.min_km is not None:
        df = df[df["km"] >= args.min_km]
        tag += f"_min{args.min_km:g}km"
    if args.max_km is not None:
        df = df[df["km"] <= args.max_km]
        tag += f"_max{args.max_km:g}km"

    if len(df) < 5:
        raise SystemExit(f"Only {len(df)} qualifying runs found; need at least 5 to fit a trend.")

    x = df[args.x].to_numpy()
    y = df["ef"].to_numpy()
    slope, intercept = np.polyfit(x, y, 1)
    r = np.corrcoef(x, y)[0, 1]

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.scatter(x, y, alpha=0.6, edgecolor="none")
    xs = np.linspace(x.min(), x.max(), 100)
    ax.plot(xs, slope * xs + intercept, color="black", linewidth=1.5)
    ax.set_xlabel(LABELS[args.x])
    ax.set_ylabel("Efficiency factor (speed per heart-rate beat)")
    title = "Efficiency factor vs. " + LABELS[args.x].split(" (")[0].lower()
    if args.min_km or args.max_km:
        title += f"  [{args.min_km or 0:g}-{args.max_km or 99:g} km runs]"
    ax.set_title(title)
    ax.text(
        0.02, 0.02,
        f"n = {len(df)} runs\nr = {r:.2f}\nEF change per +1 unit: {slope:+.4f}",
        transform=ax.transAxes, va="bottom", fontsize=9,
    )
    fig.tight_layout()

    out_path = Path(f"reports/figures/heat_effect_{tag}.png")
    fig.savefig(out_path, dpi=150)
    print(f"x={args.x} | n={len(df)} runs | r={r:.3f} | slope={slope:+.5f} | saved {out_path}")


if __name__ == "__main__":
    main()
