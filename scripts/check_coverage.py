"""Phase 5 checkpoint C: do public feeds see the low traffic around KLAF? (decision #19)

NOT part of the decoder or the backend. Standard library only.

  python scripts/check_coverage.py adsblol [--every SECONDS --count N]
      Save adsb.lol snapshots of everything within 10 NM of KLAF to data/coverage/adsblol/
      (gitignored; adsb.lol data is ODbL).
  python scripts/check_coverage.py opensky
      One manual, anonymous OpenSky snapshot, summarized on screen only. Nothing is written to disk
      (decision #18: research use only, OpenSky data is never stored).
  python scripts/check_coverage.py report [--out docs/phase5-coverage-report.md]
      Summarize the saved adsb.lol snapshots and apply decision #19's rule.

Sources (checked 2026-10-12):
  KLAF reference point: FAA NFDC airport record for LAF, 40-24-44.296 N / 86-56-12.831 W,
    elevation 605.8 ft; adsb.lol api/0/airport/KLAF gives 40.4123, -86.936897, 606 ft.
  adsb.lol: GET /v2/point/{lat}/{lon}/{radius}, radius in NM, integer 0-250
    (api.adsb.lol/api/openapi.json). Field meanings and units: the ADS-B Exchange v2 API docs
    (adsbexchange.com/version-2-api/); adsb.lol says it is a drop-in replacement
    (github.com/adsblol/api). alt_baro is feet or "ground", gs knots, seen_pos seconds before
    "now", type the source of the position.
  OpenSky: GET https://opensky-network.org/api/states/all?lamin=&lomin=&lamax=&lomax=
    (anonymous; a box of 25 sq deg or less costs 1 credit). Fields by index: 0 icao24,
    1 callsign, 3 time_position, 5 lon, 6 lat, 7 baro_altitude (m), 8 on_ground,
    16 position_source (0 ADS-B, 1 ASTERIX, 2 MLAT, 3 FLARM)
    (openskynetwork.github.io/opensky-api/rest.html).
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SNAPSHOTS = REPO / "data" / "coverage" / "adsblol"
KLAF_LAT, KLAF_LON, KLAF_ELEV_FT = 40.412304, -86.936898, 606.0
RADIUS_NM = 10
FRESH_S = 60
FT_PER_M = 1 / 0.3048
TRAINING_HOURS = range(8, 19)  # 08:00-18:59 local
USER_AGENT = (
    "adsb-tracker/0.1 (Purdue student project, coverage check; "
    "github.com/devencomstock/adsb-tracker)"
)
BANDS = [
    "ground",
    "very low (0-500 ft AGL)",
    "pattern (500-1,500)",
    "low (1,500-5,000)",
    "high (>5,000)",
    "no altitude",
]
AT_OR_BELOW_PATTERN = set(BANDS[:3])


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def distance_nm(lat: float, lon: float) -> float:
    """Great-circle distance from the KLAF reference point (haversine, Earth radius 3440.065 NM)."""
    p1, p2 = math.radians(KLAF_LAT), math.radians(lat)
    dp, dl = p2 - p1, math.radians(lon - KLAF_LON)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


def band(on_ground: bool, alt_baro_ft: float | None) -> str:
    if on_ground:
        return BANDS[0]
    if alt_baro_ft is None:
        return BANDS[5]
    agl = alt_baro_ft - KLAF_ELEV_FT
    if agl < 500:
        return BANDS[1]
    if agl < 1500:
        return BANDS[2]
    if agl < 5000:
        return BANDS[3]
    return BANDS[4]


def adsblol_kind(ac_type: str) -> str:
    for prefix, kind in (
        ("adsb_", "ADS-B"),
        ("adsr_", "ADS-R"),
        ("tisb_", "TIS-B"),
        ("mlat", "MLAT"),
    ):
        if ac_type.startswith(prefix):
            return kind
    return f"other ({ac_type})"


def adsblol_rows(snapshot: dict) -> tuple[datetime, list[dict]]:
    """Aircraft with a position at most FRESH_S old and within RADIUS_NM, as uniform rows."""
    now = snapshot["now"]
    now_s = now / 1000 if now > 1e11 else now  # observed in milliseconds; see the report
    rows = []
    for ac in snapshot.get("ac", []):
        if "lat" not in ac or ac.get("seen_pos") is None or ac["seen_pos"] > FRESH_S:
            continue
        dist = distance_nm(ac["lat"], ac["lon"])
        if dist > RADIUS_NM:
            continue
        alt = ac.get("alt_baro")
        rows.append(
            {
                "hex": ac["hex"],
                "kind": adsblol_kind(ac.get("type", "")),
                "band": band(alt == "ground", alt if isinstance(alt, (int, float)) else None),
                "dist_nm": dist,
            }
        )
    return datetime.fromtimestamp(now_s, UTC), rows


def take_adsblol() -> Path:
    data = get_json(f"https://api.adsb.lol/v2/point/{KLAF_LAT}/{KLAF_LON}/{RADIUS_NM}")
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    when, rows = adsblol_rows(data)
    low = sum(r["band"] in AT_OR_BELOW_PATTERN for r in rows)
    print(
        f"{when:%H:%M:%SZ} saved {path.name}: {len(rows)} aircraft within {RADIUS_NM} NM, "
        f"{low} at/below pattern"
    )
    return path


def take_opensky() -> None:
    """One anonymous snapshot, printed only (decision #18: never stored)."""
    dlat = RADIUS_NM / 60
    dlon = dlat / math.cos(math.radians(KLAF_LAT))
    url = (
        "https://opensky-network.org/api/states/all"
        f"?lamin={KLAF_LAT - dlat:.4f}&lomin={KLAF_LON - dlon:.4f}"
        f"&lamax={KLAF_LAT + dlat:.4f}&lomax={KLAF_LON + dlon:.4f}"
    )
    data = get_json(url)
    now = data["time"]
    counts: Counter[tuple[str, str]] = Counter()
    sources = {0: "ADS-B", 1: "ASTERIX", 2: "MLAT", 3: "FLARM"}
    for s in data.get("states") or []:
        if s[5] is None or s[6] is None or s[3] is None or now - s[3] > FRESH_S:
            continue
        if distance_nm(s[6], s[5]) > RADIUS_NM:
            continue
        alt_ft = None if s[7] is None else s[7] * FT_PER_M
        counts[(sources.get(s[16], f"source {s[16]}"), band(bool(s[8]), alt_ft))] += 1
    print(
        f"OpenSky {datetime.fromtimestamp(now, UTC):%Y-%m-%d %H:%M:%SZ} (not stored): "
        f"{sum(counts.values())} aircraft within {RADIUS_NM} NM"
    )
    for (kind, b), n in sorted(counts.items()):
        print(f"  {kind:8s} {b}: {n}")


def mostly_mlat_tisb(kinds: Counter[str], total: int) -> bool:
    return kinds["MLAT"] + kinds["TIS-B"] > total / 2


def report(out: Path | None) -> None:
    snapshots = []
    for path in sorted(SNAPSHOTS.glob("*.json")):
        when, rows = adsblol_rows(json.loads(path.read_text(encoding="utf-8")))
        snapshots.append((when.astimezone(), rows))  # local time of this machine (US Eastern)
    training = [(w, r) for w, r in snapshots if w.hour in TRAINING_HOURS]
    other = [(w, r) for w, r in snapshots if w.hour not in TRAINING_HOURS]
    low_rows = [row for _w, rows in training for row in rows if row["band"] in AT_OR_BELOW_PATTERN]
    with_low = sum(any(r["band"] in AT_OR_BELOW_PATTERN for r in rows) for _w, rows in training)
    low_kinds = Counter(r["kind"] for r in low_rows)

    if len(training) < 12:
        verdict = (
            f"**Not enough data:** {len(training)} training-hours snapshots (the rule needs 12)."
        )
    elif with_low < len(training) / 2 or mostly_mlat_tisb(low_kinds, len(low_rows)):
        verdict = (
            "**Supplement only:** public feeds are a supplement; my own antenna will be the "
            "primary source for KLAF traffic."
        )
    else:
        verdict = "**Usable as primary until the antenna arrives.**"

    lines = [
        "# Phase 5 checkpoint C: public-feed coverage of KLAF",
        "",
        "Generated by `python scripts/check_coverage.py report`. Rule: decision #19 (written "
        "before any snapshot).",
        "Data: adsb.lol, ODbL (opendatacommons.org/licenses/odbl). Raw snapshots stay in "
        "`data/coverage/` (gitignored).",
        "",
        "## Verdict",
        "",
        verdict,
        "",
        f"- Training-hours snapshots (08:00-19:00 local): **{len(training)}**; "
        f"other hours: {len(other)}.",
        f"- Training-hours snapshots with at least one aircraft at or below the pattern band "
        f"within {RADIUS_NM} NM: **{with_low} of {len(training)}**.",
        f"- Those low aircraft by data type: {dict(low_kinds) or 'none'}.",
        f"- Distinct aircraft (hex) seen at or below the pattern band: "
        f"{len({r['hex'] for r in low_rows})}.",
        "",
        "## By altitude band and data type (aircraft-snapshots, all snapshots)",
        "",
        "| Band | " + " | ".join(["ADS-B", "ADS-R", "MLAT", "TIS-B", "other"]) + " |",
        "|---|---|---|---|---|---|",
    ]
    table: Counter[tuple[str, str]] = Counter(
        (r["band"], r["kind"] if not r["kind"].startswith("other") else "other")
        for _w, rows in snapshots
        for r in rows
    )
    for b in BANDS:
        cells = [str(table[(b, k)]) for k in ("ADS-B", "ADS-R", "MLAT", "TIS-B", "other")]
        lines.append(f"| {b} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## By time of day (local)",
        "",
        "| Snapshot (local) | Within 10 NM | At/below pattern | Low aircraft |",
        "|---|---|---|---|",
    ]
    for when, rows in snapshots:
        low = [r for r in rows if r["band"] in AT_OR_BELOW_PATTERN]
        names = (
            ", ".join(f"{r['hex']} ({r['band'].split(' (')[0]}, {r['kind']})" for r in low) or "-"
        )
        lines.append(f"| {when:%Y-%m-%d %H:%M} | {len(rows)} | {len(low)} | {names} |")
    lines += [
        "",
        "## Limits",
        "",
        "- An aircraft without ADS-B Out (and not covered by MLAT/TIS-B) is invisible to every "
        "public feed. This check can only show that the feeds *see* low traffic, never that they "
        "see all of it.",
        "- Training activity depends on weather and season, and this is a short sample. Revisit "
        "with my own antenna.",
        "- Freshness: a position counts only if `seen_pos` is at most 60 s. adsb.lol's `now` "
        "arrived in **milliseconds**, although the ADS-B Exchange v2 doc describes it as seconds; "
        "the script detects which by its size.",
        "- OpenSky snapshots were taken by hand for a cross-check and are not stored "
        "(decision #18).",
    ]
    text = "\n".join(lines) + "\n"
    if out:
        out.write_text(text, encoding="utf-8", newline="\n")
        print("wrote", out)
    else:
        print(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    poll = sub.add_parser("adsblol")
    poll.add_argument("--every", type=int, default=600, help="seconds between snapshots (min 300)")
    poll.add_argument("--count", type=int, default=1)
    sub.add_parser("opensky")
    rep = sub.add_parser("report")
    rep.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.command == "adsblol":
        every = max(args.every, 300)  # conservative: at most one request every 5 minutes
        for i in range(args.count):
            take_adsblol()
            if i + 1 < args.count:
                time.sleep(every)
    elif args.command == "opensky":
        take_opensky()
    else:
        report(args.out)


if __name__ == "__main__":
    main()
