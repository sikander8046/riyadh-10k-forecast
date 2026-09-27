-- Grain: one row per calendar day from first to last run (rest days included,
-- which the fitness-fatigue model needs).
CREATE OR REPLACE TABLE marts.fct_daily_load AS
WITH bounds AS (
    SELECT min(local_date) AS first_day, max(local_date) AS last_day FROM marts.fct_runs
),
spine AS (
    SELECT CAST(d AS DATE) AS day
    FROM bounds, unnest(generate_series(first_day, last_day, INTERVAL 1 DAY)) AS t(d)
    WHERE first_day IS NOT NULL
)
SELECT
    s.day,
    count(r.activity_id)                          AS runs,
    coalesce(sum(r.distance_m), 0) / 1000.0       AS km,
    coalesce(sum(r.moving_s), 0) / 60.0           AS moving_min,
    coalesce(sum(r.trimp), 0)                     AS trimp,
    count(r.activity_id) FILTER (WHERE r.trimp IS NULL) AS runs_without_hr
FROM spine AS s
LEFT JOIN marts.fct_runs AS r ON r.local_date = s.day
GROUP BY s.day
ORDER BY s.day;
