#!/usr/bin/env python3
"""
sat_tracker.py - Satellite position, ground track, and pass predictor.

Pulls a satellite's orbital elements (OMM/JSON format) from CelesTrak,
propagates them with SGP4 (via Skyfield), and reports:
  position  - where the satellite is right now
  track     - ground track plot for the next N minutes
  passes    - when it will be visible from a given location
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
from skyfield.api import EarthSatellite, load, wgs84

CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"
CACHE_DIR = Path(".cache")
CACHE_MAX_AGE_SECONDS = 2 * 60 * 60   # be polite: reuse downloaded data for 2 hours
STALE_WARNING_HOURS = 72              # SGP4 accuracy degrades as element sets age


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def fetch_omm(catnr: int) -> dict:
    """Download (or load from cache) the latest orbital elements for one object.

    FORMAT=JSON is set explicitly. Do not use the legacy TLE format: objects
    with catalog numbers above 99999 are not available as TLEs.
    """
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"{catnr}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_MAX_AGE_SECONDS:
        return json.loads(cache_file.read_text())[0]

    resp = requests.get(
        CELESTRAK_GP_URL,
        params={"CATNR": catnr, "FORMAT": "JSON"},
        timeout=30,
    )
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        sys.exit(f"CelesTrak returned no usable data for catalog number {catnr}: {resp.text[:100]}")
    if not data:
        sys.exit(f"No data found for catalog number {catnr}.")
    cache_file.write_text(json.dumps(data))
    return data[0]


def load_omm(args: argparse.Namespace) -> dict:
    if args.omm_file:
        data = json.loads(Path(args.omm_file).read_text())
        return data[0] if isinstance(data, list) else data
    return fetch_omm(args.catnr)


def describe(sat: EarthSatellite, omm: dict) -> None:
    epoch = sat.epoch.utc_datetime()
    age_h = (datetime.now(timezone.utc) - epoch).total_seconds() / 3600
    print(f"Object : {omm.get('OBJECT_NAME', 'unknown')} (catalog #{omm.get('NORAD_CAT_ID')})")
    print(f"Epoch  : {epoch:%Y-%m-%d %H:%M:%S} UTC  (element set age: {age_h:.1f} h)")
    if age_h > STALE_WARNING_HOURS:
        print(f"WARNING: element set is older than {STALE_WARNING_HOURS} h; predictions may be off by many km.")
    print()


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_position(sat: EarthSatellite, ts) -> None:
    sub = wgs84.subpoint(sat.at(ts.now()))
    print(f"Latitude  : {sub.latitude.degrees:8.3f} deg")
    print(f"Longitude : {sub.longitude.degrees:8.3f} deg")
    print(f"Altitude  : {sub.elevation.km:8.1f} km")


def _break_at_antimeridian(lons: np.ndarray, lats: np.ndarray):
    """Insert NaNs where the track wraps from +180 to -180 so the plot has no horizontal streaks."""
    jumps = np.where(np.abs(np.diff(lons)) > 180)[0] + 1
    return np.insert(lons, jumps, np.nan), np.insert(lats, jumps, np.nan)


def cmd_track(sat: EarthSatellite, ts, name: str, minutes: float, step: float, out: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    start = datetime.now(timezone.utc)
    n = int(minutes / step) + 1
    times = ts.from_datetimes([start + timedelta(minutes=i * step) for i in range(n)])
    sub = wgs84.subpoint(sat.at(times))
    lons, lats = _break_at_antimeridian(
        np.asarray(sub.longitude.degrees, dtype=float),
        np.asarray(sub.latitude.degrees, dtype=float),
    )

    fig, ax = plt.subplots(figsize=(12, 6))
    try:  # optional: coastlines if cartopy is installed
        import cartopy.crs as ccrs
        plt.close(fig)
        fig = plt.figure(figsize=(12, 6))
        ax = plt.axes(projection=ccrs.PlateCarree())
        ax.set_global()
        ax.stock_img()
        ax.coastlines()
        ax.plot(lons, lats, color="red", linewidth=1.5, transform=ccrs.PlateCarree())
        ax.plot(lons[0], lats[0], "go", transform=ccrs.PlateCarree(), label="start")
    except ImportError:
        ax.set_xlim(-180, 180)
        ax.set_ylim(-90, 90)
        ax.grid(True, alpha=0.4)
        ax.set_xlabel("Longitude (deg)")
        ax.set_ylabel("Latitude (deg)")
        ax.plot(lons, lats, color="red", linewidth=1.5)
        ax.plot(lons[0], lats[0], "go", label="start")

    ax.set_title(f"{name} - ground track, next {minutes:.0f} min (from {start:%Y-%m-%d %H:%M} UTC)")
    ax.legend(loc="lower left")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved ground track to {out}")


def cmd_passes(sat: EarthSatellite, ts, lat: float, lon: float, hours: float, min_elev: float) -> None:
    observer = wgs84.latlon(lat, lon)
    t0 = ts.now()
    t1 = ts.from_datetime(datetime.now(timezone.utc) + timedelta(hours=hours))
    times, events = sat.find_events(observer, t0, t1, altitude_degrees=min_elev)

    if len(times) == 0:
        print(f"No passes above {min_elev} deg in the next {hours:.0f} hours.")
        return

    labels = ["rise", "peak", "set "]
    print(f"Passes above {min_elev} deg for ({lat:.3f}, {lon:.3f}), next {hours:.0f} h (UTC):")
    for ti, ev in zip(times, events):
        line = f"  {labels[ev]}  {ti.utc_strftime('%Y-%m-%d %H:%M:%S')}"
        if ev == 1:
            alt, _, _ = (sat - observer).at(ti).altaz()
            line += f"   max elevation {alt.degrees:.1f} deg"
        print(line)
        if ev == 2:
            print()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Satellite position, ground track, and pass predictor.")
    p.add_argument("--catnr", type=int, default=25544, help="NORAD catalog number (default: 25544 = ISS)")
    p.add_argument("--omm-file", help="Use a local OMM JSON file instead of downloading from CelesTrak")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("position", help="Current latitude/longitude/altitude")

    t = sub.add_parser("track", help="Plot the ground track")
    t.add_argument("--minutes", type=float, default=180, help="Length of track (default 180)")
    t.add_argument("--step", type=float, default=1, help="Minutes between points (default 1)")
    t.add_argument("--out", default="ground_track.png", help="Output image file")

    q = sub.add_parser("passes", help="Predict passes over a location")
    q.add_argument("--lat", type=float, required=True, help="Observer latitude (deg)")
    q.add_argument("--lon", type=float, required=True, help="Observer longitude (deg, east positive)")
    q.add_argument("--hours", type=float, default=24, help="Search window (default 24)")
    q.add_argument("--min-elev", type=float, default=10, help="Minimum elevation in degrees (default 10)")
    return p


def main() -> None:
    args = build_parser().parse_args()
    omm = load_omm(args)
    ts = load.timescale()
    sat = EarthSatellite.from_omm(ts, omm)
    name = omm.get("OBJECT_NAME", f"#{args.catnr}")
    describe(sat, omm)

    if args.command == "position":
        cmd_position(sat, ts)
    elif args.command == "track":
        cmd_track(sat, ts, name, args.minutes, args.step, args.out)
    elif args.command == "passes":
        cmd_passes(sat, ts, args.lat, args.lon, args.hours, args.min_elev)


if __name__ == "__main__":
    main()
