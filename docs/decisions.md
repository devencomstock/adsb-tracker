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
- **Status:** Approved
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
- **Status:** Approved
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
- **Default (fix-on) file:** the same rule also explains it, with 52 list-dependent messages and 0 exceptions.
  Repaired frames never add an address, so the default run has 159 list sources against 163 in no-fix:
  - 4 frames came out clean in the no-fix run but needed a one-bit repair in the default run.
  - 2 DF 11 frames read as interrogator ID 1 in the no-fix run were repaired (bit 55) in the default run, because dump1090
    repairs before applying the interrogator-ID rule.

  Details are in `docs/pseudocode.md` stage 4c.
- **Limit:** `modes1.bin` contains one aircraft, so it barely tests this rule. A longer recording of my own will test it properly.

## #8: What "the decoder matches dump1090" means

- **Date:** 2026-10-12
- **Status:** Approved
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
     - **Expected misses.** Against the no-fix file, up to 4 messages (golden lines 112, 185, 188, 193) may be missed until
       a phase-correction retry like dump1090's is implemented. dump1090's default run had to repair one bit in each of
       them, and they appear clean in the no-fix file only because dump1090 re-read them (`docs/pseudocode.md` stage 4c).
       They count toward the 10-message limit, and each still needs its written explanation.
     - **Against the default file**, single-bit repair should recover those frames, but **only where our demodulator reads
       at most one bit wrong.** With a plain half-versus-half comparison:
       - lines 185, 188 and 193 have exactly one wrong bit (the one dump1090 repaired);
       - line 112 has three (bits 66, 85, 110), which single-bit repair can't fix.

       So line 112 may stay a documented miss against the default file too, unless the demodulator reads bits 85 and 110 correctly.
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

## #9: Never repair the first 5 bits (the DF), for either frame length

- **Date:** 2026-10-12
- **Status:** Approved
- **Decision:** Single-bit repair (`src/decoder/crc.py`) only considers bits 5 onward, for both 56- and 112-bit frames.
- **What dump1090 does** (read from `dump1090.c` at `efe64db`, in WSL):
  - It builds its one-bit error table over positions 5-111 of a 112-bit frame (line 806), so it never repairs the DF of a long frame.
  - For a 56-bit frame it shifts those positions by 56 and keeps any that land inside the frame (874-879). Table positions 56-60
    land on bits 0-4, so **it can repair the DF of a short frame**.
  - It reads the DF before repairing (1099) and doesn't re-read it afterwards (1112-1121). A short frame whose DF bits got
    repaired is still handled as the DF it was first read as (11).
- **Alternatives:** Copy dump1090's behavior exactly: repairable bits 0-55 for short frames.
- **Why:** A wrong DF means the frame was also cut to the wrong length, so "repairing" it produces a message whose type
  and length disagree. dump1090's own comment at 792-794 gives the same reason for excluding the DF, and the short-frame case
  looks like a side effect of reusing the 112-bit table. **It can't affect `modes1.bin`:** the bits dump1090 repaired
  in the default file are 66, 55, 55, 61, 99 and 5, none of them below 5. If a future recording shows a difference, it would
  appear as a default-run miss under decision #8 and be explained there.

## #10: Preamble signal floor of 9.0

- **Date:** 2026-10-12
- **Status:** Approved
- **Decision:** A preamble candidate's weakest pulse must have magnitude of at least 9.0 (`SIGNAL_FLOOR` in
  `src/decoder/pipeline.py`; magnitude units are 0 to about 180).
- **Measured on `modes1.bin`:**
  - The median magnitude is 3.0.
  - At the 194 golden messages with an exact start, the weakest pulse is never below 24.4 (5th percentile 27.0).
  - All 194 pass the preamble test.
- **Alternatives:** no floor (relies on the shape test alone, so more noise reaches the CRC); a floor tied to the
  measured noise level per buffer (better for live use, but more to build and test).
- **Why:** 9.0 is three times the noise median and still well below the weakest real pulse, so it can't cause a miss here.
  Revisit with my own recordings, where signal levels will differ.
