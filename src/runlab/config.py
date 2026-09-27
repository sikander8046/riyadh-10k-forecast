"""Load and validate config.yaml."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


@dataclass(frozen=True)
class TzPeriod:
    start: dt.date
    tz: str


@dataclass(frozen=True)
class Config:
    root: Path
    hr_max: int
    hr_rest: int
    trimp_sex: str
    timezones: list[TzPeriod]
    trim_start_end_m: float
    keep_coordinates: bool
    export_dir: Path
    interim_dir: Path
    warehouse: Path
    max_run_speed_mps: float = 8.0
    hr_min_valid: int = 35
    hr_max_margin: int = 10
    pause_gap_s: int = 10
    extra: dict = field(default_factory=dict)

    @property
    def trimp_coefficients(self) -> tuple[float, float]:
        return (0.64, 1.92) if self.trimp_sex == "male" else (0.86, 1.67)

    def tz_for(self, when_utc: dt.datetime) -> str:
        """Timezone name in force on the (UTC) date of an activity."""
        day = when_utc.date()
        chosen = self.timezones[0].tz
        for period in self.timezones:
            if period.start <= day:
                chosen = period.tz
        return chosen


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path).resolve()
    raw = yaml.safe_load(path.read_text())
    root = path.parent

    athlete = raw["athlete"]
    if athlete["hr_max"] <= athlete["hr_rest"]:
        raise ValueError("athlete.hr_max must be greater than athlete.hr_rest")
    if athlete.get("trimp_sex", "male") not in {"male", "female"}:
        raise ValueError("athlete.trimp_sex must be 'male' or 'female'")

    periods = sorted(
        (TzPeriod(start=_as_date(p["from"]), tz=p["tz"]) for p in raw["timezones"]),
        key=lambda p: p.start,
    )
    for p in periods:
        ZoneInfo(p.tz)  # raises if the name is invalid

    paths = raw["paths"]
    quality = raw.get("quality", {})
    privacy = raw.get("privacy", {})
    return Config(
        root=root,
        hr_max=int(athlete["hr_max"]),
        hr_rest=int(athlete["hr_rest"]),
        trimp_sex=athlete.get("trimp_sex", "male"),
        timezones=periods,
        trim_start_end_m=float(privacy.get("trim_start_end_m", 500)),
        keep_coordinates=bool(privacy.get("keep_coordinates", True)),
        export_dir=(root / paths["export_dir"]).resolve(),
        interim_dir=(root / paths["interim_dir"]).resolve(),
        warehouse=(root / paths["warehouse"]).resolve(),
        max_run_speed_mps=float(quality.get("max_run_speed_mps", 8.0)),
        hr_min_valid=int(quality.get("hr_min_valid", 35)),
        hr_max_margin=int(quality.get("hr_max_margin", 10)),
        pause_gap_s=int(quality.get("pause_gap_s", 10)),
    )


def _as_date(value) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))
