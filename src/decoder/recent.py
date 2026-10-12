"""Recently seen ICAO addresses, timed in recording seconds (decision #7)."""

from __future__ import annotations

WINDOW_S = 60.0
SAMPLE_RATE_HZ = 2_000_000


def recording_time(sample_index: int) -> float:
    """Seconds since the start of the recording for a sample index at 2 MHz."""
    return sample_index / SAMPLE_RATE_HZ


class RecentlySeen:
    """ICAO addresses seen in clean DF 11/17/18 frames, each with the time it was last seen."""

    def __init__(self, window_s: float = WINDOW_S) -> None:
        self.window_s = window_s
        self._last_seen: dict[int, float] = {}

    def add(self, icao: int, t: float) -> None:
        self._last_seen[icao] = t

    def seen(self, icao: int, t: float) -> bool:
        """True if `icao` was added no more than `window_s` seconds before `t`."""
        last = self._last_seen.get(icao)
        return last is not None and t - last <= self.window_s
