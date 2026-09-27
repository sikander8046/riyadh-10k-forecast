-- Grain: one row per activity per recorded timestamp (typically 1 s).
-- Adds the time interval each sample represents, validity flags, and a
-- moving flag used to weight every stream metric by time rather than by row.
-- Streams of device duplicates are excluded (see stg_activities).
CREATE OR REPLACE TABLE staging.stg_records AS
WITH base AS (
    SELECT
        r.*,
        date_diff('millisecond', lag(r.ts) OVER w, r.ts) / 1000.0 AS gap_s
    FROM raw.records AS r
    WHERE r.activity_id IN (
        SELECT activity_id FROM staging.stg_activities WHERE NOT is_device_duplicate
    )
    WINDOW w AS (PARTITION BY r.activity_id ORDER BY r.ts)
)
SELECT
    b.activity_id,
    b.ts,
    date_diff('second', min(b.ts) OVER (PARTITION BY b.activity_id), b.ts)  AS elapsed_s,
    b.lat,
    b.lon,
    b.altitude_m,
    b.distance_m,
    b.speed_mps,
    b.hr                                                                     AS hr_raw,
    CASE
        WHEN b.hr BETWEEN p.hr_min_valid AND p.hr_max + p.hr_max_margin THEN b.hr
    END                                                                      AS hr,
    -- running cadence is often recorded per leg (~85); normalise to steps/min
    CASE WHEN b.cadence > 0 AND b.cadence < 120 THEN b.cadence * 2 ELSE b.cadence END
                                                                             AS cadence_spm,
    coalesce(b.gap_s, 0)                                                     AS gap_s,
    coalesce(b.gap_s, 0) > p.pause_gap_s                                     AS is_gap,
    coalesce(b.speed_mps, 0) > p.max_run_speed_mps                           AS is_speed_spike,
    coalesce(b.gap_s, 0) BETWEEN 0 AND p.pause_gap_s
        AND b.speed_mps BETWEEN 0.5 AND p.max_run_speed_mps                  AS is_moving
FROM base AS b
CROSS JOIN staging.params AS p;