- **Limit:** measured on one strong aircraft (`4d2023`, the only one in `modes1.bin`). Revisit with live data.

## #11: Start-sample fixture built with dump1090 prefix search

- **Date:** 2026-10-12
- **Status:** Approved
- **Decision:** `tests/golden/modes1_starts.txt` gives each golden no-fix line's start sample. It's built in two steps:
  1. `scripts/dump1090_prefix_search.sh nofix all` (WSL) finds the shortest prefix after which dump1090 outputs the line.
  2. `scripts/make_start_fixture.py` refines it by searching estimate−8 to estimate+32 for the start where plain bit
     comparison reproduces the golden hex.

  Lines with such a start are flagged `exact` (194); the others are `approximate` (23). Tests assert exact starts only.
  Nothing under `src/decoder/` reads the fixture.
- **Alternatives:** matching golden hex against the recording alone (can't place frames dump1090 decoded with phase
  correction, and confuses repeated identical messages); reading dump1090's internal buffer offsets (needs its debug code).
- **Why:** It uses dump1090 only as a black box, and every `exact` start is checked against the recording.

## #12: Skip candidates that start inside an accepted message

- **Date:** 2026-10-12
- **Status:** Approved
- **Decision:** After a message is accepted, preamble candidates that begin before its last sample are ignored.
- **Alternatives:** try every candidate (the same frame could be accepted twice from neighboring start samples, and
  bits inside a real message can look like a preamble).
- **Why:** One transmission can't contain another. dump1090 also jumps past a message once its CRC passes (`dump1090.c` 1769-1771).
  On `modes1.bin` this rule causes no misses (none of the 23 misses is "skipped: inside our message").

## #13: Supplementary golden files from the padded recording

- **Date:** 2026-10-12
- **Status:** Draft, pending approval
- **Decision:** Keep the approved golden files (#4, #5) unchanged and compare against them only within the part dump1090
  decoded: samples 0-262,143. Add four supplementary files, `tests/golden/modes1_padded_{raw,decoded}_{nofix,default}.txt`,
  from the same pinned dump1090 run on `modes1.bin` padded with byte 127 to 786,432 bytes (3 full buffers), made by
  `scripts/make_padded_golden.sh`. They're used only to check the tail (samples 262,144 onward).
- **Why padding is needed:** dump1090 never decodes a file's last, partial 262,144-byte buffer (end-of-file race,
  `dump1090.c` 496-498 and 2986-2989). Byte 127 is the "no signal" value dump1090 itself pads a short buffer with (503-506).
- **Checked:** the padded outputs start with exactly the approved 217 lines in both modes, then add 66 (no-fix) or
  67 (default) tail messages. Each run was repeated with identical output and empty stderr.
- **Alternatives:** replace the approved files (changes the answer key that decision #8 was written against); ignore
  the tail (leaves 30% of the recording unchecked).
- **Limit:** there's no start-sample fixture for the tail, so tail lines are aligned with ours in order by hex. That's
  weaker evidence than the start-based matching used for the first 262,144 samples.

## #14: Preamble test tolerates energy in the samples beside a pulse

- **Date:** 2026-10-12
- **Status:** Draft, pending approval
- **Decision:** A preamble candidate needs:
  - each pulse louder than the quiet samples right beside it;
  - the quiet samples away from pulses (offsets 4, 5, 11-14) below 2/3 of the average pulse level;
  - the weakest pulse at or above `SIGNAL_FLOOR`.

  This replaces "every pulse louder than every quiet sample".
- **Why:** A signal that arrives between sample instants spreads each pulse into its neighbour, so testing those neighbours
  rejects real messages. This follows the dump1090 behavior already documented in `docs/pseudocode.md` stage 2 (`dump1090.c`
  1599-1650), written in our own form and not identical to it.
- **Measured:** no-fix misses unchanged at 23, default misses 21 → 20 (line 193's preamble is now found and repaired), still 0
  extras inside the region dump1090 decoded. All 194 exact-start golden messages remain candidates.
- **Alternatives:** keep the strict test (simpler, but contradicts the physical reason above for no measured gain).
