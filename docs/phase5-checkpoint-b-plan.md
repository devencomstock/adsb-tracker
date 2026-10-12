# Phase 5 checkpoint B plan: decoder ingest and tracking

*Status: plan for review. Nothing here is built yet.*

Goal: turn the decoder's messages from a recording into rows in `positions` and `aircraft`
(source `decoder`), with per-aircraft CPR pairing, sanity checks, and freshness rules. Everything
new lives in `src/ingest/` and `db/migrations/`. The only change under `src/decoder/` is Gillham
altitude (item 2), which is a pure decoding function.

Sources used below:
- the Riddle, chapters "ADS-B basics" and "Airborne position";
- `dump1090.c` at `efe64db`;
- decisions #7, #9, #10, #18 and #20.

Numbers that aren't from a source are marked **(choice)** and become draft decisions.

---

## 1. Migration `0002_constraints.sql`

`CHECK` constraints are there to catch *decoding or ingest bugs*. Their limits are therefore the
widest values the message formats can encode, not guesses about physics.

| Table / column | Constraint | Why this limit |
|---|---|---|
| `positions.icao24`, `aircraft.icao24` | `~ '^[0-9a-f]{6}$'` | 24-bit ICAO address, 6 lowercase hex digits (decision #20) |
| `positions.squawk` | `IS NULL OR ~ '^[0-7]{4}$'` | 4 octal digits |
| `positions.track_deg` | `IS NULL OR (track_deg >= 0 AND track_deg < 360)` | true track; 360 is written as 0 |
| `positions.altitude_ft` | `IS NULL OR altitude_ft BETWEEN -1200 AND 126700` | the full encodable range (below) |

**The encodable altitude range:**
- **25 ft steps (Q = 1):** `25 × N − 1000` with N from 1 to 2047, which gives −975 to 50,175 ft. N = 0 means "no altitude".
- **Gillham (Q = 0), from the Riddle's formula `500 × N500 + 100 × N100 − 1300`:**
  - N500 = 0 and N100 = 1 gives the minimum, −1,200 ft;
  - N500 = 255 and N100 = 5 gives the maximum, 126,700 ft.

A stored altitude outside −1,200 to 126,700 can only be a bug. I'll recompute both ends from the
formula in a test.

**One consequence for checkpoint D:** adsb.lol marks non-ICAO addresses (for example from TIS-B)
with a leading `~` (ADS-B Exchange v2 docs, field `hex`). The icao24 check would reject those, so
the plan is to **skip them at ingest and count them**. See question Q3.

**How it's proven:** `db` tests insert one bad value per constraint, expecting `CheckViolation`, and
a boundary value that must be accepted. Migration 0002 must also apply cleanly to a database that
already holds valid 0001 rows.

## 2. Gillham (Q = 0) altitude for DF 0/4/20

- **Where:** `src/decoder/fields.py`, extending `ac13_altitude_ft`. It's still a pure function, with no pyModeS.
- **The algorithm** (Riddle, "Surveillance reply"):
  1. Drop the M and Q bits.
  2. Reorder the 11 remaining bits as D2 D4 A1 A2 A4 B1 B2 B4 C1 C2 C4.
  3. The first 8 bits are a **Gray-coded** 500 ft count (N500). The last 3 are a 100 ft count (N100).
  4. N100 values 0, 5 and 6 are invalid. N100 = 7 means 5.
  5. If N500 is odd, N100 becomes 6 − N100.
  6. Altitude = 500 × N500 + 100 × N100 − 1300.
- **Invalid codes return `None`,** as they do now. M = 1 (metric) still returns `None` (decision #17).
- **Before writing it:** I'll check the Gray-code step against the Riddle text and, if it's there, its worked
  example (`2000171806A983`).
- **Verified, in tests only, by an exhaustive comparison:**
  - Build a DF 4 frame for **every one of the 8,192 possible 13-bit codes**, then compare our result with
    pyModeS for each.
  - Every code where pyModeS gives an altitude must match. Every code where it gives `None` must give `None`.
  - Any disagreement is listed and explained, not silently accepted.
- **Open question:** ADS-B position messages (TC 9-18) can also carry a Q = 0 Gillham altitude, in a 12-bit
  field with no M bit. See question Q1.

## 3. Per-aircraft tracking (`src/ingest/tracker.py`)

Tracking keeps state across messages, so it lives in `src/ingest/`, not `src/decoder/` (Phase 4 left
this here). It consumes what the decoder already outputs: `Message(start, accepted)` plus
`decoder.fields` and `decoder.cpr`. It writes nothing; it returns fixes and rejections.

### State per ICAO address
- the latest **even** and the latest **odd** airborne-position frame: raw CPR numbers, altitude, time;
- the last **accepted** position, with its time;
- the latest velocity, callsign and squawk, each with the time it was received;
- a counter of consecutive sanity failures.

State for an aircraft is dropped after 60 s with no messages. That matches dump1090's
`MODES_INTERACTIVE_TTL` (`dump1090.c` line 91) and decision #7's window.

### Positions, step by step
For every airborne-position message (TC 9-18) at time `t`:
1. **Store it** as the latest even or odd frame.
2. **Global decode** if the other half arrived **at most 10 s earlier**.
   - **Source:** dump1090 pairs only frames "less than 10 seconds apart" (`dump1090.c` 2120-2122). The Riddle's worked example
     uses two messages "received within 10 seconds". The Riddle gives no hard limit, so the 10 s itself is **(choice)**.
   - **How:** `decoder.cpr.global_position`, using the newer frame. If it returns `None` (the pair straddles a zone
     boundary), there's no fix from the pair.
3. **Otherwise, local decode** against the last accepted position, if that position is **at most 10 s old**.
   - **Source:** the Riddle: "it is common to consider a position decoded within 10 seconds as a valid reference
     position". It must be within 180 NM ("which must be within a 180 NM range"). In 10 s that holds for any aircraft
     below about 64,800 kt.
4. **Sanity checks** on any candidate fix (next section). If it passes, it's accepted and becomes the new
   reference. If it fails, it's rejected and logged, and the reference is kept.

There is **no** local decode against the receiver's location in checkpoint B. `modes1.bin` was recorded
somewhere unknown, so a KLAF reference would give wrong positions. A receiver reference is a live-mode
feature, behind the range check, once the antenna exists.

### Sanity checks (the Riddle's "reasonable test"; the thresholds are (choice))
- **Maximum implied speed between accepted fixes: 1,000 kt.**
  - **Why that number:** civil aircraft cruise well below Mach 1. Even 600 kt true airspeed plus a strong jet-stream
    tailwind stays under 1,000 kt over the ground. A wrong CPR decode is typically off by a whole zone, which is
    hundreds of kilometres in seconds.
  - **Small gaps:** for fixes less than 1 s apart, a fixed 0.5 NM tolerance replaces the speed test, so CPR rounding
    (metres) can't fail it.
- **Maximum range from a configured reference point: 300 NM, only when a reference is given.**
  - **Why that number:** that's roughly the radio line-of-sight distance to an aircraft at 45,000 ft (about
    1.23 × √altitude in feet, in NM). **That formula needs a citation before I rely on it.**
  - **For recordings** with no `--reference`, the check is skipped, and the summary says so.
- **Stuck on a bad first fix:**
  - **The risk:** if an aircraft's *first* accepted fix were wrong, every later correct fix would fail the speed test
    against it.
  - **The fix:** after **3 consecutive** sanity failures, the aircraft's state is reset and its next global decode is
    trusted fresh **(choice)**.
- **Rejections are logged,** with the ICAO address, the time, the candidate position, which check failed and by how
  much. They go to `data/logs/ingest-<UTC time>.log` (gitignored), and the run summary prints counts per reason. No
  database table is needed for them yet; see question Q4.

### Attaching velocity, callsign and squawk to a fix
Each accepted position row gets the latest value of each field **only if that value is fresh**. Otherwise it gets `NULL`.

| Field | Comes from | Fresh if received within | Why |
|---|---|---|---|
| altitude | the same position message | n/a (same frame) | it's in the position message itself |
| ground speed, track, vertical rate | TC 19 velocity | **10 s** | velocity is sent at 2 Hz airborne (Riddle, "ADS-B basics", ADS-B v2 rates table), so 10 s is about 20 chances. Speed and track change little in 10 s; older than that, it's a reception gap, not data. |
| callsign | TC 1-4 identification | **60 s** | sent at 0.2 Hz airborne (same table), so 60 s is about 12 chances. A callsign rarely changes in flight. |
| squawk | DF 5/21 identity replies | **60 s** | these are replies to radar interrogations, which have no fixed broadcast rate, so **this window is a guess to measure with live data** (choice). TC 28 status messages also carry the squawk but aren't decoded yet. |
| on_ground | n/a | `false` for airborne-position fixes; `NULL` otherwise | surface positions aren't decoded (deferred until the dongle) |

## 4. Timestamps

- **Recordings have no clock.** `--start-time` is **required** for a recording: a UTC ISO-8601 time such as
  `2026-10-12T19:00:00Z`. Then `observed_at = start_time + start_sample / 2,000,000 s`, using the same sample-index
  clock as decision #7.
- **Duplicate runs:** re-ingesting with the same `--start-time` gives identical `(source, icao24, observed_at)`, so
  `ON CONFLICT DO NOTHING` makes the second run add nothing. A different start time inserts a second copy, so the
  summary prints the start time used.
- **Live mode later,** once the dongle exists:
  - the start time becomes the host's UTC clock when the first sample buffer arrives;
  - samples are counted continuously from there, so time stays monotonic and shared with decision #7's window;
  - the host clock should be NTP-synced (Windows Time service), and its drift checked against public-feed timestamps
    for the same aircraft;
  - USB buffering adds a small fixed delay, to be measured with the dongle. Not needed now.

## 5. Writing to Postgres (`src/ingest/decoder_ingest.py`)

- **Command line:**
  `python -m ingest.decoder_ingest --ifile data/modes1.bin --start-time 2026-10-12T19:00:00Z [--no-fix] [--reference LAT,LON] [--write-dev] [--keep]`
- **Where it writes:**
  - **By default, a throwaway database** `adsb_ingest_<random>`. It's created, migrated, filled, summarized, then dropped,
    unless `--keep` is given, which leaves it for inspection and prints its name.
  - **Writing to the dev database (`PGDATABASE`) needs `--write-dev`.** Without that flag, the code never connects to
    the dev database's name at all.
- **Rows:** `source = 'decoder'`, with the units from decision #20. Track is stored with 360 written as 0.
- **Batching:** buffered rows are written with `executemany`, 500 at a time **(choice)**, which keeps memory flat.
  Positions use `INSERT ... ON CONFLICT (source, icao24, observed_at) DO NOTHING`.
- **Aircraft rows:** one upsert per address per batch:
  `INSERT ... ON CONFLICT (icao24) DO UPDATE SET first_seen = LEAST(...), last_seen = GREATEST(...)`.
  `first_seen` and `last_seen` are the earliest and latest stored position times. An aircraft with messages but no
  accepted position gets no row.
- **Transactions:** each batch is one transaction. A crash loses at most one batch. Re-running the command is safe,
  because of `ON CONFLICT`.
- **Summary printed at the end:**
  - messages read;
  - fixes accepted per decode path (global or local);
  - rejections per reason;
  - rows inserted and rows skipped as duplicates;
  - aircraft added or updated;
  - the database used and the start time.
- **Not in this checkpoint:** `decoder_messages` (raw provenance rows). The schema doesn't have it yet (decision #20 deferred it). I
  propose adding it as migration 0003 in checkpoint B **only if you want it**, kept for recordings and off for live
  mode. See question Q2.

## 6. Tests

**Without a database** (they run everywhere):
- **Gillham:** the exhaustive 8,192-code comparison with pyModeS; the Riddle example if one exists; invalid codes give
  `None`; M = 1 gives `None`.
- **Tracker, on synthetic message sequences:**
  - pairing within 10 s versus 10.1 s apart;
  - local decode only with a reference at most 10 s old;
  - the speed test rejects a jump, and the 0.5 NM tolerance applies below 1 s;
  - the 3-strike reset;
  - the 60 s state expiry;
  - the freshness windows for velocity (10 s), callsign (60 s) and squawk (60 s), at and just past each edge;
  - range check skipped without a reference, and applied with one.
- **Timestamps:** `--start-time` parsing (UTC required, local times refused) and `start + sample / 2e6`.

**Against the golden data and pyModeS** (no database; needs `data/modes1.bin`, otherwise skipped):
- **The pairs:** run the decoder plus tracker over `modes1.bin` (no-fix and default). For every even/odd pair our tracker
  global-decodes, pyModeS must give the same latitude and longitude (`pyModeS.decode` on the two frames with matching
  timestamps), to within 1e-6 degrees.
- **The 31 pairs you cross-checked:** I'll rebuild the list from the golden TC 11 frames (consecutive even/odd within 10 s)
  and confirm the count is 31 before relying on it. If it isn't 31, I'll stop and report rather than adjust.
- **Local decodes:** checked the same way against pyModeS with `reference=` set to the previous fix.
- **Sanity log:** the run prints how many fixes were rejected. Every rejection on `modes1.bin` (one strong aircraft) gets
  explained in the checkpoint report.

**Marked `db`** (throwaway database, as in checkpoint A):
- migration 0002's constraints and boundaries;
- an ingest of `modes1.bin` lands in a throwaway database by default, and the dev database is untouched (row counts
  before and after);
- a second identical ingest inserts 0 rows;
- the `aircraft` first_seen and last_seen match `min()` and `max()` of the stored positions;
- **without `--write-dev`, the dev database is never connected to:** the test checks connection targets via a fake
  connect function.

## 7. Risks, open questions, decisions

**Risks:**
- **One aircraft, unknown location:** `modes1.bin` has a single aircraft (`4d2023`) at an unknown location. The pairing and
  local-decode logic gets exercised; the range check and multi-aircraft interleaving barely do. Synthetic tests cover
  those, but live data is the real test.
- **Arbitrary start time:** absolute times in the database for a recording are meaningless beyond being consistent within
  one run. Phase 6 queries like "overhead right now" will never match recording data unless I ingest it with
  `--start-time` close to now (fine for demos; I'll say so in the README).
- **Rejection logs:** they could grow on live data. The log is per run and gitignored; rotation is a live-mode concern.
- **Memory:** the recording is decoded fully in memory first (356,868 samples, a few MB). Rows are written in batches of 500.
  No new process stays running.

**Questions for you:**
- **Q1.** Also decode Gillham altitude in **ADS-B position messages** (TC 9-18, Q = 0)? It's the same algorithm on a
  12-bit field. Recommendation: **yes**, it's cheap and testable the same way. Otherwise a Q = 0 aircraft's positions
  get stored with `NULL` altitude.
- **Q2.** Add `decoder_messages` (raw hex, DF, start sample, run) now as migration 0003, kept for recordings and off for
  live? Recommendation: **yes, for recordings only**. It's the evidence trail behind every decoder row. Retention: the
  rows for a run are deleted when its throwaway database is dropped, and live mode stays off unless you turn it on.
- **Q3.** Non-ICAO addresses (`~` prefix) from adsb.lol: **skip and count them** (recommended), or store them in a
  separate column or table?
- **Q4.** Rejection log: a file in `data/logs/` (recommended for now), or a `position_rejections` table?
- **Q5.** Throwaway ingest database: **drop it by default** and keep it with `--keep` (recommended), or keep it by
  default?

**New decisions I expect (all Draft until you approve them):**
- **#21:** migration 0002's constraints and the encodable-range rule.
- **#22:** Gillham altitude, tested exhaustively against pyModeS; the scope depends on Q1.
- **#23:** CPR pairing at most 10 s apart; local decode against an accepted fix at most 10 s old; no receiver reference
  for recordings.
- **#24:** sanity checks: 1,000 kt; 300 NM with a reference (formula cited); 3-strike reset; log file.
- **#25:** freshness windows: velocity 10 s, callsign 60 s, squawk 60 s (to be measured live); state expiry 60 s.
- **#26:** timestamps: a required `--start-time` for recordings; the live-mode clock plan.
- **#27:** ingest targets: a throwaway database by default, `--write-dev` for the dev database, batches of 500,
  `ON CONFLICT DO NOTHING`, and the aircraft upsert rule; `decoder_messages` scope per Q2.
