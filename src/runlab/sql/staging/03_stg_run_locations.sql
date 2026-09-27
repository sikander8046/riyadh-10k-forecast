-- Grain: one row per kept run. Where each run happened, for the weather join.
-- Location = the run's average GPS position rounded to 0.1 degree (about 11 km):
-- precise enough for weather, never precise enough to reveal a route or home.
-- Runs without GPS borrow the location of the nearest GPS run in time.
CREATE OR REPLACE TABLE staging.stg_run_locations AS
WITH runs AS (
    SELECT activity_id, start_utc
    FROM staging.stg_activities
    WHERE is_run AND NOT is_device_duplicate
),
gps_runs AS (
    SELECT
        r.activity_id,
        a.start_utc,
        round(avg(r.lat), 1) AS lat_r,
        round(avg(r.lon), 1) AS lon_r
    FROM staging.stg_records AS r
    JOIN staging.stg_activities AS a USING (activity_id)
    WHERE r.lat IS NOT NULL
    GROUP BY r.activity_id, a.start_utc
),
prev AS (  -- nearest GPS run at or before this run
    SELECT r.activity_id, g.lat_r, g.lon_r,
           date_diff('second', g.start_utc, r.start_utc) AS gap_s
    FROM runs AS r
    ASOF LEFT JOIN gps_runs AS g ON r.start_utc >= g.start_utc
),
nxt AS (   -- nearest GPS run at or after this run
    SELECT r.activity_id, g.lat_r, g.lon_r,
           date_diff('second', r.start_utc, g.start_utc) AS gap_s
    FROM runs AS r
    ASOF LEFT JOIN gps_runs AS g ON r.start_utc <= g.start_utc
)
SELECT
    r.activity_id,
    r.start_utc,
    CASE WHEN p.gap_s IS NULL OR n.gap_s < p.gap_s THEN n.lat_r ELSE p.lat_r END AS lat_r,
    CASE WHEN p.gap_s IS NULL OR n.gap_s < p.gap_s THEN n.lon_r ELSE p.lon_r END AS lon_r,
    own.activity_id IS NOT NULL                                               AS location_from_gps,
    CASE WHEN own.activity_id IS NULL
         THEN round(least(coalesce(p.gap_s, n.gap_s), coalesce(n.gap_s, p.gap_s)) / 86400.0, 1)
    END                                                                       AS borrowed_days_away
FROM runs AS r
LEFT JOIN gps_runs AS own USING (activity_id)
LEFT JOIN prev AS p USING (activity_id)
LEFT JOIN nxt AS n USING (activity_id);
