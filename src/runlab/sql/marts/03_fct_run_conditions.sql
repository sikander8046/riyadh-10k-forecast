-- Grain: one row per run. Weather at the hour nearest the run's midpoint.
--   feels_like_c  apparent temperature: combines heat, humidity and wind
--   dew_point_c   the best single measure of how humid air feels to a runner
CREATE OR REPLACE TABLE marts.fct_run_conditions AS
SELECT
    f.activity_id,
    f.local_date,
    l.location_from_gps,
    l.borrowed_days_away,
    w.temp_c,
    w.humidity_pct,
    w.dew_point_c,
    w.feels_like_c,
    w.wind_mps
FROM marts.fct_runs AS f
JOIN staging.stg_run_locations AS l USING (activity_id)
LEFT JOIN raw.weather_hourly AS w
    ON NOT f.is_treadmill  -- indoor runs get no outdoor weather
   AND w.lat_r = l.lat_r
   AND w.lon_r = l.lon_r
   AND w.hour_utc = date_trunc(
        'hour',
        l.start_utc + to_seconds(CAST(coalesce(f.moving_s, 0) / 2 AS BIGINT)) + INTERVAL 30 MINUTE
   );
