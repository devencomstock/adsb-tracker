# Decoder notes

> The DF17 field-by-field reference (frame layout, type codes, identification, CRC, position, velocity) lives in [mode-s-primer.md](mode-s-primer.md).

Plain-English notes for each decoder stage, written so I can follow and explain them.
Primary source: Junzi Sun, *The 1090 Megahertz Riddle*, https://mode-s.org/1090mhz/.
pyModeS and dump1090 are answer keys only.

---

## Worked example: hand-decoding `8D4840D6202CC371C32CE0576098`

This is the worked aircraft-identification example from *The 1090 Megahertz Riddle*.

### 1. Length and layout

28 hex characters × 4 bits = **112 bits**, so this is a long message. A 112-bit
ADS-B (extended squitter) message is laid out like this:

| Bits    | Field | Size    | Hex here         |
|---------|-------|---------|------------------|
| 1-5     | DF    | 5 bits  | from `8D`        |
| 6-8     | CA    | 3 bits  | from `8D`        |
| 9-32    | ICAO  | 24 bits | `4840D6`         |
| 33-88   | ME    | 56 bits | `202CC371C32CE0` |
| 89-112  | PI    | 24 bits | `576098`         |

### 2. Downlink format (message type)

The first byte is `8D` = `1000 1101` in binary.

- The first 5 bits, `10001`, are **DF = 17**. DF17 is an ADS-B extended squitter, which the aircraft broadcasts itself.
- The next 3 bits, `101`, are **CA = 5**, the transponder capability field.

### 3. ICAO address

Bits 9-32 are the next 6 hex characters: **`4840D6`**. This is the aircraft's unique 24-bit
address. It's assigned per airframe, not per flight, and is what we'll join against the registry.

### 4. Type code (what the ME field contains)

ME = `202CC371C32CE0`. Its first byte is `20` = `0010 0000`.

- The first 5 bits, `00100`, are **TC = 4**. Type codes 1-4 are **aircraft identification**, so this message
  carries a callsign.
- The next 3 bits, `000`, are **CAT = 0**. Together with TC 4 this means "no category information".

### 5. Callsign

The remaining 48 bits of ME (`2CC371C32CE0`) hold **8 characters, 6 bits each**.

```
2C       C3       71       C3       2C       E0
00101100 11000011 01110001 11000011 00101100 11100000
```

Regrouped into 6-bit chunks:

| Chunk  | Value | Character |
|--------|-------|-----------|
| 001011 | 11    | K         |
| 001100 | 12    | L         |
| 001101 | 13    | M         |
| 110001 | 49    | 1         |
| 110000 | 48    | 0         |
| 110010 | 50    | 2         |
| 110011 | 51    | 3         |
| 100000 | 32    | (space)   |

Each value is an index into the ADS-B character table:

```
#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######
```

Index 1-26 are A-Z, 32 is a space, and 48-57 are 0-9 (`#` = unused). This gives `KLM1023 `,
which is **KLM1023** with the trailing space trimmed.

### 6. Parity

PI = `576098` is a 24-bit CRC over the first 88 bits. Checking it is the CRC stage below; for now,
pyModeS confirms it's valid.

### Result and confirmation

| Field     | Hand-decoded            |
|-----------|-------------------------|
| DF        | 17 (ADS-B)              |
| ICAO      | 4840D6                  |
| Type code | 4 (identification), CAT 0 |
| Callsign  | KLM1023                 |

`tests/test_hand_decode.py` confirms all of these with pyModeS 3.6.0
(`pyModeS.decode(msg)` returns `df=17, icao='4840D6', typecode=4, category=0,
callsign='KLM1023', crc_valid=True`).

---

## The test recording: `modes1.bin` sample format

Sources (all at antirez/dump1090 commit `efe64db3c6ba1520291331628a33c1e208e851a6`):
- `README.md` lines 69-72: the file must contain *"8-bit unsigned IQ samples at 2Mhz sample rate"*,
  for example as recorded by `rtl_sdr -f 1090000000 -s 2000000 -g 50 output.bin`.
- `dump1090.c` lines 1454-1468 (`computeMagnitudeVector`): how the bytes are actually read.
- `dump1090.c` lines 1570-1580: the comment on what one sample means in time.

