from app.services.streaming import PartialSnapshotter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_emits_partial_objects_with_trailing_strings() -> None:
    s = PartialSnapshotter(clock=Clock())
    event = s.feed('{"project_name": "Yoga Bo')
    assert event is not None and event.seq == 1
    assert event.breakdown == {"project_name": "Yoga Bo"}


def test_throttles_within_interval_and_flush_emits_latest() -> None:
    clock = Clock()
    s = PartialSnapshotter(min_interval=0.1, clock=clock)
    assert s.feed('{"a": "x') is not None
    clock.now = 0.05
    assert s.feed('{"a": "xy') is None
    flushed = s.flush('{"a": "xyz"}')
    assert flushed is not None and flushed.breakdown == {"a": "xyz"} and flushed.seq == 2


def test_unchanged_snapshot_is_not_reemitted() -> None:
    clock = Clock()
    s = PartialSnapshotter(clock=clock)
    s.feed('{"a": 1, ')
    clock.now = 1
    assert s.feed('{"a": 1, "b') is None  # same dict: {"a": 1}


def test_flush_skips_unchanged_snapshot() -> None:
    s = PartialSnapshotter(clock=Clock())
    s.feed('{"a": 1')
    assert s.flush('{"a": 1}') is None


def test_empty_whitespace_and_non_object_snapshots_are_ignored() -> None:
    s = PartialSnapshotter(clock=Clock())
    assert s.feed("") is None
    assert s.feed("   ") is None
    assert s.feed('["x"') is None
    assert s.feed("garbage {") is None
