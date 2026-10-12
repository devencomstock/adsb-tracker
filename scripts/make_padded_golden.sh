#!/usr/bin/env bash
# Supplementary golden files from modes1.bin padded to 3 full dump1090 buffers (decision #13).
#
# dump1090 never decodes the last, partial 262,144-byte buffer of a file (tests/golden/README.md).
# Padding modes1.bin with byte 127 (zero signal, the same value dump1090 itself pads with) up to
# 3 x 262,144 = 786,432 bytes makes the third buffer full, so dump1090 decodes the whole recording.
# Each command runs twice; the outputs must be identical.
#
# Run in WSL from the repo root (needs ~/src/dump1090 built at the pinned commit):
#   bash scripts/make_padded_golden.sh
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT="$REPO/tests/golden"
cd ~/src/dump1090
git rev-parse HEAD
F=testfiles/modes1.bin
PADDED=$(mktemp)
SIZE=$(stat -c %s "$F")
{ cat "$F"; head -c $((786432 - SIZE)) /dev/zero | tr '\0' '\177'; } > "$PADDED"
echo "padded input: $(stat -c %s "$PADDED") bytes, sha256 $(sha256sum "$PADDED" | cut -d' ' -f1)"

run() {  # $1 = output name, rest = dump1090 flags
  local name=$1
  shift
  for pass in 1 2; do
    timeout 60 ./dump1090 --ifile "$PADDED" "$@" > "$OUT/$name.txt.$pass" 2> "$OUT/$name.err"
    [ -s "$OUT/$name.err" ] && { echo "stderr not empty for $name"; exit 1; }
  done
  cmp "$OUT/$name.txt.1" "$OUT/$name.txt.2"
  mv "$OUT/$name.txt.1" "$OUT/$name.txt"
  rm "$OUT/$name.txt.2" "$OUT/$name.err"
  echo "$(sha256sum "$OUT/$name.txt" | cut -d' ' -f1)  $name.txt  $(wc -l < "$OUT/$name.txt") lines"
}
run modes1_padded_raw_nofix --raw --no-fix
run modes1_padded_raw_default --raw
run modes1_padded_decoded_nofix --no-fix
run modes1_padded_decoded_default
rm "$PADDED"
