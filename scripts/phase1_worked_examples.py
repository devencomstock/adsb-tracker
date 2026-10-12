"""Phase 1 study aid: worked Mode S / ADS-B examples, derived step by step.

This is NOT the project decoder. The decoder (src/decoder/, Phase 4) turns raw
samples into bits. This file starts after that point: it takes a message as a hex
string and re-derives every field, so the numbers in docs/mode-s-primer.md can be
checked by running it. It uses only the standard library. pyModeS is deliberately
not imported here; tests/test_phase1_examples.py compares this file against pyModeS.

Every formula comes from Junzi Sun, "The 1090 Megahertz Riddle" (2nd ed.),
https://mode-s.org/1090mhz/ . The chapter is named next to each function.

Run:  python scripts/phase1_worked_examples.py
"""

from __future__ import annotations

import math

# Chapter "Error control in ADS-B": generator polynomial, 25 bits, 0x1FFF409.
GENERATOR = 0x1FFF409
# Chapter "Airborne position": number of latitude zones between equator and pole.
NZ = 15
# Chapter "Aircraft identification": 6-bit code -> character (64 entries).
CHARSET = "#" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + "#" * 5 + " " + "#" * 15 + "0123456789" + "#" * 6
assert len(CHARSET) == 64

# Example messages. Every one appears in the Riddle, in the chapter named.
ID_MSG = "8D4840D6202CC371C32CE0576098"  # Aircraft identification
POS_EVEN = "8D40621D58C382D690C8AC2863A7"  # Airborne position, even frame (most recent)
POS_ODD = "8D40621D58C386435CC412692AD6"  # Airborne position, odd frame
VEL_A = "8D485020994409940838175B284F"  # Airborne velocity, subtype 1 (ground speed)
VEL_B = "8DA05F219B06B6AF189400CBC33F"  # Airborne velocity, subtype 3 (airspeed)
CRC_GOOD = "8D406B902015A678D4D220AA4BDA"  # Error control: remainder 0
CRC_BAD = "8D4CA251204994B1C36E60A5343D"  # Error control: remainder 16
ALLCALL = "5D484FDEA248F5"  # All-call reply (DF11): interrogator id 22


def to_bits(msg_hex: str) -> str:
    """Hex string -> string of '0'/'1', 4 bits per hex digit."""
    return bin(int(msg_hex, 16))[2:].zfill(len(msg_hex) * 4)


# ---------------------------------------------------------------- CRC (Error control)


def crc_remainder(bits: str) -> int:
    """Remainder of dividing the whole bit string by the generator (XOR long division).

    A valid ADS-B message (all 112 bits) gives 0. For a short all-call reply (56 bits)
    the remainder is the interrogator identifier.
    """
    n = len(bits)
    reg = int(bits, 2)
    for i in range(n - 24):
        if (reg >> (n - 1 - i)) & 1:
            # The generator is 25 bits wide, so it is aligned under bits i .. i+24.
            reg ^= GENERATOR << (n - 25 - i)
    return reg & 0xFFFFFF


def adsb_parity(msg_hex: str) -> int:
    """Parity the sender computes: remainder of the first 88 bits followed by 24 zeros."""
    bits = to_bits(msg_hex)
    return crc_remainder(bits[:-24] + "0" * 24)


def syndrome_table(n_bits: int) -> dict[int, int]:
    """Remainder produced by a single flipped bit at each position -> that position.

    CRC is linear, so remainder(message with one error) = remainder(error pattern)
    when the original message was valid. That makes each single-bit error recognisable.
    """
    table: dict[int, int] = {}
    for pos in range(n_bits):
        error = 1 << (n_bits - 1 - pos)
        table[crc_remainder(bin(error)[2:].zfill(n_bits))] = pos
    return table


def fix_single_bit(msg_hex: str) -> str | None:
    """Return the repaired message if exactly one flipped bit explains the remainder."""
    bits = to_bits(msg_hex)
    rem = crc_remainder(bits)
    if rem == 0:
        return msg_hex
    pos = syndrome_table(len(bits)).get(rem)
    if pos is None:
        return None
    flipped = bits[:pos] + ("1" if bits[pos] == "0" else "0") + bits[pos + 1 :]
    return f"{int(flipped, 2):0{len(msg_hex)}X}"


