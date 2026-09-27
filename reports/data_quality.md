# Data quality report

_Generated 2026-09-27 18:23 by `runlab quality`._

| Status | Check | Failed / total | Rate | Tolerance | What it means |
|---|---|---|---|---|---|
| PASS | `device_duplicates` | 74 / 290 | 25.52% | 100.0% | Sessions uploaded twice by two devices; the GPS copy is kept, the other excluded |
| PASS | `export_duplicate_rows` | 0 / 290 | 0.00% | 0.0% | activities.csv has no repeated Activity IDs (staging keeps the first) |
| PASS | `activity_id_unique` | 0 / 290 | 0.00% | 0.0% | Activity IDs are unique after staging |
| PASS | `activity_date_parsed` | 0 / 290 | 0.00% | 0.0% | Every activity date parsed to a timestamp |
| PASS | `no_future_activities` | 0 / 290 | 0.00% | 0.0% | No activity is dated in the future |
| PASS | `no_negative_values` | 0 / 123 | 0.00% | 0.0% | Distance and moving time are never negative |
| PASS | `run_stream_available` | 0 / 186 | 0.00% | 5.0% | Runs have a parseable GPS/HR stream file |
| PASS | `stream_parse_errors` | 0 / 186 | 0.00% | 0.0% | Stream files parse without errors |
| PASS | `hr_coverage` | 0 / 101 | 0.00% | 10.0% | Runs recorded with a heart-rate sensor have HR for at least 80% of moving time |
| PASS | `runs_without_hr_sensor` | 22 / 123 | 17.89% | 100.0% | Runs recorded with no heart-rate sensor at all (no TRIMP; handled in the load chapter) |
| PASS | `hr_sample_validity` | 0 / 115,185 | 0.00% | 1.0% | Heart-rate samples fall inside the physiologically valid range |
| PASS | `gps_speed_spikes` | 25 / 151,339 | 0.02% | 0.5% | GPS speed samples are below the spike threshold |
| PASS | `distance_agreement` | 2 / 123 | 1.63% | 10.0% | Stream distance is within 5% of Strava's recorded distance |
| PASS | `long_pauses` | 1 / 123 | 0.81% | 100.0% | Runs containing a recording gap longer than 5 minutes (watch paused or stopped) |
| PASS | `treadmill_runs` | 0 / 123 | 0.00% | 100.0% | Treadmill / virtual runs (pace comes from the device, not GPS) |
