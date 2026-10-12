#!/usr/bin/env bash
# Locate golden lines in modes1.bin using dump1090 itself as the reference. NOT part of the decoder.
#
# For each golden line index K (0-based), find the shortest even-length prefix of modes1.bin such
# that dump1090's first K+1 raw lines equal the golden file's first K+1 lines. Each prefix is padded
# back to the full file size with byte 127 (zero signal), so dump1090's chunked reading behaves as in
# the real run. In the no-fix run a frame is output only once all of its samples are present, so
#   start sample = shortest prefix (in samples) - 16 - 2 * frame bits
# (calibrated on line 0: 1034 - 240 = 794, the known start). Frames dump1090 recovered with its
# phase-correction retry can come out a sample off, so check each result with
# `scripts/golden_stats.py --trace`.
#
# Run in WSL, from anywhere (needs ~/src/dump1090 built at the pinned commit, see tests/golden/README.md):
#   bash scripts/dump1090_prefix_search.sh nofix 0 112 128 174 185 188 193
#   bash scripts/dump1090_prefix_search.sh nofix all > data/modes1_prefix_nofix.txt   (every line)
#
# Modes padded_nofix / padded_default search the supplementary padded golden files (decision #13)
# against modes1.bin padded to 786,432 bytes; `tail` there means every line after the approved 217:
#   bash scripts/dump1090_prefix_search.sh padded_nofix tail > data/modes1_prefix_padded_nofix.txt
set -u
MODE=$1
shift
REPO=$(cd "$(dirname "$0")/.." && pwd)
cd ~/src/dump1090
F=testfiles/modes1.bin
case "$MODE" in
  padded_*)
    GOLD="$REPO/tests/golden/modes1_padded_raw_${MODE#padded_}.txt"
    APPROVED="$REPO/tests/golden/modes1_raw_${MODE#padded_}.txt"
    PADDED_INPUT=$(mktemp)
    trap 'rm -f "$PADDED_INPUT"' EXIT
    { cat "$F"; head -c $((786432 - $(stat -c %s "$F"))) /dev/zero | tr '\0' '\177'; } > "$PADDED_INPUT"
    F=$PADDED_INPUT
    ;;
  *) GOLD="$REPO/tests/golden/modes1_raw_$MODE.txt" ;;
esac
SIZE=$(stat -c %s "$F")
case "$MODE" in *nofix) FLAGS="--no-fix" ;; *) FLAGS="" ;; esac

padded() { head -c "$1" "$F"; head -c $((SIZE - $1)) /dev/zero | tr '\0' '\177'; }
ok_for() {  # $1 = prefix bytes, $2 = K: do the first K+1 output lines match the golden file?
  local want got
  want=$(sed -n "1,$(($2 + 1))p" "$GOLD" | sha256sum)
  got=$(padded "$1" | ./dump1090 --ifile - --raw $FLAGS 2>/dev/null | sed -n "1,$(($2 + 1))p" | sha256sum)
  [ "$want" = "$got" ]
}

if [ "${1:-}" = all ]; then
  # Every golden line, in order. Line K can't need a shorter prefix than line K-1, so each
  # search starts from the previous answer.
  set -- $(seq 0 $(($(wc -l < "$GOLD") - 1)))
  INCREMENTAL=1
elif [ "${1:-}" = tail ]; then
  set -- $(seq "$(wc -l < "$APPROVED")" $(($(wc -l < "$GOLD") - 1)))
  INCREMENTAL=1
else
  INCREMENTAL=0
fi

prev=0
for K in "$@"; do
  lo=0
  [ "$INCREMENTAL" = 1 ] && lo=$((prev > 2 ? prev - 2 : 0))
  hi=$SIZE
  while [ $((hi - lo)) -gt 2 ]; do
    mid=$(((lo + hi) / 4 * 2))
    if ok_for "$mid" "$K"; then hi=$mid; else lo=$mid; fi
  done
  line=$(sed -n "$((K + 1))p" "$GOLD")
  hex=${line#\*}
  hex=${hex%;}
  bits=$((${#hex} * 4))
  echo "$MODE line=$K shortest_prefix_samples=$((hi / 2)) start_estimate=$((hi / 2 - 16 - 2 * bits)) $line"
  prev=$hi
done
