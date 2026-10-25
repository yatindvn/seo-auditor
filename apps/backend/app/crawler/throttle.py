"""Adaptive admission control for the crawl loop (AIMD).

The crawl used to allow a fixed number of fetches in flight. A fast site could
take more; a struggling one was hit just as hard while it slowed or started
answering 429. This grows the in-flight limit additively while responses stay
healthy, and halves it the moment the site pushes back -- the same rule TCP
uses, for the same reason: probe gently, retreat fast.

Pure and deterministic: time is passed in, so it is tested without sleeping.
"""

from __future__ import annotations

import statistics
from typing import List, Optional

RETRY_AFTER_CAP_SECONDS = 60.0
HEALTHY_RATIO = 1.5
SLOW_RATIO = 2.0


class AdaptiveLimit:
    def __init__(self, initial: int, maximum: int, minimum: int = 4,
                 window: int = 50, growth: int = 4) -> None:
        self.maximum = max(maximum, 1)
        self.minimum = max(min(minimum, initial), 1)
        self.limit = min(max(initial, self.minimum), self.maximum)
        self.window = window
        self.growth = growth
        self.paused_until = 0.0
        self._baseline: Optional[float] = None
        # Separate from _baseline, which stays None when responses carry no
        # timing: "measured nothing" must not read as "not measured yet".
        self._have_baseline = False
        self._times: List[float] = []
        self._count = 0
        self._failed_in_window = False
        # Responses seen since the last cut, and how many were in flight when
        # it happened. Until that many have come back, a failure may belong to
        # a request sent before the cut and must not cut again.
        self._since_cut: Optional[int] = None
        self._in_flight_at_cut = 0

    def record(self, response_ms: Optional[float], failed: bool,
               retry_after: Optional[float], now: float) -> None:
        if retry_after is not None:
            self.paused_until = max(self.paused_until, now + min(retry_after, RETRY_AFTER_CAP_SECONDS))

        if self._since_cut is not None:
            self._since_cut += 1

        if failed:
            self._failed_in_window = True
            if self._since_cut is None or self._since_cut > self._in_flight_at_cut:
                self._cut()
                return

        if response_ms is not None:
            self._times.append(response_ms)
        self._count += 1
        if self._count >= self.window:
            self._close_window()

    def _close_window(self) -> None:
        median = statistics.median(self._times) if self._times else None
        if not self._have_baseline:
            self._baseline = median
            self._have_baseline = True
        elif median is not None and self._baseline and median > SLOW_RATIO * self._baseline:
            self._cut()
            return
        elif not self._failed_in_window and (
            median is None or not self._baseline or median <= HEALTHY_RATIO * self._baseline
        ):
            self.limit = min(self.limit + self.growth, self.maximum)
        self._reset_window()

    def _cut(self) -> None:
        self._in_flight_at_cut = self.limit
        self.limit = max(self.limit // 2, self.minimum)
        self._since_cut = 0
        self._reset_window()

    def _reset_window(self) -> None:
        self._times = []
        self._count = 0
        self._failed_in_window = False
