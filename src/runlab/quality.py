"""Data-quality audit.

Each check returns (failed, total). A check passes when failed / total is within
its tolerance. Severity `error` fails the pipeline; `warn` and `info` are
reported but let the build continue, because real sensor data is never clean
and the point is to measure and document the mess, not hide it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from runlab.config import Config
from runlab.warehouse import connect


@dataclass(frozen=True)
class Check:
    name: str
    severity: str  # error | warn | info
    tolerance: float  # max acceptable failed/total
    description: str
    sql: str  # must return one row: failed, total


CHECKS: list[Check] = [
    Check(
        "device_duplicates",
        "info",
        1.0,
        "Sessions uploaded twice by two devices; the GPS copy is kept, the other excluded",
        "SELECT count(*) FILTER (WHERE is_device_duplicate), count(*) FROM staging.stg_activities",
    ),
    Check(
        "export_duplicate_rows",
        "warn",
        0.0,
        "activities.csv has no repeated Activity IDs (staging keeps the first)",
        "SELECT count(*) - count(DISTINCT activity_id), count(*) FROM raw.activities",
    ),
    Check(
        "activity_id_unique",
        "error",
        0.0,
        "Activity IDs are unique after staging",
        "SELECT count(*) - count(DISTINCT activity_id), count(*) FROM staging.stg_activities",
    ),
    Check(
        "activity_date_parsed",
        "error",
        0.0,
        "Every activity date parsed to a timestamp",
        "SELECT count(*) FILTER (WHERE start_utc IS NULL), count(*) FROM raw.activities",
    ),
    Check(
        "no_future_activities",
        "error",
        0.0,
        "No activity is dated in the future",
        "SELECT count(*) FILTER (WHERE start_utc > now()::TIMESTAMP + INTERVAL 1 DAY), count(*) "
        "FROM raw.activities",
    ),
    Check(
        "no_negative_values",
        "error",
        0.0,
        "Distance and moving time are never negative",
        "SELECT count(*) FILTER (WHERE distance_m < 0 OR moving_s < 0), count(*) FROM marts.fct_runs",
    ),
    Check(
        "run_stream_available",
        "warn",
        0.05,
        "Runs have a parseable GPS/HR stream file",
        "SELECT count(*) FILTER (WHERE status NOT IN ('parsed', 'cached')), count(*) "
        "FROM raw.ingest_log WHERE status <> 'skipped_non_run'",
    ),
    Check(
        "stream_parse_errors",
        "warn",
        0.0,
        "Stream files parse without errors",
        "SELECT count(*) FILTER (WHERE status = 'parse_error'), count(*) "
        "FROM raw.ingest_log WHERE status <> 'skipped_non_run'",
    ),
    Check(
        "hr_coverage",
        "warn",
        0.10,
        "Runs recorded with a heart-rate sensor have HR for at least 80% of moving time",
        "SELECT count(*) FILTER (WHERE hr_coverage < 0.8), count(*) "
        "FROM marts.fct_runs WHERE has_stream AND hr_coverage IS NOT NULL",
    ),
    Check(
        "runs_without_hr_sensor",
        "info",
        1.0,
        "Runs recorded with no heart-rate sensor at all (no TRIMP; handled in the load chapter)",
        "SELECT count(*) FILTER (WHERE hr_coverage IS NULL), count(*) FROM marts.fct_runs",
    ),
    Check(
        "hr_sample_validity",
        "warn",
        0.01,
        "Heart-rate samples fall inside the physiologically valid range",
        "SELECT count(*) FILTER (WHERE hr_raw IS NOT NULL AND hr IS NULL), "
        "count(*) FILTER (WHERE hr_raw IS NOT NULL) FROM staging.stg_records",
    ),
    Check(
        "gps_speed_spikes",
        "warn",
        0.005,
        "GPS speed samples are below the spike threshold",
        "SELECT count(*) FILTER (WHERE is_speed_spike), count(*) FROM staging.stg_records",
    ),
    Check(
        "distance_agreement",
        "warn",
        0.10,
        "Stream distance is within 5% of Strava's recorded distance",
        """
        WITH s AS (
            SELECT activity_id, max(distance_m) - min(distance_m) AS stream_m
            FROM staging.stg_records GROUP BY activity_id
        )
        SELECT count(*) FILTER (WHERE abs(s.stream_m - a.distance_m) / a.distance_m > 0.05),
               count(*)
        FROM s JOIN staging.stg_activities a USING (activity_id)
        WHERE a.distance_m > 0 AND NOT a.is_treadmill
        """,
    ),
    Check(
        "long_pauses",
        "info",
        1.0,
        "Runs containing a recording gap longer than 5 minutes (watch paused or stopped)",
        """
        SELECT count(DISTINCT activity_id) FILTER (WHERE gap_s > 300),
               count(DISTINCT activity_id)
        FROM staging.stg_records
        """,
    ),
    Check(
        "treadmill_runs",
        "info",
        1.0,
        "Treadmill / virtual runs (pace comes from the device, not GPS)",
        "SELECT count(*) FILTER (WHERE is_treadmill), count(*) FROM marts.fct_runs",
    ),
]


def run_checks(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    rows = []
    for check in CHECKS:
        failed, total = con.execute(check.sql).fetchone()
        failed, total = int(failed or 0), int(total or 0)
        rate = failed / total if total else 0.0
        if rate <= check.tolerance:
            status = "PASS"
        else:
            status = {"error": "FAIL", "warn": "WARN", "info": "INFO"}[check.severity]
        rows.append(
            dict(
                check_name=check.name,
                severity=check.severity,
                status=status,
                failed=failed,
                total=total,
                rate=round(rate, 4),
                tolerance=check.tolerance,
                description=check.description,
            )
        )
    report = pd.DataFrame(rows)
    con.register("dq_df", report)
    con.execute("CREATE OR REPLACE TABLE marts.dq_report AS SELECT *, now() AS checked_at FROM dq_df")
    con.unregister("dq_df")
    return report


def write_markdown(report: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Data quality report",
        "",
        f"_Generated {dt.datetime.now():%Y-%m-%d %H:%M} by `runlab quality`._",
        "",
        "| Status | Check | Failed / total | Rate | Tolerance | What it means |",
        "|---|---|---|---|---|---|",
    ]
    for r in report.itertuples():
        lines.append(
            f"| {r.status} | `{r.check_name}` | {r.failed:,} / {r.total:,} | {r.rate:.2%} "
            f"| {r.tolerance:.1%} | {r.description} |"
        )
    path.write_text("\n".join(lines) + "\n")


def audit(cfg: Config) -> pd.DataFrame:
    with connect(cfg) as con:
        report = run_checks(con)
    write_markdown(report, cfg.root / "reports" / "data_quality.md")
    return report
