-- Grain: one row per activity (deduplicated on activity_id).
--
-- Two kinds of duplicate are handled:
--   1. Exact: the same Activity ID appears twice in activities.csv. Keep one row.
--   2. Device: one session uploaded twice by two devices (e.g. phone app with GPS
--      and a Huawei band without GPS), with different IDs and start times a few
--      seconds to minutes apart. Consecutive activities starting within
--      duplicate_window_s are grouped into one session; the copy with GPS is kept,
--      then the one with a stream file, then the lowest ID. The others stay in
--      this table, flagged, so the audit can count them, and are excluded downstream.
CREATE OR REPLACE TABLE staging.stg_activities AS
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY activity_id ORDER BY start_utc) AS rn
    FROM raw.activities
    WHERE activity_id IS NOT NULL
),
gps AS (
    SELECT activity_id, coalesce(bool_or(had_gps), false) AS has_gps
    FROM raw.records
    GROUP BY activity_id
),
base AS (
    SELECT r.*, coalesce(g.has_gps, false) AS has_gps
    FROM ranked AS r
    LEFT JOIN gps AS g USING (activity_id)
    WHERE r.rn = 1
),
session_starts AS (
    SELECT
        *,
        CASE
            WHEN date_diff('second', lag(start_utc) OVER w, start_utc)
                 <= (SELECT duplicate_window_s FROM staging.params)
            THEN 0 ELSE 1
        END AS starts_new_session
    FROM base
    WINDOW w AS (ORDER BY start_utc, activity_id)
),
sessions AS (
    SELECT *, sum(starts_new_session) OVER (ORDER BY start_utc, activity_id) AS session_id
    FROM session_starts
),
picked AS (
    SELECT
        *,
        ROW_NUMBER() OVER keep_order  AS session_rank,
        first_value(activity_id) OVER keep_order AS session_keeper_id,
        count(*) OVER (PARTITION BY session_id) AS copies_in_session
    FROM sessions
    WINDOW keep_order AS (
        PARTITION BY session_id
        ORDER BY has_gps DESC, (filename IS NOT NULL) DESC, activity_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    )
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
    filename,
    has_gps,
    session_id,
    copies_in_session,
    session_rank > 1                                                AS is_device_duplicate,
    CASE WHEN session_rank > 1 THEN session_keeper_id END           AS duplicate_of
FROM picked;
