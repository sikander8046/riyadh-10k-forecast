"""Ingestion step: export folder -> privacy-trimmed Parquet in data/interim.

Incremental by design: each activity's records are written to their own Parquet
file and skipped on later runs unless the source file is newer, so a weekly
refresh of a multi-year export takes seconds.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from runlab.config import Config
from runlab.ingest.activities import load_activities
from runlab.ingest.streams import parse_stream
from runlab.privacy import trim_endpoints

log = logging.getLogger(__name__)


@dataclass
class IngestSummary:
    activities: int
    runs: int
    parsed: int
    cached: int
    missing_file: int
    failed: int
    seconds: float

    def __str__(self) -> str:
        return (
            f"{self.activities} activities ({self.runs} runs): {self.parsed} parsed, "
            f"{self.cached} cached, {self.missing_file} without stream file, "
            f"{self.failed} failed [{self.seconds:.1f}s]"
        )


def run_ingest(cfg: Config, force: bool = False) -> IngestSummary:
    t0 = time.perf_counter()
    records_dir = cfg.interim_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)

    activities = load_activities(cfg)
    activities.to_parquet(cfg.interim_dir / "activities.parquet", index=False)

    log_rows = []
    counts = dict(parsed=0, cached=0, missing_file=0, failed=0)
    # the raw table keeps duplicates for the audit; parse each activity once
    unique = activities.drop_duplicates("activity_id", keep="first")
    for act in unique.itertuples(index=False):
        entry = {"activity_id": act.activity_id, "filename": act.filename, "rows": 0, "error": None}
        if not act.is_run:
            entry["status"] = "skipped_non_run"
        elif pd.isna(act.filename):
            entry["status"] = "no_stream_file"
            counts["missing_file"] += 1
        else:
            source = cfg.export_dir / act.filename
            target = records_dir / f"{act.activity_id}.parquet"
            if not source.exists():
                entry["status"] = "file_not_found"
                counts["missing_file"] += 1
            elif not force and target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
                entry["status"] = "cached"
                entry["rows"] = pd.read_parquet(target, columns=["ts"]).shape[0]
                counts["cached"] += 1
            else:
                try:
                    records = parse_stream(source)
                    records = trim_endpoints(records, cfg.trim_start_end_m, cfg.keep_coordinates)
                    records.insert(0, "activity_id", act.activity_id)
                    records.to_parquet(target, index=False)
                    entry["status"] = "parsed"
                    entry["rows"] = len(records)
                    counts["parsed"] += 1
                except Exception as exc:  # keep going; the failure is logged and audited
                    log.warning("Failed to parse %s: %s", source.name, exc)
                    entry["status"] = "parse_error"
                    entry["error"] = f"{type(exc).__name__}: {exc}"[:500]
                    counts["failed"] += 1
        log_rows.append(entry)

    pd.DataFrame(log_rows).astype({"activity_id": "Int64"}).to_parquet(
        cfg.interim_dir / "ingest_log.parquet", index=False
    )
    return IngestSummary(
        activities=len(activities),
        runs=int(activities["is_run"].sum()),
        seconds=time.perf_counter() - t0,
        **counts,
    )


def records_glob(cfg: Config) -> Path:
    return cfg.interim_dir / "records" / "*.parquet"
