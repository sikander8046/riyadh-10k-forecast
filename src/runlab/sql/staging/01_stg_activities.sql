-- Grain: one row per activity (deduplicated on activity_id).
CREATE OR REPLACE TABLE staging.stg_activities AS
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY activity_id ORDER BY start_utc) AS rn
    FROM raw.activities
    WHERE activity_id IS NOT NULL
)
SELECT
    activity_id,
    start_utc,
    start_local,
    CAST(start_local AS DATE)                                       AS local_date,
    timezone,
    name,
    activity_type,
    is_run,
    activity_type = 'Virtual Run'
        OR lower(coalesce(name, '')) LIKE '%treadmill%'              AS is_treadmill,
    distance_m,
    moving_s,
    elapsed_s,
    elev_gain_m,
    avg_hr,
    max_hr,
    gear,
    filename
FROM ranked
WHERE rn = 1;
