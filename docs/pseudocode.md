# Decoder pseudocode (Phase 3)

The plan for the from-scratch decoder in `src/decoder/`. This file contains no code, only
the algorithm in plain language, so it can be reviewed before Phase 4.

Read first: `docs/decoder-notes.md` (sample format), `docs/mode-s-primer.md` (fields, CRC),
`tests/golden/README.md` (the answer key).

Sources:
- **Riddle:** Junzi Sun, *The 1090 Megahertz Riddle*, https://mode-s.org/1090mhz/. The chapters used
  are *Introduction* (preamble, PPM, format lengths), *Mode S basics* (address parity), *ADS-B basics*,
  *Error control* and *All-call reply*.
- **dump1090:** `dump1090.c` at the pinned commit `efe64db3c6ba1520291331628a33c1e208e851a6`
  (decision #5). Line numbers below refer to that commit. dump1090 is cited as the answer key's
  behavior, and its code is not copied.

Every stage is traced by hand on the same real message, the **first line of both golden raw files**:

```
*8f4d2023587f345e35837e2218b2;
```

It begins at **sample 794** of `modes1.bin` (byte offset 1,588, 0.397 ms into the recording). I found
that position by matching the message's known bits against the recording in a throwaway script, which is not
decoder code.

---

## What's in the golden files

Both `modes1_raw_nofix.txt` and `modes1_raw_default.txt` have 217 messages, all from one aircraft,
ICAO `4d2023`. Counts per downlink format (identical in both files):

| DF | Name (Riddle) | Bits | Count | How its CRC is checked |
|----|---------------|------|-------|------------------------|
| 17 | ADS-B extended squitter | 112 | 120 | remainder must be 0 |
| 11 | All-call reply | 56 | 63 | remainder is 0 or an interrogator ID (43 + 20) |
| 0  | Short air-air surveillance (ACAS) | 56 | 10 | address parity |
| 5  | Surveillance, identity reply | 56 | 8 | address parity |
| 20 | Comm-B, altitude reply | 112 | 8 | address parity |
| 21 | Comm-B, identity reply | 112 | 5 | address parity |
| 4  | Surveillance, altitude reply | 56 | 3 | address parity |

The DF17 frames break down by type code as follows: TC 11 (airborne position, baro altitude) 59, TC 19 (velocity) 54,
TC 4 (identification) 7.

**What the decoder must handle first:** DF17 and DF11, which are 183 of 217 messages and are covered by the primer.
Next come DF0/4/5/20/21, which are 34 messages. To accept them, the decoder only needs the
address-parity check (stage 4), not their field layouts. Decoding their fields (altitude, squawk,
Comm-B) is optional and can come after the match.

---

## Stage 1: Samples to magnitude

**Input:** the file's bytes as unsigned 8-bit integers. There are 2N bytes, interleaved as I, Q, I, Q, ...
**Output:** `mag[0..N-1]`, one non-negative number per sample. The sample index `s` is time:
`t = s × 0.5 µs`.

```
read the whole file as an array of uint8 bytes
if the byte count is odd: drop the last byte (a half sample) and warn
I = bytes at even positions, as signed numbers, minus 127
Q = bytes at odd positions,  as signed numbers, minus 127
mag = sqrt(I*I + Q*Q)                  # whole-array operation, no loop
return mag                              # float; length N = bytes / 2
```

Notes:
- The center value 127 is what dump1090 uses (`decoder-notes.md`, `dump1090.c` 1462-1463).
- dump1090 scales the magnitude by 360 and stores it as a 16-bit integer (359-363). Only the comparisons
  between magnitudes matter, so a float with no scaling is enough. Thresholds in later stages must then
  be expressed in these units, not dump1090's.

**Trace (sample 794):** the raw bytes are `102, 134`, so I' = 102 - 127 = -25 and Q' = 134 - 127 = 7.
That gives mag = sqrt(625 + 49) = sqrt(674) ≈ **26.0**. For comparison, the median magnitude of the whole file
(the background noise level) is 3.0.

**Golden check:** indirect only. No golden file contains magnitudes. Unit tests use hand-computed
pairs, for example `(127,127) → 0`, `(102,134) → 26.0`, and an odd-length file. The real check is stage 3.

**Interview points:**
- What I/Q samples are.
- Why the magnitude ignores phase: Mode S is pulse-position modulation, so only *when* power arrives
  matters, not its phase.
- Why 2 MHz means 0.5 µs per sample.
- Why the bytes are centered on 127.

---

## Stage 2: Preamble detection

**Input:** `mag[]`. **Output:** a list of candidate start sample indices `j`, where the preamble
begins at `j` and the data begins at `j + 16`.

The Riddle (*Introduction*) describes an 8 µs fixed preamble written as `1010000101000000` in half-microsecond
chips. Each chip is one sample at 2 MHz, so the pulses are at sample offsets **0, 2, 7, 9**, which is
0, 1.0, 3.5 and 4.5 µs. That matches dump1090's comment at 1570-1580.

```
for each sample index j from 0 to N - (16 + 224):
    high = mag[j], mag[j+2], mag[j+7], mag[j+9]          # the 4 pulses
    low  = mag[j+1], mag[j+3], mag[j+4], mag[j+5],
           mag[j+6], mag[j+8]                            # gaps between pulses
    quiet = mag[j+10 .. j+15]                            # end of preamble, before data
    if min(high) <= max(low):           skip            # pulses must stand out
    if min(high) <= max(quiet):         skip
    if min(high) < SIGNAL_FLOOR:        skip            # ignore noise; value tuned in Phase 4
    add j to candidates
return candidates
```

This is a deliberately simple, strict check written from the Riddle's description. dump1090's test is
**looser** in a specific way (1599-1650):
- It checks that each pulse is higher than its immediate neighbors (the first 10 samples, 1602-1611).
- It only requires the gap samples 4, 5 and 11-14 to be below 2/3 of the average pulse level (1624-1642).
- It deliberately doesn't test the samples right next to a pulse, because when the signal is out of phase with the
  sampling, part of a pulse's energy spills into the neighboring sample (comment at 1620-1623).

My check tests those neighbors too (offsets 1, 3, 6, 8, 10 and 15), so it **may reject out-of-phase messages that dump1090
keeps**. That's the first suspect for any missing messages in Phase 4. The likely fix is to stop testing pulse-adjacent
samples, for the physical reason above. Where the two disagree, the result shows up as missing or extra messages,
and decision #8 says how those get explained.
**Phase 4 outcome:** the decoder now uses that looser, pulse-neighbour test (decision #14; `docs/decoder-notes.md` stage 2).
It recovered one preamble (golden line 193) and no other misses.
`SIGNAL_FLOOR` is an open parameter: the first try is a few times the median magnitude (3.0 on this file), measured
in Phase 4 rather than guessed here. Candidates may overlap, and stage 3 decides which are real.

**Trace (j = 794):** pulse magnitudes at offsets 0, 2, 7, 9 are **26.0, 27.0, 26.7, 28.0**, so min(high) = 26.0.
The gap magnitudes at offsets 1, 3, 4, 5, 6, 8 are 7.2, 0.0, 2.0, 2.8, 10.0, 7.2, so max(low) = 10.0. The quiet
zone (offsets 10-15) is 1.4, 1.4, 1.4, 2.0, 3.0, 8.5, so its max is 8.5. Since 26.0 > 10.0, 26.0 > 8.5 and 26.0 > 3 × 3.0,
**794 is a candidate.**

**Golden check:**
- Each of the 217 golden messages starts at a known sample, which can be found by matching its known
  bits, as for 794 above.
- Phase 4 commits that small list (217 numbers) as a fixture, `tests/golden/modes1_starts.txt`,
  generated by a script that uses only the golden hex and the recording.
- Test: every fixture start must be in `candidates`.
- The number of candidates that don't become messages gets reported, not failed. dump1090 itself reports
  415 valid preambles for 217 messages.

**Interview points:**
- Why a fixed preamble exists (sync and "a message starts here").
- Why it's tested relative to its own gaps instead of an absolute level (signal strength varies by distance).
- The trade-off between missing weak messages and accepting noise.

---

## Stage 3: Pulses to bits (and frame length)

**Input:** `mag[]` and a candidate `j`. **Output:** a message as a bit string or bytes, of length 56 or 112,
or "rejected".

Riddle (*Introduction*), on pulse-position modulation: a `1` is "a 0.5 μs of pulse followed by a
0.5 μs flat signal", and a `0` is the reverse. One bit is sent per microsecond. Bit `k` therefore lives in
samples `j+16+2k` (first half) and `j+17+2k` (second half).

```
bits = empty list; ties = 0
for k from 0 to 111:                         # always read 112; decide length afterwards
    first  = mag[j + 16 + 2k]
    second = mag[j + 17 + 2k]
    if first > second:   append 1
    elif first < second: append 0
    else:                append 0; if k < 56: ties += 1   # equal halves: no information
df = value of bits[0..4]
length = 112 if 16 <= df <= 21 else 56       # dump1090 rule, see below
if ties > 0: reject                          # an unreadable bit inside the short part
return first `length` bits, packed 8 per byte, as hex
```

**The frame-length rule.** dump1090 `modesMessageLenByType` (746-753) returns 112 bits for DF 16, 17, 18,
19, 20 and 21, and 56 bits for every other DF. The demodulator always reads 112 bits' worth of samples
first (1666-1669) and then picks the length from the first 5 bits (1708-1709). All 217 golden messages
agree with this rule.

**Disagreement (DF 24):** The Riddle (*Introduction*) says format 24 "is identified using only the
first two bits, which must be `11`" and lists it as 112 bits (Comm-D, ELM). dump1090's rule would treat any
`11xxx` frame as 56 bits. There are no DF 24 frames in `modes1.bin`, so Phase 4 follows dump1090 to match the
answer key. Handling DF 24 per the Riddle is a known later change.

**Known divergence sources** from dump1090. These aren't in the Riddle. They're listed here and their effect is
measured in Phase 4 under decision #8:
- **"Hold the previous bit."** If the two halves are very close, dump1090 repeats the previous bit instead of
  comparing (1675-1676).
- **Average-contrast filter.** It drops a frame whose average half-to-half contrast is too low (1711-1726).
- **Phase-correction retry.** If a frame fails, it adjusts the samples and re-reads the same frame once (1654-1663, 1785-1790).

**Trace (j = 794):** the data starts at sample 810.

| bit k | samples | first | second | bit |
|---|---|---|---|---|
| 0 | 810, 811 | 30.0 | 3.6 | 1 |
| 1 | 812, 813 | 10.0 | 25.3 | 0 |
| 2 | 814, 815 | 8.1 | 26.2 | 0 |
| 3 | 816, 817 | 5.1 | 40.8 | 0 |
| 4 | 818, 819 | 25.5 | 7.2 | 1 |
| 5-7 | 820-825 | 24.2, 25.0, 28.0 | 10.2, 8.5, 4.5 | 1, 1, 1 |

The first byte is `10001111` = `0x8f`. DF = `10001` = 17, which is in 16..21, so the length is **112**. All 112 bits
reproduce `8f4d2023587f345e35837e2218b2`.

**Golden check:**
- Run stages 1-3 at every fixture start and compare the hex with the golden line, expecting 217/217.
- Then run the full detector on the whole file and compare the *set* of messages that pass stage 4 with
  `modes1_raw_nofix.txt`, as decision #8 describes.

**Interview points:**
- PPM: why comparing the two halves is better than comparing either one against a fixed threshold.
- Why the decoder reads 112 bits before knowing the length.
- How the DF picks the length.
- What the DF 24 disagreement is.

---

## Stage 4: CRC check

**Input:** a 56- or 112-bit message, plus the "recently seen" list and the current sample index.
**Output:** `accepted` or `rejected`. If accepted, also the ICAO address and, for DF 11, the interrogator ID.

The CRC (Riddle, *Error control*; primer section 4): divide the whole message by the generator `0x1FFF409`
using XOR, and keep the 24-bit remainder. For DF 17, the transmitter sets the parity so that the remainder
of an intact frame is 0.

```
r = crc_remainder(all bits of the message)                 # 24-bit number
df = first 5 bits

if df in {17, 18}:
    if r != 0: reject                                     # no-fix; repair comes later (4c)
    icao = bits 9-32;   add_recent(icao, now)             # clean frame: remember it
    accept
elif df == 11:
    icao = bits 9-32
    if r == 0:  add_recent(icao, now); accept (iid = 0)
    elif r < 80 and seen_recently(icao, now): accept (iid = r)   # NOT added to list
    else: reject
elif df in {0, 4, 5, 16, 20, 21, 24}:                     # address/parity formats
    icao = r                                              # remainder IS the address
    if seen_recently(icao, now): accept else reject
else:
    reject                                                # unknown format
```

### 4a. Address parity (DF 0/4/5/16/20/21/24)

The Riddle (*Mode S basics*, Parity) says "Address Parity is generated by overlaying the normal CRC remainder
with the 24-bit transponder ICAO address". The parity field is (CRC of the data) XOR (address). So the remainder
of the whole frame (data plus parity) comes out as the address itself. There's no way to check such a frame on its own;
it can only be accepted if that address is already known. dump1090 does exactly this (`bruteForceAP`, 942-983,
for the DFs listed at 947-953, called at 1183-1192).

### 4b. The DF 11 interrogator-ID rule

In an all-call reply the parity is overlaid with the interrogator ID instead, so a clean DF 11
frame's remainder *is* the interrogator ID. It's 0 for a spontaneous reply (Riddle, *All-call reply*; primer section 4).
dump1090 adds its own acceptance condition (1202-1209): a DF 11 frame with a nonzero remainder is accepted only if the
remainder is **below 80** and the frame's ICAO address is **recently seen**. The remainder then becomes the
interrogator ID. Why the cut-off is 80 is not explained in the source. I haven't found it in the Riddle either,
so it is treated as dump1090's choice, not a protocol fact.

### 4c. The "recently seen" list

**What adds an address** (dump1090 1197-1200): only DF 11, 17 or 18 frames whose CRC remainder was 0
*with no bit repaired*. A DF 11 accepted through an interrogator ID doesn't add its address, because it wasn't clean.
Neither does an address-parity frame, which can only be accepted *because* the address was already listed.

**How "recently" is defined for offline replay.** dump1090 timestamps each entry with the computer's wall
clock and allows 60 seconds (66, 910-924). Options for this decoder:

| Option | Rule | Reproduces golden no-fix? | Live use later |
|---|---|---|---|
| A | seen anywhere earlier in this run, never expires | yes | grows stale: an address stays trusted forever |
| **B (chosen, decision #7)** | seen within the last **60 s of recording time**, where `now = sample index / 2,000,000` | **yes** | correct: same 60 s window, and the clock is the sample stream |
| C | dump1090's wall clock | yes on a fast machine | tests would depend on machine speed, so rejected |

**Why A and B both reproduce the no-fix golden output:** `modes1.bin` is 0.178 s long, so no entry can
expire under B. dump1090 reads the whole file in well under 60 wall-clock seconds, so none expired there either.
On this file all three rules collapse to "seen earlier in the file".

**Evidence so far:** I replayed `modes1_raw_nofix.txt` in order, adding an address from each clean DF 11/17/18 line.
- All **20** DF 11 interrogator-ID frames come after `4d2023` was added.
- All **34** address-parity frames resolve to `4d2023` and come after it was added.
- The rule therefore explains all 54 list-dependent messages, with zero exceptions.

That shows the rule accepts everything dump1090 accepted, not that it rejects everything dump1090 rejected.
The file has one aircraft, whose first frame is a clean DF 17, so it barely exercises the list. **Phase 4 verification:**
1. The decoder's no-fix message set must equal the golden file.
2. With the list disabled, exactly those 54 messages must disappear, and nothing else.

**Default run (fix on) versus no-fix.** dump1090 repaired 6 frames in the default run. A repaired frame doesn't add
its address to the list (1197-1200). `scripts/golden_stats.py` partitions both files exactly and lists the 6 frames. They
split into two kinds:

| Golden line | DF | Repaired bit | Start sample | No-fix hex, remainder | Default hex | List source? no-fix / default |
|---|---|---|---|---|---|---|
| 112 | 17 | 66 | 123821 | same, `000000` | same | yes / no |
| 185 | 17 | 61 | 222008 | same, `000000` | same | yes / no |
| 188 | 17 | 99 | 229407 | same, `000000` | same | yes / no |
| 193 | 11 | 5 | 231307 | same, `000000` | same | yes / no |
| 128 | 11 | 55 | about 144765 | `5d4d20237a55a7`, `000001` | `5d4d20237a55a6` | no / no |
| 174 | 11 | 55 | about 198770 | `5d4d20237a55a7`, `000001` | `5d4d20237a55a6` | no / no |

- **Same hex in both files (4 frames).** In the default run, the first reading had one wrong bit, which was repaired. In
  the no-fix run the same frame came out clean. At 222008, 229407 and 231307, a plain half-versus-half comparison gets exactly
  the repaired bit wrong and nothing else, so the no-fix run must have re-read those samples differently. That fits the
  phase-correction retry (1785-1790), but I haven't traced it inside dump1090. These 4 frames are list sources in the
  no-fix run only.
- **Different hex (2 DF 11 frames).** The no-fix remainder is 1. One is a power of two, and **1 is exactly the remainder a single
  flipped last parity bit (bit 55) produces**. dump1090 tries repair *before* the interrogator-ID rule (1112-1127 run before
  1202-1209). So with the fix on, it flips bit 55 and gets remainder 0; with `--no-fix` it reads interrogator ID 1. Below 80, the
  remainders that collide like this are exactly 1, 2, 4, 8, 16, 32 and 64 (bits 55 down to 49 of the parity field). Every other
  interrogator-ID frame in this file has remainder **60**, which collides with nothing, so those 18 are read the same
  way in both runs. Which reading of the two remainder-1 frames is true can't be decided from the bits. All the
  others saying 60 hints at a bit error, and at line 128's best alignment the plain comparison reads bit 55 as 0, but
  neither is proof. Neither run adds these two to the list.

This makes no difference on this file, because `4d2023` was already listed (159 clean list sources in the default run versus
163 in no-fix). On a busier recording it could: an aircraft seen only in repaired frames would never be listed, so its DF 4/5/20/21
replies would be dropped.

**What Phase 4 must do to match the default file** (step 10 below):
1. Add single-bit repair for DF 11/17/18 only, and run it **before** the DF 11 interrogator-ID rule. Repair only when the
   remainder equals the remainder of exactly one flipped bit. Never repair the first 5 bits of a 112-bit frame (806).
   - For 56-bit frames, dump1090 reuses its 112-bit table shifted by 56 bits (874-880). As I read it, that leaves a short frame's
     first 5 bits repairable. This is unverified; Phase 4 pins it down with a unit test.
2. A repaired frame is accepted and output with the repaired hex, but **doesn't add its address** to the list.
3. Bit-level check (100%): applying the repair to the 217 no-fix golden lines changes exactly lines 128 and 174, and the
   result equals `modes1_raw_default.txt` byte for byte. `scripts/golden_stats.py` already shows this.
4. The other 4 repaired frames have the same hex in both files, so they only test the demodulator. If our demodulator reads one
   bit wrong, the repair recovers it; if it reads it right, no repair is needed. Either way the output line matches.

**Trace:**
- `8f4d2023587f345e35837e2218b2` (DF 17): remainder **000000**, so it's accepted. `4d2023` is added at
  t = 794 / 2,000,000 = 0.000397 s.
- `5d4d20237a55a7` (DF 11, no-fix file): remainder **000001**. That's below 80 and `4d2023` is listed, so it's accepted
  with interrogator ID 1. It isn't added to the list.
- `20000f1f684a6c` (DF 4): the CRC of the data part is `256a4f`, and `256a4f` XOR the parity `684a6c` = **4d2023**.
  That's the remainder of the whole frame, it's listed, so the frame is accepted with address 4d2023.

**Golden check (100% expected):** run stage 4 on all 217 golden hex lines in file order. Expect 120 DF 17 with remainder 0,
43 clean DF 11, 20 DF 11 with an interrogator ID between 1 and 79, and 34 address-parity frames resolving to `4d2023`.
Every line must be accepted. Unit tests also feed known-bad frames, which must be rejected.

**Interview points:**
- What a CRC remainder is.
- Why DF 17 can be checked on its own but DF 4/5/20/21 can't.
- What the interrogator ID is.
- Why the list is filled only from clean frames, so a mistake can't be trusted and then trust others.
- Why recording time beats the wall clock for tests.

---

## Stage 5: Routing by message type

**Input:** an accepted message. **Output:** the message tagged with its kind, ready for field decoding.

```
df = first 5 bits
if df == 17 or df == 18:
    tc = ME bits 1-5 (message bits 33-37)
    kind = identification   if 1 <= tc <= 4
           surface position if 5 <= tc <= 8
           airborne position (baro)  if 9 <= tc <= 18
           velocity         if tc == 19
           airborne position (GNSS)  if 20 <= tc <= 22
           other ADS-B      otherwise               # status etc. (primer section 9)
elif df == 11:              kind = all-call reply
elif df in {4, 20}:         kind = altitude reply
elif df in {5, 21}:         kind = identity reply
elif df == 0:               kind = short air-air surveillance
else:                       kind = unhandled
return (kind, df, tc or none)
```

Type-code ranges come from the primer's TC table (Riddle, *ADS-B basics*).

**Trace:** `8f4d2023587f345e35837e2218b2`. The first byte `8f` gives DF 17. The ME is `587f345e35837e`, and its first byte `58` = `01011000`,
so TC = `01011` = **11**, an airborne position with barometric altitude.

**Golden check (100% expected):** route all 217 lines. The counts must equal the table at the top: DF 17 split
59 / 54 / 7 by TC 11 / 19 / 4, DF 11 63, DF 0 10, DF 5 8, DF 20 8, DF 21 5, DF 4 3. Then compare per message against the
`DF` and `Extended Squitter Type` lines in `modes1_decoded_nofix.txt`.

**Interview points:**
- DF answers "which protocol"; TC answers "which ADS-B message".
- Why routing comes after the CRC check (don't spend effort on garbage).

---

## Stage 6: Output fields

**Input:** a routed message. **Output:** (a) the raw line, and (b) a small dict of decoded fields.

```
raw_line = "*" + lowercase hex of the message bits + ";"      # same as dump1090 --raw
fields = { df, icao }
if df == 17:
    fields.ca = bits 6-8
    tc 1-4:  fields.callsign  (primer section 3)
    tc 9-18: fields.altitude_ft (Q bit = 1 only for now), fields.cpr_odd, cpr_lat, cpr_lon
    tc 19:   fields.subtype, speed, track or heading, vertical_rate (primer section 6)
if df == 11: fields.ca = bits 6-8; fields.iid = from stage 4
if df in {0, 4, 5, 20, 21}: fields.icao = from stage 4 (address parity)
return raw_line, fields
```

Positions (latitude and longitude) are *not* an output of this stage, because they need two frames or a reference (primer section 5).
They belong to a later tracking step. dump1090's single-message output also prints them as "not decoded".

**Trace:** `8f4d2023587f345e35837e2218b2`.
- **Raw line:** `*8f4d2023587f345e35837e2218b2;`.
- **CA** = `111` = 7.
- **ICAO** = `4d2023`.
- **TC 11:** the ME bits are `01011000 01111111 00110100 ...`.
  - ALT = ME bits 9-20 = `011111110011`. The 8th bit (Q) is 1; dropping it leaves `01111110011` = 1011.
    1011 × 25 - 1000 = **24275 ft**.
  - T = ME bit 21 = 0, and F = ME bit 22 = 1, so the frame is **odd**.
- The golden decoded file shows `Altitude : 24275 feet`, `F flag : odd`, `T flag : non-UTC`, and
  `Latitude : 12058`, `Longitude: 99198 (not decoded)`.

**Golden check:**
- (a) **Raw lines:** the list of raw lines must equal `modes1_raw_nofix.txt` byte for byte (100% on the
  golden hex: feed the golden lines back in and reproduce them exactly).
- (b) **Decoded fields:** compare DF, ICAO, CA, TC, altitude, F flag and CPR lat/lon against `modes1_decoded_nofix.txt`.
  That file is human-readable text, so Phase 4 needs a small parser in `tests/` that extracts just those
  fields. Callsign and velocity fields are compared against pyModeS as well.

**Interview points:**
- Why the raw hex is the most robust thing to compare.
- Which fields can be decoded from one message and which need state (CPR).
- The Q bit.

---

## Stage 3c (proposed, step a1): CRC-assisted soft-decision bit flipping

*Status: pseudocode for review. Not built.* This is a response to the 23 no-fix misses at checkpoint B
(`docs/phase4-golden-report.md`). Every number below was measured on the **first 217 golden lines only**. The 66/67
tail lines (decision #13) are a holdout and weren't used.

**Idea.** Stage 3 makes a hard 1/0 decision for each bit, but some decisions are close. When a frame fails its CRC,
the bits most likely to be wrong are the ones whose two halves were nearly equal. So try flipping a few of those bits
and keep a result only if the CRC then passes. The CRC acts as the referee; the confidence decides what to try first.

**Input:** `mag[]`, a start sample `j`, the hard bits from stage 3 (already cut to the DF's length), the recently-seen
list, and time `t`. **Output:** an accepted, corrected frame, or "rejected".

```
only for frames whose DF (as read) is 11, 17 or 18 and whose CRC remainder is not 0
    (and, with repair on, that ordinary single-bit repair didn't fix)
for each bit k from 5 to n-1:                          # never bits 0-4, the DF (decision #9)
    confidence[k] = |mag[j+16+2k] - mag[j+17+2k]|      # how clearly the two halves differ
weak = the K bits with the lowest confidence           # K = 10
try flip sets in this order: every single bit in weak, then every pair, then every triple
    (m = 3 at most; ties broken by smaller total confidence first)
    -> at most C(10,1) + C(10,2) + C(10,3) = 175 candidates per frame
for each candidate:
    if crc_remainder(candidate) != 0: continue         # remainder must be exactly 0:
                                                       # no interrogator-ID reading for a flipped frame
    icao = candidate bits 8-31
    if not recent.seen(icao, t): continue              # only aircraft that already proved themselves
    collect candidate
if exactly one candidate was collected: accept it (how = "soft decision", flipped bits recorded);
    it does NOT add its address to the recently-seen list (like a repaired frame)
else: reject                                           # none, or ambiguous: two corrections both pass
```

**What it can recover on the first 217 lines.** For each miss, I ranked its wrong bits among bits 5 onward from least
to most confident at the fixture start. Absolute and relative (`|a-b|/(a+b)`) confidence gave the same ranking.

| K (weakest bits) | m (max flips) | Candidates per frame | Recoverable no-fix misses |
|---|---|---|---|
| 8 | 2 | 36 | 3: 185, 188, 193 |
| 8 | 3 | 92 | 4: + 112 |
| **10** | **3** | **175** | **5: 71, 112, 185, 188, 193** |
| 10 | 4 | 385 | 6: + 209 |
| 16 | 4 | 2,516 | 6 (no further gain) |

I'm proposing **K = 10, m = 3**. Going to m = 4 recovers one more line at 2.2 times the candidates. The other 18 misses are out of reach of
flipping:
- 9 of them (27, 52, 69, 128, 156, 174, 178, 207, 212) have a wrong bit inside the DF field, so they're read as a
  different DF and never reach this step.
- The other 9 (35, 49, 75, 78, 80, 84, 111, 157, 209) have 4 to 14 wrong bits, some of them outside the 10 least-confident.

**Expected result:** no-fix 23 → **about 18** missing; default 20 → **about 18** (185, 188 and 193 are already recovered
there by ordinary repair). **Either way that's still above 10, so (a2) would be needed.** These are predictions from bits at the fixture
starts, not a measured run.

**False accepts.** A wrong candidate passes the CRC by chance with probability about 2^-24 ≈ 6 × 10^-8. On the first
262,144 samples, the pipeline produces **17** CRC-failing DF 11/17/18 frames, so at 175 candidates each:
17 × 175 × 2^-24 ≈ **1.8 × 10^-4 expected false accepts** for this part of the recording (1 in about 5,600 runs).
- **Two things make it smaller:** the recently-seen check, and rejecting the frame when two different corrections both pass.
- **Two things make it unsafe to scale up:**
  - The flips leave the address bits mostly untouched, so the recently-seen check is *not* an independent factor I can multiply in.
  - Live traffic has many aircraft and far more failing frames. Count failing frames per second on my own recordings
    before trusting this rate.
- **For comparison:** dump1090's interrogator-ID rule accepts any remainder below 80. That's 80 times more permissive per frame, which is why flipped
  DF 11 frames here must reach remainder exactly 0.

**The DF field (line 212) and decision #9.** I propose this step **does not flip bits 0-4**, consistent with decision #9.
A wrong DF bit also means a wrong length. Line 212's frame (true DF 17) reads as DF 25, gets cut to 56 bits, and never
reaches this step. Allowing it would mean a different design: re-read the frame under each "DF one flip away from
11/17/18" hypothesis at that DF's length, then run the CRC. That would be a DF-specific exception to decision #9, so it needs
its own decision. Cost of not doing it: line 212 and line 128 (which also has a wrong DF bit) stay as misses.

**An open question for you: `--no-fix`.** In dump1090, `--no-fix` turns off CRC-based correction. Its no-fix golden file
still contains frames it recovered by *re-demodulating* (phase correction), but none recovered by flipping bits until the
CRC passes. This step is CRC-based correction, so:
- **(i)** if it runs only with fix on, the no-fix miss count doesn't move (23), and only default improves;
- **(ii)** if it also runs under `--no-fix`, our "no-fix" means something different from dump1090's.

I lean towards (i). It keeps `--no-fix` honest, and leaves the no-fix target to (a2), which is a demodulation change and so fits.

**Golden check:**
- Bit-level: no-fix golden lines and default golden lines must pass through unchanged, because they're already clean.
- Unit tests:
  - a golden frame with 1, 2 or 3 of its weakest bits inverted is recovered;
  - a frame with an unlisted address is not;
  - an ambiguous double pass is rejected;
  - bits 0-4 are never flipped.
- Whole file: re-run `scripts/compare_golden.py` in both modes, still with **0 extras** inside the decoded region. Report
  the holdout tail separately.

**Interview points:**
- Soft versus hard decisions.
- Why the CRC can referee a guess.
- Why the number of guesses directly scales the false-accept rate.
- Why "exactly one passing correction" matters.

---

## Phase 4: order of work and testing plan

Build **from the bits inward first**. The golden hex lets stages 4-6 be finished and verified before any
signal processing exists.

1. **Hex utilities and CRC** (stage 4 without the list): remainder function, unit tests from the primer, then all
   217 golden lines.
2. **Frame length and routing** (stages 3b and 5): DF to length, DF/TC to kind. Test on golden lines; counts must match exactly.
3. **Recently-seen list and DF 11 / address-parity acceptance** (stage 4 complete). Test by replaying the golden lines.
   All 217 must be accepted, and with the list disabled exactly 54 must be rejected.
4. **Output fields** (stage 6). Raw lines round-trip byte for byte. Decoded fields are compared against the parsed
   `modes1_decoded_nofix.txt`.
5. **Samples to magnitude** (stage 1). Unit tests on hand-computed byte pairs.
6. **Fixture of message start samples.** A small script in `scripts/` matches each golden hex line against the recording
   (as done for sample 794) and writes `tests/golden/modes1_starts.txt`. It's tiny, so it gets committed.
7. **Bits at known starts** (stage 3a). 217/217 hex must match at the fixture starts.
8. **Preamble detection** (stage 2). Every fixture start must be a candidate.
9. **Whole-file run.** Compare against `modes1_raw_nofix.txt` and report counts of matched, missing (in golden, not
   in ours) and extra (in ours, not in golden). Extra must be zero, and every miss must be explained (decision #8).
   Expected: up to 4 misses (golden lines 112, 185, 188, 193) until a phase-correction retry exists. They count toward the
   10-message limit and each needs its written explanation.
10. **Later:** single-bit repair before the DF 11 interrogator-ID rule (stage 4c, "What Phase 4 must do"). First, the bit-level
    test: the 217 no-fix golden lines plus repair must equal `modes1_raw_default.txt`. Then the whole-file run against the default file.
    Repair should recover lines 185, 188 and 193 (one wrong bit each under plain comparison). Line 112 has three wrong bits under
    plain comparison (66, 85, 110), so repair alone recovers it only if the demodulator reads 85 and 110 correctly. Otherwise it stays
    a documented miss.

Each step is one small function with its own tests (CLAUDE.md). All tests run from `pytest`, and no test imports dump1090.
pyModeS appears only in tests.

## Python or C

Recommendation: **Python 3 with NumPy** for Phase 4. A C port of the demodulator (stages 1-3) is an optional
stretch idea for later, not part of Phase 4. See decision #6 for the comparison.

## Open questions

- `SIGNAL_FLOOR` in stage 2: measured in Phase 4, not guessed.
- DF 24 length: the Riddle and dump1090 disagree. Phase 4 follows dump1090; it doesn't matter for `modes1.bin`.
- Why dump1090 uses 80 as the DF 11 interrogator-ID cut-off is not documented in its source. I'm treating it as a dump1090
  choice that the decoder reproduces in order to match.
