import pytest

from rpi_vstim.hardware.lick import (
    MIN_CLASSIFIED_LICK_INTERVAL_MS,
    RELEASE_STABLE_MS,
    LickClassifier,
)


def test_bounce_is_one_contact_and_release_rearms():
    classifier = LickClassifier()
    ms = 1_000_000
    assert not classifier.process_edge(0, 0)
    assert classifier.process_edge(1, 30 * ms)
    assert not classifier.process_edge(0, 31 * ms)
    assert not classifier.process_edge(1, 32 * ms)
    assert not classifier.process_edge(0, 33 * ms)
    assert not classifier.process_edge(1, 50 * ms)
    assert not classifier.process_edge(0, 51 * ms)
    assert classifier.process_edge(1, 100 * ms)


def test_physiological_interval_guard_is_not_a_100_ms_cap():
    classifier = LickClassifier()
    ms = 1_000_000
    assert not classifier.process_edge(0, 0)
    assert classifier.process_edge(1, 30 * ms)
    assert not classifier.process_edge(0, 31 * ms)
    assert not classifier.process_edge(1, 90 * ms)
    assert not classifier.process_edge(0, 91 * ms)
    assert classifier.process_edge(1, 116 * ms)


def test_invalid_lick_timing_is_rejected():
    with pytest.raises(ValueError):
        LickClassifier(release_stable_ms=0)
    with pytest.raises(ValueError):
        LickClassifier(min_classified_lick_interval_ms=0)
    with pytest.raises(ValueError):
        LickClassifier().process_edge(2, 0)


def test_requested_defaults_are_explicit():
    assert MIN_CLASSIFIED_LICK_INTERVAL_MS == 70
    assert RELEASE_STABLE_MS == 25


def test_recorded_bounce_shaped_bursts_produce_one_lick_each():
    classifier = LickClassifier()
    ms = 1_000_000
    classified = 0
    for burst in range(20):
        base = burst * 200 * ms
        for level, offset in ((1, 30), (0, 35), (1, 40), (0, 45), (1, 50), (0, 100)):
            classified += classifier.process_edge(level, base + offset * ms)
    assert classified == 20


def test_first_contact_starts_a_fresh_release_timer():
    classifier = LickClassifier()
    ms = 1_000_000
    assert classifier.process_edge(1, 5_000 * ms)
    assert not classifier.process_edge(0, 5_001 * ms)
    assert not classifier.process_edge(1, 5_001 * ms + 1_000)
