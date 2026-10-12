# Decoder notes

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

## Decoder stages

To be filled in during Phases 1-4.

### 1. Samples to magnitude
### 2. Preamble detection
### 3. Pulses to bits
### 4. CRC check
### 5. Message routing (by DF / type code)
### 6. Output fields
