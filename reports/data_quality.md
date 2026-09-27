# Data quality report

_Generated 2026-09-27 17:39 by `runlab quality`._

| Status | Check | Failed / total | Rate | Tolerance | What it means |
|---|---|---|---|---|---|
| WARN | `export_duplicate_rows` | 1 / 66 | 1.52% | 0.0% | activities.csv has no repeated Activity IDs (staging keeps the first) |
| PASS | `activity_id_unique` | 0 / 65 | 0.00% | 0.0% | Activity IDs are unique after staging |
| PASS | `activity_date_parsed` | 0 / 66 | 0.00% | 0.0% | Every activity date parsed to a timestamp |
| PASS | `no_future_activities` | 0 / 66 | 0.00% | 0.0% | No activity is dated in the future |
| PASS | `no_negative_values` | 0 / 64 | 0.00% | 0.0% | Distance and moving time are never negative |
| PASS | `run_stream_available` | 1 / 64 | 1.56% | 5.0% | Runs have a parseable GPS/HR stream file |
| PASS | `stream_parse_errors` | 0 / 64 | 0.00% | 0.0% | Stream files parse without errors |
| PASS | `hr_coverage` | 1 / 63 | 1.59% | 10.0% | Runs with a stream have heart rate for at least 80% of moving time |
| PASS | `hr_sample_validity` | 360 / 151,270 | 0.24% | 1.0% | Heart-rate samples fall inside the physiologically valid range |
| PASS | `gps_speed_spikes` | 24 / 151,270 | 0.02% | 0.5% | GPS speed samples are below the spike threshold |
| PASS | `distance_agreement` | 1 / 62 | 1.61% | 10.0% | Stream distance is within 5% of Strava's recorded distance |
| PASS | `long_pauses` | 1 / 63 | 1.59% | 100.0% | Runs containing a recording gap longer than 5 minutes (watch paused or stopped) |
| PASS | `treadmill_runs` | 1 / 64 | 1.56% | 100.0% | Treadmill / virtual runs (pace comes from the device, not GPS) |