# ---------------------------------------------------------------- common frame fields


def frame_fields(msg_hex: str) -> dict[str, int | str]:
    """Split a 112-bit frame: DF(5) CA(3) ICAO(24) ME(56) PI(24). Chapter "ADS-B basics"."""
    bits = to_bits(msg_hex)
    assert len(bits) == 112, "expected a 112-bit (28 hex digit) frame"
    return {
        "df": int(bits[0:5], 2),
        "ca": int(bits[5:8], 2),
        "icao": f"{int(bits[8:32], 2):06X}",
        "me": bits[32:88],
        "tc": int(bits[32:37], 2),
        "pi": f"{int(bits[88:112], 2):06X}",
    }


# ---------------------------------------------------------------- identification


def identification(me: str) -> tuple[int, str]:
    """ME bits -> (category CA, callsign). Chapter "Aircraft identification"."""
    category = int(me[5:8], 2)
    chars = [CHARSET[int(me[8 + 6 * k : 14 + 6 * k], 2)] for k in range(8)]
    return category, "".join(chars).rstrip()


# ---------------------------------------------------------------- airborne position


def barometric_altitude_ft(me: str) -> int | None:
    """12-bit altitude field, Q bit = 1 case only. Chapter "Airborne position"."""
    alt = me[8:20]
    if int(alt, 2) == 0:
        return None
    if alt[7] != "1":
        raise NotImplementedError("Q=0 uses the Gillham code; not needed for the examples")
    n = int(alt[:7] + alt[8:], 2)  # drop the Q bit (8th bit of the field)
    return 25 * n - 1000


def cpr_fields(me: str) -> tuple[int, int, int]:
    """ME bits -> (odd/even flag F, 17-bit CPR latitude, 17-bit CPR longitude)."""
    return int(me[21], 2), int(me[22:39], 2), int(me[39:56], 2)


def nl(lat: float) -> int:
    """Number of longitude zones at this latitude (1..59)."""
    a = abs(lat)
    if a == 0:
        return 59
    if a == 87:
        return 2
    if a > 87:
        return 1
    x = 1 - (1 - math.cos(math.pi / (2 * NZ))) / math.cos(math.radians(lat)) ** 2
    return math.floor(2 * math.pi / math.acos(x))


def cpr_global(
    even: tuple[int, int], odd: tuple[int, int], latest: str = "even"
) -> dict[str, float | int] | None:
    """Globally unambiguous decode from one even and one odd frame.

    `even` and `odd` are (cpr_lat, cpr_lon) integers. `latest` says which frame is
    newer. Returns the intermediate values too, or None if the frames straddle a
    longitude-zone boundary (wait for a new pair).
    """
    lat_e, lon_e = even[0] / 2**17, even[1] / 2**17
    lat_o, lon_o = odd[0] / 2**17, odd[1] / 2**17
    j = math.floor(59 * lat_e - 60 * lat_o + 0.5)
    lat_even = (360 / (4 * NZ)) * (j % 60 + lat_e)
    lat_odd = (360 / (4 * NZ - 1)) * (j % 59 + lat_o)
    if lat_even >= 270:
        lat_even -= 360
    if lat_odd >= 270:
        lat_odd -= 360
    if nl(lat_even) != nl(lat_odd):
        return None
    lat = lat_even if latest == "even" else lat_odd
    n_l = nl(lat)
    m = math.floor(lon_e * (n_l - 1) - lon_o * n_l + 0.5)
    if latest == "even":
        n = max(n_l, 1)
        lon = (360 / n) * (m % n + lon_e)
    else:
        n = max(n_l - 1, 1)
        lon = (360 / n) * (m % n + lon_o)
    if lon >= 180:
        lon -= 360
    return {
        "j": j,
        "lat_even": lat_even,
        "lat_odd": lat_odd,
        "nl": n_l,
        "m": m,
        "lat": lat,
        "lon": lon,
    }


def cpr_local(
    f: int, lat_cpr: int, lon_cpr: int, lat_ref: float, lon_ref: float
) -> tuple[float, float]:
    """Locally unambiguous decode: one frame plus a reference within 180 NM."""
    lc, oc = lat_cpr / 2**17, lon_cpr / 2**17
    dlat = 360 / (4 * NZ - f)
    j = math.floor(lat_ref / dlat) + math.floor((lat_ref % dlat) / dlat - lc + 0.5)
    lat = dlat * (j + lc)
    dlon = 360 / max(nl(lat) - f, 1)
    m = math.floor(lon_ref / dlon) + math.floor((lon_ref % dlon) / dlon - oc + 0.5)
    return lat, dlon * (m + oc)


