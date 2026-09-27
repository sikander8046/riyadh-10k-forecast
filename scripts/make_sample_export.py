"""Generate a synthetic Strava bulk export for demos, tests and CI.

The fake athlete trains ~4x/week for 16 weeks and gets fitter (efficiency
rises), with deliberately planted data problems so the quality audit has
something to find:

  - one run with GPS spikes, one with a dropping-out HR strap
  - one run with a 6-minute pause, one treadmill run with no GPS
  - one run whose stream file is missing, one duplicated CSV row
  - a bike ride (non-run, must be ignored)
  - GPX, FIT and TCX files, gzipped and plain, and the real CSV's
    duplicated column headers

Usage: python scripts/make_sample_export.py data/raw/sample_export
Requires the dev extra (fit-tool) for FIT output.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import math
import sys
from pathlib import Path

import numpy as np

CENTER = (24.6900, 46.7200)  # an arbitrary point in Riyadh, not anyone's home
LOOP_RADIUS_M = 700.0
M_PER_DEG_LAT = 111_320.0

HEADER = [
    "Activity ID",
    "Activity Date",
    "Activity Name",
    "Activity Type",
    "Activity Description",
    "Elapsed Time",
    "Distance",
    "Max Heart Rate",
    "Relative Effort",
    "Commute",
    "Activity Private Note",
    "Activity Gear",
    "Filename",
    "Athlete Weight",
    "Bike Weight",
    "Elapsed Time",
    "Moving Time",
    "Distance",
    "Max Speed",
    "Average Speed",
    "Elevation Gain",
    "Elevation Loss",
    "Elevation Low",
    "Elevation High",
    "Max Grade",
    "Average Grade",
    "Average Positive Grade",
    "Average Negative Grade",
    "Max Cadence",
    "Average Cadence",
    "Max Heart Rate",
    "Average Heart Rate",
    "Max Watts",
    "Average Watts",
    "Calories",
]


def position(distance_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    theta = distance_m / LOOP_RADIUS_M
    lat = CENTER[0] + (LOOP_RADIUS_M * np.sin(theta)) / M_PER_DEG_LAT
    lon = CENTER[1] + (LOOP_RADIUS_M * (1 - np.cos(theta))) / (
        M_PER_DEG_LAT * math.cos(math.radians(CENTER[0]))
    )
    return lat, lon


def simulate_run(rng, start_utc, week, kind, duration_s):
    """1 Hz samples: HR target by session type, speed = efficiency * HR."""
    ef = 1.05 + 0.15 * (week / 15) + rng.normal(0, 0.015)  # m/min per bpm
    target_hr = {"easy": 145, "tempo": 170, "long": 148, "intervals": 160}[kind]
    t = np.arange(duration_s)
    warmup = np.clip(t / 300, 0, 1)
    drift = 0.004 * t / 60 * target_hr / 145  # cardiac drift, bpm per minute scale
    hr = 95 + (target_hr - 95) * warmup + drift + rng.normal(0, 1.5, duration_s)
    if kind == "intervals":
        hr += 12 * (np.sin(2 * np.pi * t / 360) > 0.3) * warmup
    speed = np.clip(ef * (hr - drift * 1.8) / 60 + rng.normal(0, 0.08, duration_s), 0.8, 6.0)
    distance = np.cumsum(speed)
    lat, lon = position(distance)
    return {
        "ts": [start_utc + dt.timedelta(seconds=int(s)) for s in t],
        "lat": lat,
        "lon": lon,
        "alt": 610 + 4 * np.sin(distance / 350),
        "hr": np.round(hr),
        "cad": np.round(84 + rng.normal(0, 1.5, duration_s)),
        "distance": distance,
        "speed": speed,
    }


def write_gpx(path: Path, s: dict, gz: bool) -> None:
    pts = []
    for i in range(len(s["ts"])):
        pts.append(
            f'<trkpt lat="{s["lat"][i]:.7f}" lon="{s["lon"][i]:.7f}"><ele>{s["alt"][i]:.1f}</ele>'
            f"<time>{s['ts'][i]:%Y-%m-%dT%H:%M:%SZ}</time><extensions><gpxtpx:TrackPointExtension>"
            f"<gpxtpx:hr>{int(s['hr'][i])}</gpxtpx:hr><gpxtpx:cad>{int(s['cad'][i])}</gpxtpx:cad>"
            f"</gpxtpx:TrackPointExtension></extensions></trkpt>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="sample" xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
        "<trk><type>running</type><trkseg>" + "".join(pts) + "</trkseg></trk></gpx>"
    ).encode()
    path.write_bytes(gzip.compress(xml) if gz else xml)


def write_tcx(path: Path, s: dict) -> None:
    tps = []
    for i in range(len(s["ts"])):
        tps.append(
            f"<Trackpoint><Time>{s['ts'][i]:%Y-%m-%dT%H:%M:%SZ}</Time><Position>"
            f"<LatitudeDegrees>{s['lat'][i]:.7f}</LatitudeDegrees>"
            f"<LongitudeDegrees>{s['lon'][i]:.7f}</LongitudeDegrees></Position>"
            f"<AltitudeMeters>{s['alt'][i]:.1f}</AltitudeMeters>"
            f"<DistanceMeters>{s['distance'][i]:.1f}</DistanceMeters>"
            f"<HeartRateBpm><Value>{int(s['hr'][i])}</Value></HeartRateBpm></Trackpoint>"
        )
    xml = (
        '  <?xml version="1.0" encoding="UTF-8"?>\n'  # leading spaces: a real device quirk
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
        '<Activities><Activity Sport="Running"><Lap><Track>'
        + "".join(tps)
        + "</Track></Lap></Activity></Activities></TrainingCenterDatabase>"
    )
    path.write_bytes(gzip.compress(xml.encode()))


def write_fit(path: Path, s: dict, with_gps: bool = True) -> None:
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.record_message import RecordMessage
    from fit_tool.profile.profile_type import FileType, Manufacturer

    builder = FitFileBuilder(auto_define=True, min_string_size=50)
    fid = FileIdMessage()
    fid.type = FileType.ACTIVITY
    fid.manufacturer = Manufacturer.DEVELOPMENT.value
    fid.product = 0
    fid.serial_number = 12345
    fid.time_created = int(s["ts"][0].timestamp() * 1000)
    builder.add(fid)
    records = []
    for i in range(len(s["ts"])):
        r = RecordMessage()
        r.timestamp = int(s["ts"][i].timestamp() * 1000)
        if with_gps:
            r.position_lat = float(s["lat"][i])
            r.position_long = float(s["lon"][i])
        r.distance = float(s["distance"][i])
        r.enhanced_speed = float(s["speed"][i])
        r.enhanced_altitude = float(s["alt"][i])
        r.heart_rate = int(s["hr"][i])
        r.cadence = int(s["cad"][i])
        records.append(r)
    builder.add_all(records)
    tmp = path.with_suffix("")  # write .fit then gzip to .fit.gz
    builder.build().to_file(str(tmp))
    path.write_bytes(gzip.compress(tmp.read_bytes()))
    tmp.unlink()


def csv_row(aid, start, name, typ, filename, s=None, distance_m=None, moving_s=None):
    if s is not None:
        distance_m = float(s["distance"][-1])
        moving_s = len(s["ts"])
        avg_hr, max_hr = float(np.mean(s["hr"])), float(np.max(s["hr"]))
    else:
        avg_hr = max_hr = ""
    row = {h: "" for h in range(len(HEADER))}
    values = {
        0: aid,
        1: start.strftime("%b %d, %Y, %I:%M:%S %p").replace(" 0", " ", 1),
        2: name,
        3: typ,
        5: moving_s,
        6: f"{distance_m / 1000:.2f}",
        7: max_hr,
        9: "false",
        12: filename,
        15: moving_s,
        16: moving_s,
        17: f"{distance_m:.1f}",
        20: 18.0,
        29: 84,
        30: max_hr,
        31: avg_hr,
        34: 450,
    }
    row.update(values)
    return [row[i] for i in range(len(HEADER))]


def main(out_dir: str) -> None:
    rng = np.random.default_rng(42)
    out = Path(out_dir)
    (out / "activities").mkdir(parents=True, exist_ok=True)
    rows = []
    plan = [("easy", 35), ("tempo", 40), ("easy", 30), ("long", 55)]
    first_day = dt.date(2026, 6, 1)
    aid = 10_000_000_000
    n = 0
    for week in range(16):
        for slot, (kind, minutes) in enumerate(plan):
            if week % 3 == 2 and kind == "tempo":
                kind = "intervals"
            day = first_day + dt.timedelta(days=week * 7 + [0, 2, 4, 5][slot])
            start = dt.datetime.combine(day, dt.time(2, 30)) + dt.timedelta(minutes=int(rng.integers(0, 40)))
            aid += int(rng.integers(1_000, 9_000))
            n += 1
            s = simulate_run(rng, start, week, kind, minutes * 60 + int(rng.integers(-120, 120)))
            name = f"Morning {kind.title()} Run"
            typ = "Run"

            # planted data problems
            if n == 7:  # GPS spikes
                idx = rng.choice(len(s["ts"]), 12, replace=False)
                s["lat"][idx] += 0.01
                name += " (bad GPS)"
            if n == 11:  # failing HR strap
                s["hr"][600:900] = 0
                s["hr"][900:960] = 245
            if n == 15:  # 6-minute pause at a traffic light
                cut = len(s["ts"]) // 2
                s["ts"] = s["ts"][:cut] + [t + dt.timedelta(minutes=6) for t in s["ts"][cut:]]

            if n == 20:  # stream file missing from export
                filename = f"activities/{aid}.gpx"
                rows.append(csv_row(aid, start, name, typ, filename, s))
                continue
            if n == 24:  # treadmill: FIT with no GPS
                filename = f"activities/{aid}.fit.gz"
                write_fit(out / filename, s, with_gps=False)
                rows.append(csv_row(aid, start, "Treadmill Easy Run", "Virtual Run", filename, s))
                continue

            if n % 5 == 0:
                filename = f"activities/{aid}.fit.gz"
                write_fit(out / filename, s)
            elif n == 9:
                filename = f"activities/{aid}.tcx.gz"
                write_tcx(out / filename, s)
            else:
                gz = n % 2 == 0
                filename = f"activities/{aid}.gpx" + (".gz" if gz else "")
                write_gpx(out / filename, s, gz)
            rows.append(csv_row(aid, start, name, typ, filename, s))

    # a bike ride that must be ignored, and a duplicated export row
    ride_start = dt.datetime(2026, 7, 11, 3, 0)
    rows.append(csv_row(aid + 1, ride_start, "Weekend Ride", "Ride", "", distance_m=40_000, moving_s=5_400))
    rows.append(rows[3])

    with open(out / "activities.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"Wrote {len(rows)} activity rows to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/sample_export")
