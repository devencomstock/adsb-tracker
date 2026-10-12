from decoder.recent import RecentlySeen, recording_time


def test_recording_time_is_sample_index_over_2_mhz() -> None:
    assert recording_time(794) == 0.000397
    assert recording_time(2_000_000) == 1.0


def test_window_is_inclusive_60_seconds() -> None:
    recent = RecentlySeen()
    recent.add(0x4D2023, 10.0)
    assert recent.seen(0x4D2023, 10.0)
    assert recent.seen(0x4D2023, 70.0)
    assert not recent.seen(0x4D2023, 70.5)
    assert not recent.seen(0x123456, 10.0)


def test_adding_again_refreshes_the_time() -> None:
    recent = RecentlySeen()
    recent.add(0x4D2023, 0.0)
    recent.add(0x4D2023, 50.0)
    assert recent.seen(0x4D2023, 100.0)