# ---------------------------------------------------------------- airborne velocity


def velocity(me: str) -> dict[str, float | int | str | None]:
    """TC=19 ME bits -> speed, direction, vertical rate, GNSS-baro difference."""
    subtype = int(me[5:8], 2)
    scale = 4 if subtype in (2, 4) else 1
    out: dict[str, float | int | str | None] = {"subtype": subtype}

    if subtype in (1, 2):  # ground speed from east-west and north-south components
        vew, vns = int(me[14:24], 2), int(me[25:35], 2)
        vx = (-1 if me[13] == "1" else 1) * scale * (vew - 1)
        vy = (-1 if me[24] == "1" else 1) * scale * (vns - 1)
        out["vx"], out["vy"] = vx, vy
        out["speed_kt"] = math.hypot(vx, vy)
        out["track_deg"] = math.degrees(math.atan2(vx, vy)) % 360
    else:  # subtype 3/4: airspeed and magnetic heading
        out["heading_deg"] = int(me[14:24], 2) * 360 / 1024 if me[13] == "1" else None
        out["airspeed_kt"] = scale * (int(me[25:35], 2) - 1)
        out["airspeed_type"] = "TAS" if me[24] == "1" else "IAS"

    vr_raw = int(me[37:46], 2)
    out["vr_source"] = "BARO" if me[35] == "1" else "GNSS"
    out["vertical_rate_fpm"] = (
        None if vr_raw == 0 else (-1 if me[36] == "1" else 1) * 64 * (vr_raw - 1)
    )
    d_raw = int(me[49:56], 2)
    out["geo_minus_baro_ft"] = (
        None if d_raw == 0 else (-1 if me[48] == "1" else 1) * (d_raw - 1) * 25
    )
    return out


# ---------------------------------------------------------------- demo


def _show(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    _show("Identification: " + ID_MSG)
    f = frame_fields(ID_MSG)
    cat, call = identification(str(f["me"]))
    print(f"DF={f['df']} CA={f['ca']} ICAO={f['icao']} TC={f['tc']} PI={f['pi']}")
    print(f"category={cat} callsign={call!r}")

    _show("CRC")
    print(f"{CRC_GOOD}: remainder of whole frame = {crc_remainder(to_bits(CRC_GOOD))}")
    print(f"{CRC_GOOD}: parity of first 88 bits  = {adsb_parity(CRC_GOOD):06X}")
    print(f"{CRC_BAD}: remainder of whole frame = {crc_remainder(to_bits(CRC_BAD))}")
    print(f"{CRC_BAD}: single-bit repair gives   = {fix_single_bit(CRC_BAD)}")
    print(f"{ALLCALL}: DF11 remainder (interrogator id) = {crc_remainder(to_bits(ALLCALL))}")
    print(f"syndromes for 112-bit frames are distinct: {len(syndrome_table(112)) == 112}")

    _show("Airborne position")
    me_e = str(frame_fields(POS_EVEN)["me"])
    me_o = str(frame_fields(POS_ODD)["me"])
    fe, lat_e, lon_e = cpr_fields(me_e)
    fo, lat_o, lon_o = cpr_fields(me_o)
    print(f"ALT bits {me_e[8:20]} -> {barometric_altitude_ft(me_e)} ft")
    print(f"even: F={fe} lat_cpr={lat_e} lon_cpr={lon_e}")
    print(f"odd : F={fo} lat_cpr={lat_o} lon_cpr={lon_o}")
    steps = cpr_global((lat_e, lon_e), (lat_o, lon_o), latest="even")
    print("global:", steps)
    print("local (ref 52.258, 3.918):", cpr_local(fe, lat_e, lon_e, 52.258, 3.918))

    _show("Airborne velocity")
    print("A:", velocity(str(frame_fields(VEL_A)["me"])))
    print("B:", velocity(str(frame_fields(VEL_B)["me"])))


if __name__ == "__main__":
    main()
