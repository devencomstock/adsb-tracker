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
  - ClickHouse: not chosen. Want to use Postgres instead.
  - TimescaleDB from day one.
- **Why:** The core queries are spatial ("aircraft within N km of KLAF", "circling near the airport"),
  which PostGIS handles directly. Expected volume (one small area, a few students' use) is well within
  plain Postgres. TimescaleDB adds setup and concepts before there's a measured need for them.

## #4: Golden output generated twice, with and without error correction

- **Date:** 2026-10-12
- **Status:** Approved
- **Decision:** Generate dump1090's answer key on `modes1.bin` in two settings, each as raw hex
  (`--raw`) and as decoded text:
  - **no-fix** (`--no-fix`): single-bit CRC error correction off. My decoder matches this first.
  - **default**: dump1090's defaults (CRC check on, single-bit fix on, no `--aggressive`). Matched later,
    once my decoder has error correction.
  Exact commands and checksums are in `tests/golden/README.md`.
- **Alternatives:**
  - Default settings only. Rejected because my first decoder has no error correction, so any
    difference would mix "my bug" with "a feature I haven't built yet".
  - Also generate `--aggressive` (two-bit fixes) output. Deferred because it's a later feature, and it can be added if needed.
  - Committing a tiny subset only. Not needed because all four files total about 140 KB.
- **Why:** Each comparison isolates one thing. On this recording both settings give the same
  217 messages; they differ only in two DF11 lines (IID interpretation vs a bit-55 fix) and 6
  "error fixed" notes. So no-fix is a fair first target, and the gap to default is small and documented.

## #5: Pin the answer key to one dump1090 commit

- **Date:** 2026-10-12
- **Status:** Approved
- **Decision:** The golden files come from antirez/dump1090 at commit
  `efe64db3c6ba1520291331628a33c1e208e851a6`, built in WSL outside this repo (`~/src/dump1090`).
  It isn't vendored. The commit SHA and the sha256 of the input and outputs are recorded.
- **Alternatives:** Use whatever HEAD is when regenerating, or vendor dump1090 into the repo
  (ruled out by the project rules: don't copy dump1090 code).
- **Why:** Upstream can change at any time, and a change to its demodulator would silently move the
  answer key. Pinning makes "matches dump1090" mean one exact,
  reproducible thing.
