-- Grain: one row per run. Stream metrics are time-weighted over moving samples.
--   trimp          Banister TRIMP: sum(minutes * HRr * a * e^(b * HRr))
--   ef_*           efficiency factor: speed (m/min) / heart rate
--   decoupling_pct aerobic decoupling, first half EF vs second half EF (+ = HR drifted up)
CREATE OR REPLACE TABLE marts.fct_runs AS
WITH rec AS (
    SELECT
        r.*,
        CASE WHEN r.is_moving THEN r.gap_s ELSE 0 END           AS moving_dt,
        (r.hr - p.hr_rest) / (p.hr_max - p.hr_rest)            AS hrr,
        p.trimp_a,
        p.trimp_b
    FROM staging.stg_records AS r
    CROSS JOIN staging.params AS p
),
halves AS (
    SELECT
        *,
        sum(moving_dt) OVER (PARTITION BY activity_id ORDER BY ts)  AS cum_moving_s,
        sum(moving_dt) OVER (PARTITION BY activity_id)              AS total_moving_s
    FROM rec
),
flagged AS (
    SELECT *, cum_moving_s <= total_moving_s / 2 AS first_half FROM halves
),
per_run AS (
    SELECT
        activity_id,
        count(*)                                                              AS n_records,
        sum(moving_dt)                                                        AS moving_s_stream,
        max(distance_m) - min(distance_m)                                     AS distance_m_stream,
        sum(moving_dt * hr) / nullif(sum(moving_dt) FILTER (WHERE hr IS NOT NULL), 0)
                                                                              AS avg_hr_stream,
        sum(moving_dt) FILTER (WHERE hr IS NOT NULL) / nullif(sum(moving_dt), 0)
                                                                              AS hr_coverage,
        sum(moving_dt / 60.0 * hrr * trimp_a * exp(trimp_b * hrr))
            FILTER (WHERE hr IS NOT NULL AND hrr > 0)                         AS trimp,
        sum(moving_dt * speed_mps) FILTER (WHERE first_half AND hr IS NOT NULL) * 60
            / nullif(sum(moving_dt * hr) FILTER (WHERE first_half AND hr IS NOT NULL), 0)
                                                                              AS ef_first_half,
        sum(moving_dt * speed_mps) FILTER (WHERE NOT first_half AND hr IS NOT NULL) * 60
            / nullif(sum(moving_dt * hr) FILTER (WHERE NOT first_half AND hr IS NOT NULL), 0)
                                                                              AS ef_second_half,
        sum(moving_dt * speed_mps) FILTER (WHERE hr IS NOT NULL) * 60
            / nullif(sum(moving_dt * hr) FILTER (WHERE hr IS NOT NULL), 0)    AS ef,
        count(*) FILTER (WHERE is_speed_spike)                                AS n_speed_spikes,
        count(*) FILTER (WHERE hr_raw IS NOT NULL AND hr IS NULL)             AS n_hr_invalid
    FROM flagged
    GROUP BY activity_id
)
SELECT
    a.activity_id,
    a.local_date,
    a.start_local,
    a.name,
    a.activity_type,
    a.is_treadmill,
    a.has_gps,
    coalesce(a.distance_m, s.distance_m_stream)                               AS distance_m,
    coalesce(s.moving_s_stream, a.moving_s)                                   AS moving_s,
    coalesce(s.moving_s_stream, a.moving_s)
        / nullif(coalesce(a.distance_m, s.distance_m_stream) / 1000, 0)       AS pace_s_per_km,
    a.elev_gain_m,
    coalesce(s.avg_hr_stream, a.avg_hr)                                       AS avg_hr,
    s.hr_coverage,
    s.trimp,
    s.ef,
    s.ef_first_half,
    s.ef_second_half,
    100 * (s.ef_first_half - s.ef_second_half) / nullif(s.ef_first_half, 0)   AS decoupling_pct,
    s.n_records,
    s.n_speed_spikes,
    s.n_hr_invalid,
    s.activity_id IS NOT NULL                                                 AS has_stream
FROM staging.stg_activities AS a
LEFT JOIN per_run AS s USING (activity_id)
WHERE a.is_run
  AND NOT a.is_device_duplicate;
