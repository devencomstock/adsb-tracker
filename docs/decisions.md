# Decisions

One entry per real choice. Status is **Draft** until approved, then **Approved**.

---

## #1: No hardware at first; work from recordings

- **Date:** 2026-10-12
- **Status:** Approved
- **Decision:** Start without an RTL-SDR dongle. Build and validate the decoder against existing
  recordings (dump1090's `testfiles/modes1.bin`).
- **Alternatives:** Buy the dongle now and decode live signals from day one.
- **Why:** A recording with a known answer key (dump1090's output) makes every decoder bug
  reproducible and checkable. Live data has no ground truth and adds antenna and placement problems
  on top of decoder problems. The dongle (about $35-45) is bought only once the decoder matches dump1090.

## #2: Parallel tracks

- **Date:** 2026-10-12
- **Status:** Approved
- **Decision:** Build the decoder and validate it against recordings. Meanwhile, build the
  backend, enrichment, dashboard and anomaly rules using public feed data (OpenSky, adsb.lol).
  The dongle is only needed to record my own samples.
- **Alternatives:** Serial build: finish the decoder first, then build everything downstream on
  its output.
- **Why:** Public feeds let the downstream work start before the decoder exists. How well they
  cover low-altitude KLAF traffic is still unverified and gets checked in Phase 5. The decoder
  becomes one more data source feeding the same tables.

## #3: PostgreSQL + PostGIS; TimescaleDB deferred

- **Date:** 2026-10-12
- **Status:** Approved
- **Decision:** Use PostgreSQL 16 with PostGIS (via Docker Compose, psycopg 3). Add TimescaleDB
  later only if volume demands it, and log that as a new decision.
- **Alternatives:**
  - ClickHouse: not chosen. Want to use postGre instead.
  - TimescaleDB from day one.
- **Why:** The core queries are spatial ("aircraft within N km of KLAF", "circling near the airport"),
  which PostGIS handles directly. Expected volume (one small area, a few students' use) is well within
  plain Postgres. TimescaleDB adds setup and concepts before there's a measured need for them.
