# River Gage Stage Data Puller

A small, dependency-free Python script that downloads daily **river-stage
("gage height")** data for every U.S. Army Corps of Engineers
[RiverGages](https://rivergages.mvr.usace.army.mil/) station on a given river,
together with each station's coordinates.

Written by **Minseong Kang**.

## What it does

1. Reads the master station list from the RiverGages data-mining page and keeps
   every station whose name contains a chosen river keyword
   (default: `"Mississippi River"`). **No station IDs are hard-coded** — the list
   is rebuilt from the site on each run, so new gages are picked up automatically.
2. Scrapes each station's info page for **latitude / longitude** and the official
   station name.
3. Pulls the full **daily stage time series** (parameter `HG`, falling back to
   `HT`) for the requested date range.
4. Writes a tidy long CSV, one row per gage-day.

## Use a different river

Open `pull_gages.py` and change a single line:

```python
KEYWORD = "Mississippi River"   # -> "Arkansas River", "Kansas River", "Illinois River", ...
```

Everything else — the station list, coordinates, data, and the output filenames
— follows the keyword. Use the river name exactly as it appears on RiverGages.

You can also adjust the date range at the top of the file:

```python
START_DATE = "01/01/2006"
END_DATE   = "12/31/2025"
```

## Run

```bash
python3 pull_gages.py
```

Python 3 standard library only — no `pip install` required.

## Download the data

The CSV files are hosted separately (they are not committed to this repo):

- **Daily stage panel** + **station metadata**: <ADD-DOWNLOAD-LINK-HERE>

Running `pull_gages.py` also regenerates both files locally under `./data/`.

## Output (`./data/`)

`<river>_gage_stage_<start>_<end>.csv` — the long panel:

| column | description |
|--------|-------------|
| `gageID` | RiverGages station code (e.g. `GTTI4`, `01160`) |
| `gageNM` | station name (e.g. `Mississippi River at Baton Rouge (01160)`) |
| `lat`, `lon` | decimal degrees (WGS84) |
| `Date` | `YYYY-MM-DD` |
| `Stage` | daily stage, **feet** |

`<river>_station_metadata.csv` — one row per gage (`gageID`, `gageNM`, `lat`,
`lon`, `river_mile`, `param`, `n_obs`, `pulled`).

## Caveats

- **Stage is on each gage's own datum** ("Gage Zero"), so absolute levels are
  **not comparable across gages** — use each series as a within-gage time series,
  or convert to elevation using the per-gage datum if you need cross-gage levels.
- **Values can be revised** by USACE after the fact. The pull date is recorded in
  the `pulled` column of the stations file; cite it as the data vintage.
- Coordinates are normalized for the continental U.S. (a handful of station pages
  list lat/lon swapped or sign-flipped); stations with missing coordinates are
  left blank.

## Data source

U.S. Army Corps of Engineers, RiverGages — Rock Island District (MVR):
<https://rivergages.mvr.usace.army.mil/>
