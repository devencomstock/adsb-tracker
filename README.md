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

Status: Phase 0 (setup). See [docs/ROADMAP.md](docs/ROADMAP.md) for the plan and
[docs/decisions.md](docs/decisions.md) for the reasoning.

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
pytest
ruff check .
```

Database (not started yet, needs Docker Desktop):

```powershell
Copy-Item .env.example .env   # then set a real password in .env
docker compose up -d
```

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
