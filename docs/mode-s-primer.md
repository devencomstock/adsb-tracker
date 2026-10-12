# Mode S / ADS-B primer (Phase 1)

Study notes for the decoder project, written in my own words from Junzi Sun's
*The 1090 Megahertz Riddle* (2nd ed., https://mode-s.org/1090mhz/). Chapter links
are in [Sources](#sources). Every number below was reproduced by running
`scripts/phase1_worked_examples.py`, and `tests/test_phase1_examples.py` checks the
script against pyModeS 3.6.0 (11 tests). Run `python scripts/phase1_worked_examples.py`
to see the steps print out.

This document starts *after* the signal has become bits. Samples to bits (magnitude,
preamble, pulses) is the decoder's job in Phase 4; see `docs/decoder-notes.md`.

## 1. The 30-second version

An ADS-B broadcast is a 112-bit frame on 1090 MHz. The first 5 bits (DF) say what kind of
frame it is, and `DF = 17` means an ADS-B message from a transponder. Next come 3 bits of
transponder capability, the 24-bit ICAO address that identifies the aircraft, a 56-bit
message (ME), and a 24-bit CRC remainder at the end. The first 5 bits of the ME are a type
code (TC) that says whether the message carries a callsign, a position, or a velocity. The
CRC lets a receiver detect corruption, and in the single-bit case it can locate and repair
the damaged bit. Positions are sent in a compact form (CPR) that needs either two frames
(one even, one odd) or one frame plus a nearby reference position to decode.

## 2. Frame layout

Bit numbers follow the book (1-indexed). The last column is the Python slice for a string
of `'0'`/`'1'` characters, which is what the decoder will work with.

| Field | Bits | Width | Meaning | Slice |
|---|---|---|---|---|
| DF | 1–5 | 5 | Downlink format (17 = ADS-B) | `bits[0:5]` |
| CA | 6–8 | 3 | Transponder capability | `bits[5:8]` |
| ICAO | 9–32 | 24 | Aircraft address | `bits[8:32]` |
| ME | 33–88 | 56 | Message | `bits[32:88]` |
| TC | 33–37 | 5 | First 5 bits of ME | `bits[32:37]` |
| PI | 89–112 | 24 | Parity (the CRC remainder in ADS-B) | `bits[88:112]` |

DF 18 is used instead of DF 17 for ADS-B and TIS-B from equipment that cannot be interrogated.
Short Mode S replies are 56 bits: the book says 4 of the 11 current downlink formats are
short and 7 are long. DF 11 (all-call reply) is one of the short ones: DF, CA, address, PI.

### Type codes (TC) in DF 17

| TC | Content |
|---|---|
| 1–4 | Aircraft identification and category |
| 5–8 | Surface position |
| 9–18 | Airborne position, barometric altitude |
| 19 | Airborne velocity |
| 20–22 | Airborne position, GNSS height |
| 28 | Aircraft status |
| 29 | Target state and status |
| 31 | Aircraft operation status |

CA is 5 for the Phase 0 example: a Level 2+ transponder that is airborne.

## 3. Worked example: identification

`8D4840D6202CC371C32CE0576098`

| Part | Hex | Result |
|---|---|---|
| DF, CA | `8D` = `10001 101` | DF 17, CA 5 |
| ICAO | `4840D6` | aircraft `4840D6` |
| ME | `202CC371C32CE0` | TC 4 = identification |
| PI | `576098` | the CRC remainder |

The ME bits split as `00100` (TC = 4), `000` (aircraft category, 0 = no category info),
then eight 6-bit characters. Their values are 11, 12, 13, 49, 48, 50, 51, 32. Each value
indexes this 64-entry table (`#` marks unused codes):

```
#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######
```

Indexes 1–26 are A–Z, 48–57 are 0–9, and 32 is a space. That gives `K L M 1 0 2 3 (space)`,
so the callsign is `KLM1023`. A callsign names a flight, not an aircraft: the same callsign
is reused by different aircraft on different days.

## 4. CRC and parity

**Idea.** Treat the frame as one long binary number and divide it by a fixed 25-bit
generator, `0x1FFF409` (`1111111111111010000001001`), using XOR instead of subtraction.
The 24-bit remainder is the CRC.

**ADS-B use.** The sender divides the first 88 bits followed by 24 zero bits and puts that
remainder in PI. The receiver divides all 112 bits: a remainder of 0 means the frame
arrived intact. The book notes that "parity", "checksum" and "CRC remainder" all mean this
same 24-bit remainder in the Mode S literature.

**Algorithm.** Walk from the first bit. Whenever the current bit is 1, XOR the generator
into the 25-bit window that starts there, then move on. After the last position with a full
window (bit index 87 for a 112-bit frame), the final 24 bits are the remainder. The book's
pseudocode is loose about the window width (it slices 24 bits against a 25-bit generator),
so my implementation uses a 25-bit window. It reproduces the book's results.

Checked values:

| Message | Check | Result |
|---|---|---|
| `8D406B902015A678D4D220AA4BDA` | remainder of the whole frame | `0` (clean) |
| `8D406B902015A678D4D220AA4BDA` | parity of the first 88 bits + 24 zeros | `AA4BDA`, which matches its PI |
| `8D4CA251204994B1C36E60A5343D` | remainder of the whole frame | `16` (corrupted) |

**One bad bit can be located.** CRC is linear, so a single flipped bit always produces a
remainder that depends only on *which* bit flipped, not on the message. I checked that all
112 single-bit remainders are different. The remainder 16 above points at one bit in the
parity field. Flipping it gives `8D4CA251204994B1C36E60A5342D`, which passes the CRC and
decodes as callsign `RYR1069`. This is the same idea as dump1090's single-bit correction
(`--no-fix` turns it off); I have not read dump1090's implementation in this phase.

**DF 11 and other formats.** In formats other than DF 17/18 the parity field is combined
(XOR) with other data. In an all-call reply (DF 11) it is combined with the interrogator
identifier, so the CRC of a clean frame comes out as that identifier: for `5D484FDEA248F5`
the remainder is 22, and 0 means a spontaneous squitter. Your Phase 2 finding (a DF 11 frame
whose remainder is `000001`, read as interrogator ID 1) is this case. The extra rule dump1090
applies there (as reported at the end of Phase 2) is not in the Riddle. For formats where the parity is
combined with the *address*, the ICAO address can be recovered as (remainder of the payload)
XOR (received parity). Checked with the book's example `A0001838CA380031440000F24177`:
`CE2CA7 XOR F24177 = 3C6DD0`.

## 5. Worked example: airborne position (TC 9–18)

ME layout (ME bit numbers 1-indexed, Python slices on the 56-character ME string):

| Field | ME bits | Width | Slice |
|---|---|---|---|
| TC | 1–5 | 5 | `me[0:5]` |
| SS (surveillance status) | 6–7 | 2 | `me[5:7]` |
| SAF (single antenna flag) | 8 | 1 | `me[7]` |
| ALT (encoded altitude) | 9–20 | 12 | `me[8:20]` |
| T (time) | 21 | 1 | `me[20]` |
| F (0 = even frame, 1 = odd) | 22 | 1 | `me[21]` |
| LAT-CPR | 23–39 | 17 | `me[22:39]` |
| LON-CPR | 40–56 | 17 | `me[39:56]` |

Two messages for the same aircraft (from the book):

```
even  8D40621D58C382D690C8AC2863A7   (most recent)
odd   8D40621D58C386435CC412692AD6
```

### Altitude

ALT is `110000111000`. Its 8th bit is the Q bit; Q = 1 means the altitude is in 25 ft steps.
Drop the Q bit to get `11000011000` = 1560, then `1560 × 25 − 1000 = 38000 ft`. When Q = 0
the field uses a different encoding (Gillham code) which this primer does not cover.
For TC 20–22 the field is a GNSS height in meters instead.

### Why CPR exists

17 bits per axis cannot hold a whole-earth latitude and longitude at useful precision.
CPR sends only the *fraction of the way across a grid cell*. Two grids are used, so each frame
alone has many possible positions (one per cell), and the second grid lets the receiver pick
the one cell that fits both. With `N_Z = 15`, the even grid has 60 latitude zones (6° each) and
the odd grid has 59 zones (about 6.1017° each). The number of longitude zones, `NL(lat)`,
shrinks toward the poles (59 at the equator, 45 around West Lafayette's 40.4° N, 1 beyond 87°).

### Global decode (one even + one odd frame)

| Step | Value |
|---|---|
| CPR fields, even | lat 93000, lon 51372 (each divided by 2¹⁷ below) |
| CPR fields, odd | lat 74158, lon 50194 |
| latitude index `j = floor(59·lat_e − 60·lat_o + ½)` | 8 |
| `lat_even = 6 · (8 + 93000/2¹⁷)` | 52.2572021484375 |
| `lat_odd = (360/59) · (8 + 74158/2¹⁷)` | 52.26578017412606 |
| `NL(lat_even)`, `NL(lat_odd)` | 36 and 36 (equal, so the pair is usable) |
| longitude index `m = floor(lon_e·(NL−1) − lon_o·NL + ½)` | 0 |
| `lon = (360/36) · (0 + 51372/2¹⁷)` using the even frame | 3.91937255859375 |

Use the latitude and longitude from the *newer* frame. If the two NL values differ, the
frames straddle a longitude-zone boundary and the pair must be discarded. If longitude comes
out at 180 or more, subtract 360. The example is over the Netherlands: 52.2572°, 3.9194°.

### Local decode (one frame + a reference)

With a reference position within 180 NM of the aircraft, a single frame is enough. Using
reference `(52.258, 3.918)` on the even frame gives exactly the same answer. The book says a
position decoded within the last 10 seconds is commonly accepted as a reference.

### Sanity check

CPR can occasionally decode to a wrong place. The book recommends a "reasonableness" test:
reject positions outside the receiver's possible range, or compare several independent pairs.

## 6. Worked example: airborne velocity (TC 19)

ME layout (slices are into the 56-character ME string):

| Field | ME bits | Slice |
|---|---|---|
| TC (19) | 1–5 | `me[0:5]` |
| Subtype (1–4) | 6–8 | `me[5:8]` |
| Intent change, IFR, NUC | 9–13 | `me[8:13]` |
| Subtype-specific fields | 14–35 | `me[13:35]` |
| Vertical-rate source (0 GNSS, 1 baro) | 36 | `me[35]` |
| Vertical-rate sign (0 up, 1 down) | 37 | `me[36]` |
| Vertical rate | 38–46 | `me[37:46]` |
| GNSS minus baro: sign, then value | 49, 50–56 | `me[48]`, `me[49:56]` |

Subtypes 1 and 2 report ground speed; 3 and 4 report airspeed. Subtypes 2 and 4 are the same
as 1 and 3 with 4 kt steps for supersonic aircraft, and are essentially unused.

### Subtype 1: `8D485020994409940838175B284F`

| Field | Bits | Value | Result |
|---|---|---|---|
| East-west sign, magnitude | `1`, `0000001001` | 1, 9 | `Vx = −(9 − 1) = −8` kt (westward) |
| North-south sign, magnitude | `1`, `0010100000` | 1, 160 | `Vy = −(160 − 1) = −159` kt (southward) |
| Speed | | | `√(8² + 159²) = 159.20` kt |
| Track | | | `atan2(Vx, Vy)` mod 360 = **182.88°** (south, a hair west) |
| Vertical rate | sign `1`, value 14 | | `−64 × (14 − 1) = −832` ft/min (descending, GNSS source) |
| GNSS minus baro | sign `0`, value 23 | | `(23 − 1) × 25 = +550` ft |

A magnitude of 0 means "no information" for that field.
Note: the book's worked line for this example prints `(−9)` and `(−160)` inside the square root
and the arctangent, but its final answers (159.20, 182.88) only come out of `(−8, −159)`;
with `(−9, −160)` you would get 160.25 and 183.22. I read that as a typo and used `(−8, −159)`,
which also agrees with pyModeS.

### Subtype 3: `8DA05F219B06B6AF189400CBC33F`

| Field | Bits | Result |
|---|---|---|
| Heading status | `1` | heading is available |
| Magnetic heading | `1010110110` = 694 | `694 × 360/1024 = 243.98°` |
| Airspeed type | `1` | true airspeed (0 would be indicated) |
| Airspeed | `0101111000` = 376 | `376 − 1 = 375` kt |
| Vertical rate | baro source, sign down, value 37 | `−64 × 36 = −2304` ft/min |
| GNSS minus baro | all zeros | not available |

Subtype 3 is rare in practice: it appears when the aircraft cannot supply a ground-speed vector.

## 7. What this means for the decoder (bridge to Phase 3)

Once the signal stage has produced bits, the rest of the decoder is the chain below. The golden
files in `tests/golden/` can check each link at message level.

1. **Frame length.** Decide whether a received frame is 56 or 112 bits. The book says 4 formats
   are short and 7 are long, but I have not verified how a receiver decides which length applies;
   take that rule from dump1090's source when writing the Phase 3 pseudocode.
2. **CRC check.** DF 17/18: whole-frame remainder must be 0. DF 11: the remainder is the interrogator
   ID, plus the DF 11 rule from the Phase 2 report.
3. **Routing.** DF first, then TC for DF 17.
4. **Field decoding.** Slices and formulas from sections 3, 5 and 6.
5. **State.** Position needs memory: an even/odd pair per ICAO, or a recent reference position.

The chapters summarized here cover DF 11 and DF 17 only. Count which DFs actually appear in
`tests/golden/modes1_raw_default.txt` before deciding the decoder's scope. Anything else (for
example DF 4/5/20/21) would need the Mode S chapters of the book.

## 8. Self-test

Try these without looking above, then check the answers below.

1. How many bits are in an ADS-B frame, and what are its five fields in order?
2. Which five bits mean DF 17? What does CA = 5 tell you?
3. What kind of message is TC 4? TC 11? TC 19?
4. Decode the 6-bit values 11, 12, 13, 49, 48, 50, 51, 32.
5. Why does an intact DF 17 frame give a CRC remainder of 0?
6. A frame has remainder 16. What is the most likely explanation, and what can you do about it?
7. Why do position messages come in even and odd forms? What makes a pair unusable?
8. ALT bits are `110000111000`. What altitude is that?
9. Velocity subtype 1 with `Sew=1, Vew=9, Sns=1, Vns=160`: roughly which way is the aircraft
   heading, and how fast?
10. In an all-call reply (DF 11), what does a CRC remainder of 22 mean?

### Answers

1. 112 bits: DF (5), CA (3), ICAO (24), ME (56), PI (24).
2. `10001`. A Level 2+ transponder that is airborne.
3. TC 4: aircraft identification and category. TC 11: airborne position with barometric altitude.
   TC 19: airborne velocity.
4. K, L, M, 1, 0, 2, 3, space → callsign `KLM1023`.
5. Because PI is the remainder of the first 88 bits followed by 24 zeros. Dividing the whole frame
   (data plus that remainder) leaves nothing over.
6. Most likely a single flipped bit (here one in the parity field). Because each single-bit position
   gives its own remainder, the bit can be found and flipped back; the repaired frame should then pass.
7. Each frame alone only fixes the position within a grid cell. The two grids have different cell sizes,
   so combining them picks out one cell. A pair is unusable if `NL(lat_even) ≠ NL(lat_odd)`.
8. 38000 ft: the Q bit is 1, the other bits are `11000011000` = 1560, and `1560 × 25 − 1000 = 38000`.
9. `Vx = −8`, `Vy = −159`: south, slightly west, track about 182.9° at about 159 kt.
10. The interrogator identifier is 22 (0 would mean a spontaneous squitter).

## 9. Not covered here

- Surface position (TC 5–8), aircraft status (TC 28), target state (TC 29), operation status
  (TC 31), and uncertainty/NIC fields.
- Gillham-coded altitude (Q = 0) and GNSS height (TC 20–22).
- Mode S replies other than DF 11 (DF 4/5, 20/21, ACAS) and the Comm-B registers.
- How the book's pseudocode handles the CRC window (see section 4).

## Sources

Junzi Sun, *The 1090 Megahertz Riddle: A Guide to Decoding Mode S and ADS-B Signals*, 2nd ed.,
TU Delft OPEN Publishing, 2021, https://doi.org/10.34641/mg.11 (CC BY-NC-SA 4.0). Chapters used:

- ADS-B basics: https://mode-s.org/1090mhz/content/ads-b/1-basics.html
- Aircraft identification: https://mode-s.org/1090mhz/content/ads-b/2-identification.html
- Airborne position: https://mode-s.org/1090mhz/content/ads-b/3-airborne-position.html
- Airborne velocity: https://mode-s.org/1090mhz/content/ads-b/5-airborne-velocity.html
- Error control: https://mode-s.org/1090mhz/content/ads-b/8-error-control.html
- Mode S basics: https://mode-s.org/1090mhz/content/mode-s/1-basics.html
- All-call reply: https://mode-s.org/1090mhz/content/mode-s/2-allcall.html

Cross-checks: pyModeS 3.6.0 (`pyModeS.decode`), via `tests/test_phase1_examples.py`.