In plain words:

- **No header.** The file is just raw bytes from start to end, with nothing describing it.
  `--ifile` passes the bytes straight to the demodulator (`readDataFromFile`, lines 460-500).
- **Each byte is one unsigned 8-bit number (0-255).** dump1090 treats **127** as zero
  (`p[j]-127`), so a byte of 127 means "no signal" on that channel, and 0 or 255 is the strongest.
- **Bytes come in pairs: I then Q.** Even bytes are I (in-phase) and odd bytes are Q (quadrature):
  `i = p[j]`, `q = p[j+1]`. One pair is one sample. The file starts `129 127 126 125 ...`, so the
  first sample is I=+2, Q=0 after subtracting 127: almost silence.
- **2 million samples per second (2 MHz)**, so **one sample = 0.5 µs**. The source comment says
  so directly: *"Since we are sampling at 2 Mhz every sample in our magnitude vector is 0.5 usec"*.
  A 0.5 µs Mode S pulse therefore spans about one sample.
- **Signal strength is the magnitude**, `sqrt(I² + Q²)`. dump1090 looks it up in a precomputed
  table scaled by 360 to fit a 16-bit integer (lines 359-363). The scaling is an implementation
  detail; what matters is "magnitude = distance of (I, Q) from the center".
- **Size check:** 713,736 bytes / 2 = 356,868 samples, which is 0.178 seconds of radio at 2 MHz.
  The byte count is even, so the file is a whole number of I/Q pairs.

`modes1.bin` lives in `data/` (gitignored). Its sha256 and source are recorded in
`tests/golden/README.md`.

---

## Decoder stages

To be filled in during Phases 1-4. The Phase 3 pseudocode, with a hand trace of a real message through each
stage, is in [pseudocode.md](pseudocode.md).

### 1. Samples to magnitude

Code: `src/decoder/samples.py`. Read the file's bytes, drop a trailing half sample if there is one, subtract 127
from every byte, and pair them up as (I, Q). Each pair's distance from the center, `sqrt(I² + Q²)`, is how much
radio energy arrived in that half microsecond. Phase is thrown away because Mode S only cares *when* a pulse
arrives. The whole file is converted at once with NumPy, with no Python loop. On `modes1.bin` the typical
(median) magnitude is 3.0 and real pulses are about 25 to 150.

### 2. Preamble detection

