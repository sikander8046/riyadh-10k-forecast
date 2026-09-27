import pandas as pd

from runlab.config import load_config
from runlab.ingest.activities import load_activities, parse_activity_dates


def test_parse_dates_handles_narrow_nbsp():
    s = pd.Series(["Mar 5, 2024, 6:12:03\u202fAM", "Dec 31, 2023, 11:59:59 PM"])
    out = parse_activity_dates(s)
    assert out.iloc[0] == pd.Timestamp("2024-03-05 06:12:03", tz="UTC")
    assert out.iloc[1].hour == 23


def test_duplicate_headers_prefer_metric_columns(tmp_path, make_config):
    csv = (
        "Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,"
        "Filename,Elapsed Time,Moving Time,Distance\n"
        '1,"Jun 1, 2026, 2:30:00 AM",Easy,Run,1800,"5.02",activities/1.gpx,1800,1750,5021.4\n'
        '2,"Jun 2, 2026, 2:30:00 AM",Old export,Run,1800,"6.00",,,,\n'
    )
    export = tmp_path / "export"
    export.mkdir()
    (export / "activities.csv").write_text(csv)
    cfg = load_config(make_config(export))
    df = load_activities(cfg)
    assert df.loc[0, "distance_m"] == 5021.4
    assert df.loc[0, "moving_s"] == 1750
    assert df.loc[0, "start_local"] == pd.Timestamp("2026-06-01 05:30:00")  # Asia/Riyadh
    assert df["is_run"].all()
    assert pd.isna(df.loc[1, "filename"])
