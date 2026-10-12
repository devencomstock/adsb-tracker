# Golden data: dump1090 answer key for `modes1.bin`

These files are the output of antirez's dump1090 on its own test recording. My decoder is
compared against them. See decisions #4 and #5 in `docs/decisions.md`.

All files here are marked `-text` in `.gitattributes`, so git never changes their line endings
and the checksums below stay valid on Windows.

## Source

| Item | Value |
|------|-------|
| dump1090 repo | https://github.com/antirez/dump1090 |
| Commit (pinned) | `efe64db3c6ba1520291331628a33c1e208e851a6` (2026-02-15, "Clarify high computation in preamble detection.") |
| Input file | `testfiles/modes1.bin` in that repo, copied to `data/modes1.bin` (gitignored) |
| Input size | 713,736 bytes |
| Input sha256 | `3a33e16025da8669149c780075950b4e908ca036ea21f9583c113f60d5fb3094` |
| Built with | Ubuntu 24.04 (WSL), gcc 13.3.0, librtlsdr 2.0.1, plain `make` |

## How to reproduce (in WSL)

```bash
git clone https://github.com/antirez/dump1090 ~/src/dump1090
cd ~/src/dump1090
git checkout efe64db3c6ba1520291331628a33c1e208e851a6
make

OUT=~/src/dump1090-golden
mkdir -p "$OUT"
timeout 60 ./dump1090 --ifile testfiles/modes1.bin --raw          > "$OUT/modes1_raw_default.txt"     2> "$OUT/modes1_raw_default.err"
timeout 60 ./dump1090 --ifile testfiles/modes1.bin --raw --no-fix > "$OUT/modes1_raw_nofix.txt"       2> "$OUT/modes1_raw_nofix.err"
timeout 60 ./dump1090 --ifile testfiles/modes1.bin                > "$OUT/modes1_decoded_default.txt" 2> "$OUT/modes1_decoded_default.err"
timeout 60 ./dump1090 --ifile testfiles/modes1.bin --no-fix       > "$OUT/modes1_decoded_nofix.txt"   2> "$OUT/modes1_decoded_nofix.err"
sha256sum "$OUT"/*.txt
```

Flags (from `./dump1090 --help`):
- `--ifile <filename>`: read samples from a file instead of a dongle. It reads the file once and
  exits, because `--loop` is off by default.
- `--raw`: print only each message's hex, one per line, as `*<hex>;`.
- `--no-fix`: disable single-bit error correction using the CRC. Defaults otherwise apply:
  CRC check on, single-bit fix on, no `--aggressive` two-bit fixing.

Each command was run twice and gave identical sha256 both times. All runs exited with code 0, and
every `.err` file was empty.

## Files

| File | Settings | Lines | Bytes | sha256 |
|------|----------|-------|-------|--------|
| `modes1_raw_nofix.txt` | `--raw --no-fix` | 217 | 5,551 | `c04cb8f05b96a03791f3d82a42518da9d2b1e9fbe99aade1f5b11b3ed5a8d830` |
| `modes1_raw_default.txt` | `--raw` | 217 | 5,551 | `df33c5f123ecbef63d2f067602cbaf67174eaf16b841d6d512f143757b461e82` |
| `modes1_decoded_nofix.txt` | `--no-fix` | 2,421 | 66,083 | `8b5356287746996f777efd0ebb2e3067935462ead20ffdadaed25b5e0407bf78` |
| `modes1_decoded_default.txt` | (defaults) | 2,427 | 66,268 | `2c60641b67a8d5f577ac032baebe4eef70ba4d1a3f1f61eee7103ae8df60f944` |

Match the **no-fix** files first (my decoder starts without error correction), and the default
files later.

## Statistics quoted in the docs

`scripts/golden_stats.py` prints the numbers quoted in `docs/pseudocode.md` and decision #7. It covers DF and
type-code counts per file, the replay under the "seen earlier in the recording" rule (54 list-dependent
messages in the no-fix file, 0 exceptions), and the stage 4 CRC examples. With `--trace` it also prints the
sample-level hand trace of the first message (it starts at sample 794), which needs `data/modes1.bin`. It isn't
part of the decoder. From the repo root, in PowerShell:

```powershell
.\.venv\Scripts\python scripts\golden_stats.py            # golden files only
.\.venv\Scripts\python scripts\golden_stats.py --trace    # also the sample-level trace
```

## What error correction changes (default vs no-fix)

Both settings produce the **same 217 messages**. Error correction adds no messages on this
recording; it only changes how 6 of them are recovered.

`--stats` output for each setting:

| Counter | default | `--no-fix` |
|---------|---------|------------|
| valid preambles | 415 | 415 |
| demodulated again after phase correction | 216 | 220 |
| with good crc | 211 | 217 |
| with bad crc | 196 | 190 |
| errors corrected | 6 | 0 |
| total usable messages | 217 | 217 |

Why the same messages most likely come out both ways (an inference from the counters, not traced
frame by frame): when a frame fails its CRC, dump1090 retries demodulating it with
**phase correction** (`dump1090.c` lines 1785-1790). With `--no-fix`, there are 4 more phase-correction
retries (220 vs 216) and 6 more good-CRC frames. That fits the retry recovering the frames the CRC fix
would otherwise have repaired.

The differences, from `diff nofix default`:
- **Raw:** two lines differ, both the same DF11 message: `*5d4d20237a55a7;` (no-fix) vs
  `*5d4d20237a55a6;` (default). Its CRC remainder is `000001`.
  - With `--no-fix`, dump1090 accepts it as a DF11 reply whose remainder is a small
    interrogator ID (IID = 1). It allows that when the remainder is below 80 and the ICAO is recently seen
    (`dump1090.c` lines 1202-1209).
  - With the fix on, it instead flips the last parity bit (bit 55) to make the remainder 0.
  - Both readings are consistent with the bits. They are two interpretations, and neither is a decoding mistake.
- **Decoded:** the same two DF11 differences, plus 4 extra `Single bit error fixed, bit N` lines
  (bits 66, 61, 99 on DF17 and bit 5 on DF11). In those 4 cases the hex is identical in both files.