Code: `src/decoder/preamble.py`. A message begins with four pulses at sample offsets 0, 2, 7 and 9. Every other
sample up to offset 15 should be quiet. A start sample is a **candidate** if its weakest pulse is louder than its
loudest quiet sample, and at least `SIGNAL_FLOOR` (9.0, decision #10). This is stricter than dump1090, which
doesn't test the samples right next to a pulse. On this recording, all 194 golden messages with an exact start
pass it, and their weakest pulse is never below 24.4.

### 3. Pulses to bits

Code: `src/decoder/bits.py` and `src/decoder/pipeline.py`. After the preamble, each bit takes two samples. A pulse
in the first one means 1, in the second one 0, so the bit is "first sample louder than second". Read 112 bits, look
at the first 5 (the DF) to learn the real length, and keep that many. If any of the first 56 bits had two exactly
equal halves, the frame is dropped, because that bit carries no information. Candidates are tried in order. Once a
message is accepted, candidates that start inside it are skipped (decision #12).

**What this plain rule misses.** At 23 of the 217 golden messages, no start sample gives the golden bits with this
comparison (`tests/golden/modes1_starts.txt`, flag `approximate`). dump1090 decoded those with extra rules not in
the Riddle: chiefly a retry that adjusts the samples for a signal that arrives between two sample instants
("phase correction"). This is the open question at checkpoint B (`docs/phase4-golden-report.md`).

Already built at checkpoint A: the **frame length** (`src/decoder/frame.py`, `frame_length`). Once the first 5 bits
(the DF) are read, the DF alone says how long the frame is. DF 16 to 21 are 112 bits and everything else is 56, which is
dump1090's rule (`dump1090.c` 746-753). The Riddle says DF 24 is also long; we follow dump1090 here because it's the answer key.

### 4. CRC check

Code: `src/decoder/crc.py`, `src/decoder/recent.py`, `src/decoder/accept.py`.

**The remainder.** Treat the frame as one long binary number and divide it by a fixed 25-bit number (the generator
`0x1FFF409`), using XOR instead of subtraction. What's left is a 24-bit remainder. For an ADS-B frame (DF 17) the sender
chose the last 24 bits so that an intact frame leaves remainder 0. So "remainder 0" means "arrived intact".

**Three families of frames**, because the last 24 bits mean different things in different formats:
- **DF 11, 17, 18: plain parity.** Remainder 0 means intact. DF 17 can be checked entirely on its own.
- **DF 11 also carries an interrogator ID.** In an all-call reply, the parity is overlaid with the ID of the
  ground radar that asked, so an intact reply's remainder *is* that ID. In `modes1.bin` that's 60 for 18 replies.
  dump1090 accepts a nonzero remainder as an ID only if it's below 80 and the aircraft was seen recently.
- **DF 0, 4, 5, 16, 20, 21, 24: address parity.** The parity is overlaid with the aircraft's own ICAO address, so the
  remainder of an intact frame *is* the address. Such a frame can't prove itself; it's believed only if that
  address was recently seen in a clean frame.

**The recently-seen list.** An ICAO address goes on the list only from a DF 11/17/18 frame with remainder 0 that needed
no repair. Trust has to start from frames that proved themselves. An entry stays valid for 60 seconds of *recording*
time (sample index ÷ 2,000,000), not wall-clock time, so tests give the same answer on any machine (decision #7).

**Single-bit repair** (only with error correction on). Because the CRC is linear, flipping one bit always changes the
remainder by the same amount, whatever the rest of the message is. So each bit position has its own "fingerprint"
remainder. If a frame's remainder equals one bit's fingerprint, flip that bit back. The repaired frame is accepted but
doesn't go on the recently-seen list. Repair is tried before the interrogator-ID rule (that's dump1090's order). A
flipped bit in the parity field has a fingerprint that is a power of two (1, 2, 4, ... 64 below 80), so with repair on,
those remainders get repaired instead of being read as interrogator IDs. That's exactly why two golden lines differ
between the no-fix and default files. The first 5 bits are never repaired (decision #9).

**A known weak spot of the interrogator-ID rule.** In a DF 11, a flipped bit in the parity field changes the remainder by a power of two.
Two flipped bits there produce a small remainder such as 3, 5 or 6. If the remainder is below 80 and the address is on the
recently-seen list, the corrupted frame is accepted as an interrogator ID. That's dump1090's rule, and we copy it to match
the golden files. The list check is what limits the damage: the address must belong to an aircraft that recently sent a
frame that proved itself. `tests/unit/test_accept_rejects.py` shows this is the *only* way a two-bit error gets through.
Every two-bit error in a DF 17 is rejected, and no two-bit error ever looks clean or repairable.

**How it's checked** (`tests/test_golden_bitlevel.py`):
- All 217 no-fix golden lines are accepted: 163 clean, 20 by interrogator ID (18 × 60, 2 × 1) and 34 by address parity.
- With the list disabled, exactly 54 are rejected.
- With repair on, the no-fix lines become the default file byte for byte (only lines 128 and 174 change).

### 5. Message routing (by DF / type code)

Code: `src/decoder/routing.py`. After a frame is accepted, sort it by kind:
- **DF first:** DF 11 is an all-call reply, DF 4/20 altitude replies, DF 5/21 identity replies, DF 0 short air-air.
- **For ADS-B (DF 17/18), the type code next**, which is the first 5 bits of the 56-bit ME field: 1-4 identification,
  5-8 surface position, 9-18 airborne position with barometric altitude, 19 velocity, 20-22 airborne position with
  GNSS height, and anything else is "other".

Routing comes after the CRC check so that no effort goes into frames that are noise. Checked against the golden
counts (TC 11 = 59, TC 19 = 54, TC 4 = 7) and against the `DF` and `Extended Squitter Type` lines of the decoded
golden file, message by message.

### 6. Output fields
