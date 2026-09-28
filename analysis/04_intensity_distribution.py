"""Chapter 5: intensity distribution -- how training time splits across effort.

Zones are defined by percent heart-rate reserve (Karvonen): HRR = (HR - rest)
/ (max - rest). Endurance coaches' "polarized" model calls for roughly 80% of
training time easy (Z1-Z2) and no more than about 20% moderate-to-hard
(Z3-Z5), on the theory that too much time in the uncomfortable middle zone
(Z3) builds fatigue without much fitness benefit ("junk miles").

Usage: python analysis/04_intensity_distribution.py [--config config.yaml]
Output: reports/figures/intensity_distribution.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from runlab.config import load_config
from runlab.warehouse import connect

ZONES = [
    ("Z1 recovery (<60% HRR)", 0.60),
    ("Z2 easy aerobic (60-70%)", 0.70),
    ("Z3 tempo (70-80%)", 0.80),
    ("Z4 threshold (80-90%)", 0.90),
    ("Z5 max effort (90%+)", None),
]

QUERY = """
SELECT
    CASE
        WHEN (r.hr - p.hr_rest) / (p.hr_max - p.hr_rest) < 0.60 THEN 'Z1 recovery (<60% HRR)'
        WHEN (r.hr - p.hr_rest) / (p.hr_max - p.hr_rest) < 0.70 THEN 'Z2 easy aerobic (60-70%)'
        WHEN (r.hr - p.hr_rest) / (p.hr_max - p.hr_rest) < 0.80 THEN 'Z3 tempo (70-80%)'
        WHEN (r.hr - p.hr_rest) / (p.hr_max - p.hr_rest) < 0.90 THEN 'Z4 threshold (80-90%)'
        ELSE 'Z5 max effort (90%+)'
    END AS zone,
    sum(r.gap_s) AS seconds
FROM staging.stg_records AS r
CROSS JOIN staging.params AS p
WHERE r.is_moving AND r.hr IS NOT NULL
GROUP BY 1
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)

    with connect(cfg, read_only=True) as con:
        df = con.execute(QUERY).df()

    if df.empty:
        raise SystemExit("No heart-rate-validated moving time found; run `runlab build` first.")

    df = df.set_index("zone").reindex([z for z, _ in ZONES], fill_value=0)
    total_s = df["seconds"].sum()
    pct = 100 * df["seconds"] / total_s

    easy_pct = pct.iloc[0] + pct.iloc[1]
    moderate_pct = pct.iloc[2]
    hard_pct = pct.iloc[3] + pct.iloc[4]

    print(f"  {total_s / 3600:.1f} hours of HR-validated moving time across all runs")
    for zone, share in pct.items():
        print(f"    {zone:<28} {share:5.1f}%")
    print(f"  easy (Z1-Z2): {easy_pct:.0f}%   Z3: {moderate_pct:.0f}%   hard (Z4-Z5): {hard_pct:.0f}%")
    print("  polarized-model target: ~80% easy, ~20% moderate-to-hard, little time in Z3")

    fig, ax = plt.subplots(figsize=(8, 4.5))
    colors = ["#4c72b0", "#64a6bd", "#dd8452", "#c44e52", "#8c2d19"]
    bars = ax.barh(pct.index[::-1], pct.values[::-1], color=colors[::-1])
    for bar, value in zip(bars, pct.values[::-1], strict=True):
        ax.text(value + 0.5, bar.get_y() + bar.get_height() / 2, f"{value:.0f}%", va="center", fontsize=9)
    ax.set_xlabel("Share of HR-validated moving time (%)")
    ax.set_title("Training intensity distribution")
    ax.set_xlim(0, max(60, pct.max() + 12))
    ax.text(
        0.99,
        0.03,
        f"easy (Z1-Z2): {easy_pct:.0f}%   Z3: {moderate_pct:.0f}%   hard (Z4-Z5): {hard_pct:.0f}%\n"
        "polarized-model target: ~80% easy, little time in Z3",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
    )
    fig.tight_layout()

    out_path = Path("reports/figures/intensity_distribution.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"  saved {out_path}")


if __name__ == "__main__":
    main()
