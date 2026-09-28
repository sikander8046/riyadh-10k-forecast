-- Grain: one row per walk or hike (duplicate uploads collapsed).
--
-- Walking builds aerobic fitness, so it belongs in the training-load story.
-- Load is estimated from each activity's average heart rate and moving time
-- (average-HR TRIMP), not from second-by-second streams: walks are steady,
-- low-intensity efforts where the average is close to the stream-based value,
-- and it avoids parsing files the rest of the pipeline does not need.
--
-- Duplicates: a phone app and a wrist band can both upload the same walk. Copies
-- that start within duplicate_window_s share a session_id (see stg_activities).
-- Within a session, keep the copy WITH heart rate, then the longest, then the
-- lowest ID -- heart rate is what the load calculation needs.
CREATE OR REPLACE TABLE marts.fct_walks AS
WITH walks AS (
    SELECT a.*, p.hr_rest, p.hr_max, p.trimp_a, p.trimp_b
    FROM staging.stg_activities AS a
    CROSS JOIN staging.params AS p
    WHERE a.activity_type IN ('Walk', 'Hike')
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY session_id
            ORDER BY (avg_hr IS NOT NULL) DESC, moving_s DESC NULLS LAST, activity_id
        ) AS rn
    FROM walks
)
SELECT
    activity_id,
    local_date,
    activity_type,
    moving_s,
    distance_m,
    avg_hr,
    CASE
        WHEN avg_hr > hr_rest AND moving_s > 0 THEN
            (moving_s / 60.0) * ((avg_hr - hr_rest) / (hr_max - hr_rest))
            * trimp_a * exp(trimp_b * ((avg_hr - hr_rest) / (hr_max - hr_rest)))
    END AS trimp_est
FROM ranked
WHERE rn = 1;
