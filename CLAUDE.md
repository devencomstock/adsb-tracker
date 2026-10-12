# ADS-B Aircraft Tracking & Anomaly Detection

## Project
Build a from-scratch 1090 MHz Mode S/ADS-B decoder, feed a PostgreSQL/PostGIS backend (plus OpenSky/adsb.lol data),
enrich with FAA registry data, show it on a Leaflet map, and flag anomalies with rule-based checks.
No SDR hardware yet: work from recordings. An LLM natural-language query layer is optional and comes last.
Real user: a Purdue student (me and friends) curious about the planes flying over West Lafayette, including flight-training traffic around the Purdue University Airport (KLAF).
The one question the dashboard answers: "What's that plane overhead right now, and is it doing something unusual (circling, pattern work, odd altitude)?"
Dashboard defaults: map centered on the Purdue campus, click a plane for a detail card (type, owner, altitude, speed), and highlight flagged aircraft.

## How we work
- BUILD mode for all phases: you write the code, I review it. Follow docs/ROADMAP.md in order. Current phase: Phase 3.
- Before non-trivial changes, propose a short plan and wait for my approval.
- The decoder is written from scratch under src/decoder/. pyModeS and dump1090 are answer keys only.
  Never import pyModeS under src/decoder/ and never copy dump1090 code.
- Never claim the decoder matches dump1090 without running the golden comparison and showing the diff.
- For each decoder stage (samples to magnitude, preamble detection, pulses to bits, CRC, message routing,
  output fields), write a short plain-English explanation in docs/decoder-notes.md so I can follow and explain it.
- Log every real choice in docs/decisions.md (date, decision, alternatives, why). Draft it, I approve.
- If unsure about a protocol detail, API, or rate limit, say so and check the source. Do not guess.
  Cite sources (The 1090 MHz Riddle, ICAO Annex 10, dump1090 source, official API docs).

## Environment
- I am on native Windows with PowerShell. Give PowerShell-compatible commands and use pathlib, not hardcoded separators.
- Building dump1090 needs a C toolchain and the librtlsdr headers. Do that in WSL, and tell me before starting.
- Docker Desktop runs the database. Do not assume it is running; check first.

## Stack and rules
- Python 3.11+, venv, NumPy, pytest, ruff, type hints. One small function per pipeline stage.
- pyModeS and dump1090 are validation tools only.
- PostgreSQL 16 + PostGIS via Docker Compose, psycopg 3 driver. Add TimescaleDB later only if volume demands it,
  and log that decision. Schema changes go in numbered SQL files under db/migrations/. Ask before adding an ORM.
- FastAPI for the API, Leaflet + OpenStreetMap for the map, plain JS frontend.
- Anomaly rules are plain Python functions with tests: loitering/circling near the airport, altitude/speed/vertical-rate jumps,
  squawks 7500/7600/7700.
- Ask before adding any dependency.
- Public repo: no secrets, .env, employer code or schemas, or large data files.
  Recordings go in data/ (gitignored); only tiny fixtures are committed. Commit .env.example, never .env.

## Git
- Branch per phase: phase-N-short-name. Small commits with clear messages.
- Never push to main directly. No force pushes. Open a PR per phase with gh.

## Layout
src/decoder/  src/ingest/  src/enrich/  src/api/  src/rules/  web/  db/migrations/
tests/  tests/golden/  docs/  data/
