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

## #6: Write the decoder in Python with NumPy (not C)

- **Date:** 2026-10-12
- **Status:** Draft, pending approval
- **Decision:** Write the Phase 4 decoder in Python 3 with NumPy. Do the per-sample work (magnitude, and preamble
  screening where possible) as whole-array NumPy operations. The per-candidate steps (bits, CRC, routing) stay
  plain Python functions.
- **Alternatives:**
  - **C** (like dump1090).
    - Pros: fastest, real-time live decoding is proven possible by dump1090 itself, and it's close to how receivers are built.
    - Cons: slower to write and debug, a second toolchain on Windows (WSL), harder to unit-test next to pyModeS,
      and the temptation to drift toward dump1090's code, which the project rules forbid copying.
  - **Python with no NumPy.** Simplest, but a Python loop over every sample is very slow for 2 million samples per second.
  - **Python with a compiler such as Numba or Cython.** Faster loops, but it's a new dependency and needs approval. Deferred
    until a measurement shows it's needed.
- **Why:** Phase 4 runs offline on a 0.18 s recording, where correctness and readability matter and speed doesn't.
  Python keeps every stage small, testable with pytest, and easy to compare against pyModeS and the golden files.
  Live use with the dongle means 2 MHz × 2 bytes = 4 MB/s of input. Whether Python + NumPy keeps up is
  **unmeasured**. Before buying the dongle (decision #8), time the decoder on `modes1.bin` and report samples per second
  against the 2,000,000 needed. If it's too slow, revisit this decision.
- **Stretch idea (not part of Phase 4):** port only the demodulator (stages 1-3) to C later, as a learning exercise or
  for live speed. It would be written from my own pseudocode and checked against the same golden files and the Python version.

## #7: "Recently seen" uses recording time with a 60-second window

- **Date:** 2026-10-12
- **Status:** Draft, pending approval
- **Decision:** The list of recently seen ICAO addresses (used to accept DF 11 frames that carry an interrogator ID and the
  address-parity formats DF 0/4/5/16/20/21/24) timestamps each entry with **recording time**,
  `sample index / 2,000,000` seconds. An entry counts as recent for **60 seconds**. Only DF 11/17/18 frames with
  CRC remainder 0 and no repaired bit add an entry, matching dump1090 (`dump1090.c` 1197-1200 at `efe64db`).
- **Alternatives:**
  - **A: seen anywhere earlier in the run, never expires.** Reproduces the golden output, but in live use an address
    would stay trusted forever.
  - **C: wall clock with 60 s, exactly like dump1090** (66, 910-924). Test results would depend on machine speed, so a
    slow test machine could expire entries that dump1090 kept.
- **Why:** On `modes1.bin` (0.178 s long) A, B and C all reduce to "seen earlier in the file". That's why B reproduces the
  no-fix golden output. Replaying the golden file under this rule accepts all 20 interrogator-ID DF 11 frames and all
  34 address-parity frames, with zero exceptions. B also keeps dump1090's 60 s window for long recordings and live use, and
  stays deterministic. **Verification in Phase 4:**
  1. The decoder's no-fix message set must equal the golden file.
  2. Disabling the list must remove exactly those 54 messages.
- **Limit:** `modes1.bin` contains one aircraft, so it barely tests this rule. A longer recording of my own will test it properly.

## #8: What "the decoder matches dump1090" means

- **Date:** 2026-10-12
- **Status:** Draft, pending approval
- **Decision:** Two levels, both against the pinned golden files (`tests/golden/`):
  1. **Bit-level stages (CRC, frame length, routing, output fields): 100% on the golden hex.** Fed the 217 lines of
     `modes1_raw_nofix.txt`, the decoder must:
     - accept all 217;
     - assign the same DF and length to each;
     - route them into exactly the counts in `docs/pseudocode.md`;
     - reproduce every raw line byte for byte;
     - match the decoded fields (DF, ICAO, CA, TC, altitude, F flag, CPR lat/lon) in `modes1_decoded_nofix.txt`.
     No exceptions are allowed.
  2. **Demodulator (stages 1-3): judged on the no-fix message set.** Run on all of `modes1.bin` and report three
     lists: matched, missing (in golden but not ours) and extra (ours but not golden).
     - **Extra messages: zero allowed.** Every message the decoder outputs must be in the golden set.
     - **Missing messages: every one must have a written explanation.** Typical causes are dump1090's phase-correction
       retry, its "hold the previous bit" rule, its contrast filter, or its looser preamble test. Each explanation must be
       backed by evidence such as the message's samples and which check it failed.
- **Buy the dongle when:**
  - level 1 passes at 100%;
  - level 2 has **zero extra messages**, **at most 10 missing (95% or more of 217 matched)**, and **every miss explained**;
  - the speed measurement in decision #6 has been reported.
- **Go back and adjust the demodulator when:**
  - any extra message appears;
  - any miss is unexplained;
  - more than 10 messages are missing;
  - or a message is found at a golden start sample but its bits differ from the golden hex (a stage 3 bug, not a heuristic gap).
- **Alternatives:**
  - Require an exact 217/217 match. This would force reproducing every dump1090 heuristic, which would push the decoder toward
    copying it.
  - "Close enough" with no explanation required. This would hide real bugs.
- **Why:** The bit-level stages are pure logic, so anything less than 100% is a bug. The demodulator works on noisy
  analog signals, where dump1090 uses tuned tricks that aren't in the Riddle. Allowing no extra messages means the
  decoder never outputs anything dump1090 rejected. Requiring every miss to be explained keeps it honest without requiring a copy.
  The 10-message (about 5%) limit is the threshold for buying the dongle.
