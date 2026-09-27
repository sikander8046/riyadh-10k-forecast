import gzip

import pytest

from runlab.ingest.streams import UnsupportedFormat, detect_format, parse_stream

GPX = """<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1"><trk><trkseg>
<trkpt lat="24.69" lon="46.72"><time>2026-06-01T02:30:00Z</time>
  <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>140</gpxtpx:hr><gpxtpx:cad>84</gpxtpx:cad></gpxtpx:TrackPointExtension></extensions></trkpt>
<trkpt lat="24.69" lon="46.72"><time>2026-06-01T02:30:00Z</time></trkpt>
<trkpt lat="24.69003" lon="46.72"><time>2026-06-01T02:30:01Z</time>
  <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>141</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>
</trkseg></trk></gpx>"""


def test_gpx_reads_hr_and_derives_distance_and_speed(tmp_path):
    path = tmp_path / "a.gpx.gz"
    path.write_bytes(gzip.compress(GPX.encode()))
    df = parse_stream(path)
    assert len(df) == 2, "duplicate timestamps are dropped"
    assert df["hr"].tolist() == [140.0, 141.0]
    assert df["cadence"].iloc[0] == 84
    assert df["distance_m"].iloc[-1] == pytest.approx(3.34, abs=0.05)  # 0.00003 deg lat
    assert df["speed_mps"].iloc[-1] == pytest.approx(3.34, abs=0.05)


def test_tcx_with_leading_whitespace(tmp_path):
    tcx = """   <?xml version="1.0"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
<Activities><Activity><Lap><Track>
<Trackpoint><Time>2026-06-01T02:30:00Z</Time><DistanceMeters>0</DistanceMeters>
  <HeartRateBpm><Value>130</Value></HeartRateBpm></Trackpoint>
<Trackpoint><Time>2026-06-01T02:30:02Z</Time><DistanceMeters>6</DistanceMeters>
  <HeartRateBpm><Value>132</Value></HeartRateBpm></Trackpoint>
</Track></Lap></Activity></Activities></TrainingCenterDatabase>"""
    path = tmp_path / "a.tcx"
    path.write_text(tcx)
    df = parse_stream(path)
    assert df["hr"].tolist() == [130.0, 132.0]
    assert df["speed_mps"].iloc[-1] == pytest.approx(3.0)


def test_fit_roundtrip(tmp_path):
    pytest.importorskip("fit_tool")
    import datetime as dt

    import numpy as np
    from make_sample_export import simulate_run, write_fit

    s = simulate_run(np.random.default_rng(0), dt.datetime(2026, 6, 1, 2, 30), 0, "easy", 120)
    path = tmp_path / "a.fit.gz"
    write_fit(path, s)
    df = parse_stream(path)
    assert len(df) == 120
    assert df["lat"].between(24.6, 24.8).all(), "semicircles converted to degrees"
    assert df["hr"].notna().all()


def test_unsupported_format(tmp_path):
    with pytest.raises(UnsupportedFormat):
        detect_format(tmp_path / "a.kml")
