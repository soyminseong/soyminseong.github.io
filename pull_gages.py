#!/usr/bin/env python3
"""
* Written by Minseong Kang, 2026-06-25

pull_gages.py
Download daily river-stage ("gage height") series for every USACE RiverGages
station whose name contains a chosen river name (default: "Mississippi River").

  >>> Want a different river?  Just set KEYWORD below to any river name as it
      appears on RiverGages, e.g.  KEYWORD = "Arkansas River"  or  "Kansas River"
      or "Illinois River".  Nothing else needs to change -- the station list,
      coordinates, data, and output filenames all follow the keyword. <<<

Source : U.S. Army Corps of Engineers RiverGages (Rock Island District / MVR)
         https://rivergages.mvr.usace.army.mil/

How it works
  1. Read the master station list from the RiverGages "data mining" page and
     keep every station whose display name contains the keyword (default:
     "Mississippi River").  No station IDs are hard-coded -- the list is
     rebuilt from the site each run, so new gages are picked up automatically.
  2. For each station, scrape its station-info page for latitude / longitude
     and the official station name.
  3. Pull the full daily stage time series (parameter HG; falls back to HT)
     for the requested date range from the data-mining endpoint.
  4. Write a tidy long CSV with one row per gage-day:
         gageID, gageNM, lat, lon, Date, Stage

Output (written next to this script, in ./data/; <river> follows KEYWORD)
  <river>_gage_stage_<START>_<END>.csv  long panel, one row / gage / day
  <river>_station_metadata.csv          one row / gage: ID, name, lat, lon, river mile

Dependencies: Python 3 standard library only (no pip install required).

Usage
  python3 pull_gages.py

Notes
  - Stage is reported in feet, on each gage's own datum (see "Gage Zero" /
    "Datum" on the station-info page). Stages are NOT comparable in absolute
    level across gages; use them as within-gage time series.
  - RiverGages values can be revised after the fact, so record the pull date
    (printed in the run log and saved in the station file's `pulled` column).

"""

import csv
import html
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #
KEYWORD     = "Mississippi River"   # river-name filter (case-insensitive).
                                    # Change to any river, e.g. "Arkansas River",
                                    # "Kansas River", "Illinois River".
START_DATE  = "01/01/2006"          # mm/dd/yyyy, inclusive
END_DATE    = "12/31/2025"          # mm/dd/yyyy, inclusive
PARAMETERS  = ("HG", "HT")          # stage codes to try, in order (HG, then HT)
PULL_DATE   = "2026-06-25"          # date this script was last run (data vintage)

BASE        = "https://rivergages.mvr.usace.army.mil/WaterControl"
LIST_URL    = f"{BASE}/datamining2.cfm"
INFO_URL    = f"{BASE}/stationinfo2.cfm"
DATA_URL    = f"{BASE}/datamining2.cfm"

TIMEOUT     = 120                   # seconds per request
PAUSE       = 0.3                   # seconds between stations (be polite)
MIN_ROWS    = 10                    # a parameter "works" if it returns > this many rows

OUT_DIR     = Path(__file__).resolve().parent / "data"
_SLUG       = KEYWORD.lower().replace(" ", "_")            # e.g. "mississippi_river"
STAGE_CSV   = OUT_DIR / f"{_SLUG}_gage_stage_{START_DATE[-4:]}_{END_DATE[-4:]}.csv"
STATION_CSV = OUT_DIR / f"{_SLUG}_station_metadata.csv"

# --------------------------------------------------------------------------- #
# HTTP helper                                                                 #
# --------------------------------------------------------------------------- #
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE          # the .mil cert chain is often incomplete
_HEADERS = {"User-Agent": "Mozilla/5.0 (academic research data pull)"}


