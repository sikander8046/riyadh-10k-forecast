"""End-to-end: synthetic export -> ingest -> warehouse -> quality audit."""

import duckdb
import pytest

from runlab.cli import main


@pytest.fixture(scope="module")
def sample_export(tmp_path_factory):
    pytest.importorskip("fit_tool")
    from make_sample_export import main as make

    out = tmp_path_factory.mktemp("export")
    make(str(out))
    return out


def test_full_pipeline(sample_export, make_config, tmp_path):
    config = make_config(sample_export)
    assert main(["--config", str(config), "all"]) == 0

    con = duckdb.connect(str(tmp_path / "wh.duckdb"), read_only=True)
    runs = con.execute("SELECT count(*), count(*) FILTER (WHERE has_stream) FROM marts.fct_runs").fetchone()
    assert runs == (64, 63)  # 65 run rows minus 1 duplicate; 1 run has no stream file

    ride = con.execute("SELECT count(*) FROM marts.fct_runs WHERE activity_type = 'Ride'").fetchone()
    assert ride == (0,)

    # GPS never appears within 500 m of the start or finish
    leaks = con.execute(
        """
        SELECT count(*) FROM staging.stg_records r
        JOIN (SELECT activity_id, max(distance_m) AS total FROM staging.stg_records GROUP BY 1) t
          USING (activity_id)
        WHERE r.lat IS NOT NULL AND (r.distance_m < 500 OR r.distance_m > t.total - 500)
        """
    ).fetchone()
    assert leaks == (0,)

    # planted problems are detected
    dq = dict(con.execute("SELECT check_name, failed FROM marts.dq_report").fetchall())
    assert dq["export_duplicate_rows"] == 1
    assert dq["device_duplicates"] == 1

    # the band copy is flagged and the GPS recording of that session is the one kept
    dup = con.execute(
        """
        SELECT d.name, d.has_gps, k.has_gps, k.activity_id IN (SELECT activity_id FROM marts.fct_runs)
        FROM staging.stg_activities d
        JOIN staging.stg_activities k ON k.activity_id = d.duplicate_of
        WHERE d.is_device_duplicate
        """
    ).fetchall()
    assert dup == [("Outdoor run", False, True, True)]
    assert dq["gps_speed_spikes"] > 0
    assert dq["hr_sample_validity"] > 0
    assert dq["long_pauses"] == 1

    # the simulated athlete gets fitter: efficiency rises over the block
    first, last = con.execute(
        """
        SELECT avg(ef) FILTER (WHERE local_date < DATE '2026-07-01'),
               avg(ef) FILTER (WHERE local_date >= DATE '2026-09-01')
        FROM marts.fct_runs
        """
    ).fetchone()
    assert last > first * 1.08


def test_incremental_ingest_uses_cache(sample_export, make_config, capsys):
    config = make_config(sample_export)
    main(["--config", str(config), "ingest"])
    main(["--config", str(config), "ingest"])
    second_run = capsys.readouterr().out.strip().splitlines()[-1]
    assert " 0 parsed" in second_run and " 0 cached" not in second_run
