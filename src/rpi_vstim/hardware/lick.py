"""Lick contact debouncing and physiological event classification."""

MIN_CLASSIFIED_LICK_INTERVAL_MS = 70
RELEASE_STABLE_MS = 25


class LickClassifier:
    """Turn raw GPIO levels into one event per released contact."""

    def __init__(
        self,
        *,
        release_stable_ms: int = RELEASE_STABLE_MS,
        min_classified_lick_interval_ms: int = MIN_CLASSIFIED_LICK_INTERVAL_MS,
        initial_level: int = 0,
        initial_timestamp_ns: int = 0,
    ) -> None:
        if release_stable_ms <= 0 or min_classified_lick_interval_ms <= 0:
            raise ValueError("lick timing settings must be positive")
        if initial_level not in (0, 1):
            raise ValueError("lick levels must be 0 or 1")
        self.release_stable_ns = release_stable_ms * 1_000_000
        self.min_classified_lick_interval_ns = min_classified_lick_interval_ms * 1_000_000
        self._latched = initial_level == 1
        self._low_since_ns = initial_timestamp_ns if initial_level == 0 else None
        self._last_classified_ns: int | None = None
        self._last_edge_ns: int | None = None

    def process_edge(self, level: int, timestamp_ns: int) -> bool:
        """Consume one raw edge; return whether it is a classified lick."""
        if level not in (0, 1):
            raise ValueError("lick levels must be 0 or 1")
        if self._last_edge_ns is not None and timestamp_ns < self._last_edge_ns:
            raise ValueError("lick edge timestamps must be monotonic")
        self._last_edge_ns = timestamp_ns

        if level == 0:
            if self._low_since_ns is None:
                self._low_since_ns = timestamp_ns
            return False

        if self._latched:
            if (
                self._low_since_ns is None
                or timestamp_ns - self._low_since_ns < self.release_stable_ns
            ):
                return False
            self._latched = False
            self._low_since_ns = None

        self._latched = True
        if (
            self._last_classified_ns is not None
            and timestamp_ns - self._last_classified_ns < self.min_classified_lick_interval_ns
        ):
            return False
        self._last_classified_ns = timestamp_ns
        return True


class LickInput:
    def start(self) -> None:
        raise NotImplementedError("lick capture starts after Phase 00")
