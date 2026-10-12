# adsb-tracker

> **Problem statement (draft for review: edit it to sound like you):**
> Planes fly over West Lafayette all day: airliners at cruise, plus a steady stream of
> flight-training traffic around the Purdue University Airport (KLAF). My friends and I look up and
> wonder what we're seeing, and existing trackers show everything everywhere without telling us
> whether anything is out of the ordinary. This project answers one question for Purdue students:
> *"What's that plane overhead right now, and is it doing something unusual (circling, pattern work,
> odd altitude)?"* To answer it, I'm building a 1090 MHz Mode S/ADS-B decoder from scratch, storing
> its output alongside public feed data (OpenSky, adsb.lol) in PostgreSQL/PostGIS, enriching each
> aircraft with FAA registry data, and showing it on a map centered on campus. Rule-based checks
> flag unusual behavior.

Status: the from-scratch decoder is done (Phase 4); next is the backend (Phase 5). See
[docs/ROADMAP.md](docs/ROADMAP.md) for the plan and [docs/decisions.md](docs/decisions.md) for the reasoning.

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
pytest
ruff check .
```

## The decoder

`src/decoder/` turns raw 1090 MHz samples (8-bit I/Q at 2 MHz) into Mode S / ADS-B messages. It's written from
scratch; dump1090 and pyModeS are only used as answer keys in tests. How each stage works is in
[docs/decoder-notes.md](docs/decoder-notes.md), and the design is in [docs/pseudocode.md](docs/pseudocode.md).

Get the test recording, the one dump1090 ships with, pinned to the commit the answer key came from:

```powershell
Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/antirez/dump1090/efe64db3c6ba1520291331628a33c1e208e851a6/testfiles/modes1.bin" -OutFile data\modes1.bin
(Get-FileHash data\modes1.bin -Algorithm SHA256).Hash   # expect 3A33E160...FD5FB3094
```

Decode it (one `*hex;` line per message, like `dump1090 --raw`; `--fields` adds the decoded fields, and
`--no-fix` turns off single-bit error correction):

```powershell
$env:PYTHONPATH = "src"
python -m decoder --ifile data\modes1.bin --fields
```

Compare with dump1090's answer key and measure speed (decision #8; writes the report):

```powershell
python scripts\compare_golden.py --report docs\phase4-golden-report.md
python scripts\measure_speed.py
```

Current result on `modes1.bin` ([docs/phase4-golden-report.md](docs/phase4-golden-report.md)):
- **default mode:** 216/217 messages matched;
- **no-fix mode:** 213/217 matched;
- **every miss explained, and every extra explained;**
- **speed:** 4.2 to 6.5 times real time in default mode, measured the same way every time (the method and the
  range across sessions are in the report's "Speed" section).

The tests that need the recording are skipped when `data\modes1.bin` is absent.

## Data sources and credits

- **adsb.lol** (`api.adsb.lol`): the automated public feed. Its data is licensed under the
  [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/summary/). Anything derived from it is credited to adsb.lol.
- **The OpenSky Network** (`opensky-network.org`): used only for manual, one-off research snapshots, as its
  [terms of use](https://opensky-network.org/about/terms-of-use) allow. Nothing from OpenSky is stored or committed (decision #18).
- **FAA**: the Releasable Aircraft Database and the NFDC airport record for KLAF.

Recordings, feed snapshots and downloaded data live in `data/` and are never committed.

## Database (PostgreSQL 16 + PostGIS, needs Docker Desktop)

One-time setup: copy `.env.example` to `.env` and replace both `change-me` values with the same new password.
`.env` is gitignored and must never be committed.

```powershell
docker compose up -d                       # start (first run downloads the image)
docker compose ps                          # wait for "(healthy)"
$env:PYTHONPATH = "src"
python -m ingest.migrate                   # apply db/migrations/*.sql; safe to run again
python -m pytest -m db                     # database tests, each run on its own throwaway database
docker compose stop                        # stop; the data stays in the pgdata volume
docker compose down                        # stop and remove the container; the data still stays
docker compose down -v                     # remove the data volume as well (deletes everything)
```

The database listens on 127.0.0.1:5432 only and is capped at 1 GB of memory. Idle, it uses about 70 MB.

## Layout

```
src/decoder/   from-scratch Mode S / ADS-B decoder
src/ingest/    decoder + public-feed ingestion
src/enrich/    FAA registry and other enrichment
src/api/       FastAPI backend
src/rules/     anomaly rules
web/           Leaflet frontend
db/migrations/ numbered SQL migrations
tests/         pytest (tests/golden/ holds tiny answer-key fixtures)
docs/          roadmap, decisions, decoder notes
data/          local recordings (gitignored)
```
