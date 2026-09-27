"""Command line entry point: `runlab ingest | build | quality | all | summary`."""

from __future__ import annotations

import argparse
import logging
import sys

from runlab.config import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="runlab", description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="parse the Strava export into Parquet")
    ingest.add_argument("--force", action="store_true", help="re-parse every stream file")
    sub.add_parser("build", help="rebuild the DuckDB warehouse")
    sub.add_parser("quality", help="run the data-quality audit")
    all_ = sub.add_parser("all", help="ingest + build + quality")
    all_.add_argument("--force", action="store_true")
    sub.add_parser("summary", help="print headline numbers from the warehouse")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config(args.config)

    if args.command in ("ingest", "all"):
        from runlab.ingest.pipeline import run_ingest

        print(f"[ingest] {run_ingest(cfg, force=args.force)}")

    if args.command in ("build", "all"):
        from runlab.warehouse import build

        models = build(cfg)
        print(f"[build]  {len(models)} models: {', '.join(models)}")

    if args.command in ("quality", "all"):
        from runlab.quality import audit

        report = audit(cfg)
        print("[quality]")
        print(report[["status", "check_name", "failed", "total", "rate"]].to_string(index=False))
        if (report["status"] == "FAIL").any():
            print("Data-quality errors found; see reports/data_quality.md", file=sys.stderr)
            return 1

    if args.command == "summary":
        _summary(cfg)
    return 0


def _summary(cfg) -> None:
    from runlab.warehouse import connect

    with connect(cfg, read_only=True) as con:
        print(
            con.execute(
                """
            SELECT count(*) AS runs,
                   round(sum(distance_m) / 1000, 1) AS total_km,
                   min(local_date) AS first_run,
                   max(local_date) AS last_run,
                   round(avg(hr_coverage), 3) AS mean_hr_coverage
            FROM marts.fct_runs
            """
            )
            .df()
            .to_string(index=False)
        )
        print()
        print(
            con.execute(
                """
            SELECT day, round(ctl, 1) AS fitness_ctl, round(atl, 1) AS fatigue_atl,
                   round(tsb, 1) AS form_tsb, round(acwr, 2) AS acwr
            FROM marts.fct_fitness ORDER BY day DESC LIMIT 7
            """
            )
            .df()
            .to_string(index=False)
        )


if __name__ == "__main__":
    raise SystemExit(main())