def fetch(url, params=None, data=None):
    """GET (or POST, if `data` is given) and return the response body as text."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL) as r:
        return r.read().decode("latin-1", "ignore")


# --------------------------------------------------------------------------- #
# Scrapers                                                                    #
# --------------------------------------------------------------------------- #
_OPTION_RE = re.compile(r'<option value="([^"]+)"\s*>([^<]+)')
_LATLON_RE = re.compile(r"(Longitude|Latitude):\s*([\-0-9.]+)")
_RMILE_RE  = re.compile(r"River Mile:\s*([\-0-9.]+)")
_DATA_RE   = re.compile(
    r"(\d{2})/(\d{2})/(\d{4}) \d{2}:\d{2}</div></td>\s*<td><div[^>]*>\s*([\-\d.]+)"
)


def get_stations(keyword):
    """Return [(gageID, gageNM), ...] for every station whose name matches `keyword`."""
    page = fetch(LIST_URL)
    key = keyword.lower()
    seen, stations = set(), []
    for sid, name in _OPTION_RE.findall(page):
        name = html.unescape(name).strip()
        if key in name.lower() and sid not in seen:
            seen.add(sid)
            stations.append((sid, name))
    return stations


def _norm_coords(lat_raw, lon_raw):
    """Normalize a (lat, lon) pair for continental-U.S. gages.

    A few RiverGages station pages enter coordinates with the latitude and
    longitude swapped or with the wrong sign (e.g. station HSTM5 lists
    "Longitude: -44.76  Latitude: 92.87" -- a 90+ latitude is impossible).
    All USACE RiverGages stations sit in the lower 48, so we classify each
    number by its magnitude: 18-50 -> latitude (forced +, N), 60-130 ->
    longitude (forced -, W). Returns ('', '') if coordinates are missing
    (e.g. 0/0) or implausible.
    """
    lat = lon = None
    for raw in (lat_raw, lon_raw):
        try:
            v = abs(float(raw))
        except (TypeError, ValueError):
            continue
        if 18 <= v <= 50:
            lat = v
        elif 60 <= v <= 130:
            lon = -v
    if lat is None or lon is None:
        return "", ""
    return f"{lat:.8f}", f"{lon:.8f}"


def get_latlon(sid):
    """Return (lat, lon, river_mile) for a station, or ('', '', '') if unavailable."""
    page = fetch(INFO_URL, params={"sid": sid, "fid": sid, "dt": "S"})
    coords = dict(_LATLON_RE.findall(page))
    lat, lon = _norm_coords(coords.get("Latitude"), coords.get("Longitude"))
    rm = _RMILE_RE.search(page)
    return lat, lon, (rm.group(1) if rm else "")


def pull_stage(sid):
    """Return (parameter, [(YYYY-MM-DD, stage), ...]) for a station, or (None, [])."""
    for param in PARAMETERS:
        page = fetch(
            DATA_URL,
            params={"sid": sid},
            data={
                "fld_station": sid, "fld_parameter": param,
                "fld_from": "-999", "fld_to": "999",
                "fld_fromdate": START_DATE, "fld_todate": END_DATE,
            },
        )
        rows = _DATA_RE.findall(page)
        if len(rows) > MIN_ROWS:
            series = [(f"{yy}-{mm}-{dd}", val) for mm, dd, yy, val in rows]
            return param, series
    return None, []


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stations = get_stations(KEYWORD)
    print(f"Found {len(stations)} stations matching '{KEYWORD}'\n")

    stage_rows, station_rows, failures = [], [], []
    for i, (sid, name) in enumerate(stations, 1):
        try:
            lat, lon, rmile = get_latlon(sid)
            param, series = pull_stage(sid)
        except Exception as e:                       # network hiccup -> log, keep going
            print(f"[{i:>3}/{len(stations)}] {sid:<10} ERROR  {e}")
            failures.append(sid)
            continue

        station_rows.append((sid, name, lat, lon, rmile, param or "", len(series), PULL_DATE))
        if series:
            for date, stage in series:
                stage_rows.append((sid, name, lat, lon, date, stage))
            span = f"{series[-1][0][:4]}-{series[0][0][:4]}"
            print(f"[{i:>3}/{len(stations)}] {sid:<10} {param} {len(series):>5} rows ({span})  {name}")
        else:
            print(f"[{i:>3}/{len(stations)}] {sid:<10} NO DATA              {name}")
            failures.append(sid)
        time.sleep(PAUSE)

    # ---- write outputs ---------------------------------------------------- #
    with open(STAGE_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gageID", "gageNM", "lat", "lon", "Date", "Stage"])
        w.writerows(stage_rows)

    with open(STATION_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gageID", "gageNM", "lat", "lon", "river_mile", "param", "n_obs", "pulled"])
        w.writerows(station_rows)

    # ---- summary ---------------------------------------------------------- #
    n_gages = len({r[0] for r in stage_rows})
    print(f"\nDone. {len(stage_rows)} rows across {n_gages} gages with data.")
    print(f"  stage panel : {STAGE_CSV}")
    print(f"  station meta: {STATION_CSV}")
    if failures:
        print(f"  no data / failed ({len(failures)}): {', '.join(failures)}")


if __name__ == "__main__":
    sys.exit(main())
