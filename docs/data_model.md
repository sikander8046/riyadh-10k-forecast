# Data model

```
Strava export ──► data/interim (Parquet, privacy-trimmed) ──► raw ──► staging ──► marts
```

## raw (loaded as-is from Parquet)

| Table | Grain | Notes |
|---|---|---|
| `raw.activities` | one row per activities.csv row | Duplicates kept so the audit can count them |
| `raw.records` | one row per stream sample | Only runs are parsed. GPS already trimmed at ingestion |
| `raw.ingest_log` | one row per activity | `parsed`, `cached`, `file_not_found`, `no_stream_file`, `parse_error`, `skipped_non_run` |

## staging

| Table | Grain | Key logic |
|---|---|---|
| `staging.params` | single row | Athlete and quality settings from config.yaml, joined into models instead of hard-coding |
| `staging.stg_activities` | activity (PK `activity_id`) | Exact dedup, device-duplicate detection (`is_device_duplicate`, `duplicate_of`, `has_gps`), local date via timezone periods, treadmill flag |
| `staging.stg_records` | activity × timestamp | `gap_s` (time each sample represents), invalid HR nulled (raw kept in `hr_raw`), cadence normalised to steps/min, `is_gap`, `is_speed_spike`, `is_moving` |

## marts

| Table | Grain | Columns worth knowing |
|---|---|---|
| `marts.fct_runs` | run (PK `activity_id`) | `pace_s_per_km`, time-weighted `avg_hr`, `hr_coverage`, `trimp`, `ef`, `decoupling_pct`, `has_stream` |
| `marts.fct_daily_load` | calendar day, rest days included | `runs`, `km`, `moving_min`, `trimp`, `runs_without_hr` |
| `marts.fct_fitness` | calendar day | `ctl` (fitness), `atl` (fatigue), `tsb` (form), `acwr` |
| `marts.dq_report` | quality check | `status`, `failed`, `total`, `rate`, `tolerance` |

## Metric definitions

**Moving time.** Sum of sample intervals where the gap to the previous sample is at most `pause_gap_s`
and speed is between 0.5 m/s and the spike threshold. Every stream metric is weighted by this time,
not by row count, so 1 s and "smart recording" devices give comparable numbers.

**Heart-rate reserve.** `HRr = (HR - HR_rest) / (HR_max - HR_rest)`.

**Banister TRIMP.** `Σ minutes × HRr × a × e^(b × HRr)`, with a = 0.64, b = 1.92 (male) or
a = 0.86, b = 1.67 (female). Runs without heart rate have NULL TRIMP, counted in
`runs_without_hr` so the resulting under-estimate of load is visible rather than hidden.

**Efficiency factor (EF).** Average moving speed in m/min divided by average HR. Rising EF at
similar effort means aerobic fitness is improving.

**Aerobic decoupling.** `(EF first half − EF second half) / EF first half`, halves split by moving
time. Above ~5% on a steady run suggests the aerobic base is the limiter. Meaningless for
intervals, so filter by session type before interpreting it.

**Fitness-fatigue.** `CTL_t = CTL_{t-1} + (TRIMP_t − CTL_{t-1}) / 42`, ATL likewise with 7 days,
`TSB_t = CTL_{t-1} − ATL_{t-1}`.

**ACWR.** 7-day mean load / 28-day mean load (rolling-average form; undefined for the first 27 days).

## Device duplicates

A phone app and a wrist band can both upload the same session, producing two
activities with different IDs. Activities whose starts fall within
`duplicate_window_s` (default 180 s) of the previous one are grouped into a
session. The copy with GPS is kept (GPS distance is measured; a band without GPS
estimates distance from steps), then the one with a stream file, then the lowest
ID. Flagged copies stay in `stg_activities` for the audit and are excluded from
`stg_records` and every mart.

## Known limitations

- Two genuinely separate activities started within the duplicate window (e.g. a
  warm-up saved separately) would be merged. Raise or lower `duplicate_window_s`
  after reviewing flagged pairs.

- Cadence normalisation assumes values below 120 are per-leg. Walking can be misclassified.
- Timezone is set by configured date ranges, not per activity location (GPS is trimmed before
  it could be used). Runs near midnight during travel may land on the wrong local date.
- GPS spikes inflate stream distance for GPX files that lack a device distance field; Strava's
  own distance from activities.csv is used for pace, and `distance_agreement` measures the gap.

## Classification rule

An activity's Strava type, not its name, decides whether it is a run. Names are free text and often left as Strava's automatic label. Checked case: three sessions in October 2022 named "Morning Walk" but typed Run had paces of 7:29 to 8:10 per km, consistent with walk/run sessions, so they are kept as runs.

## Sparse device speed values

Some files record GPS distance every second but only report a speed value every few seconds (observed in files named "Outdoor run" and Nike Run Club activities). The original rule filled in speed only when a file's entire speed column was empty, so these partially-empty files kept their sparse speed as-is, and every second with a missing value was wrongly classified as not moving. One diagnosed run (23 May 2025) had 24.9 minutes of continuous, gap-free GPS recording but only 3.7 minutes counted as moving. Fix: fill any individual missing speed value from the distance change since the previous reading, keeping the device's own speed wherever it exists. Confirmed against four previously-affected dates, all now showing realistic paces (4:45-6:51/km).
