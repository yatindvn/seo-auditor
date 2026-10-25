"""AIMD admission control: grow while the site is healthy, halve when it is not."""

from app.crawler.throttle import AdaptiveLimit


def _feed(limit, count, ms=100.0, failed=False, retry_after=None, now=0.0):
    for _ in range(count):
        limit.record(ms, failed, retry_after, now)


def test_starts_at_the_initial_limit():
    assert AdaptiveLimit(initial=32, maximum=64).limit == 32


def test_grows_by_four_after_each_healthy_window():
    limit = AdaptiveLimit(initial=32, maximum=64, window=50)
    _feed(limit, 50)          # first window sets the baseline
    assert limit.limit == 32
    _feed(limit, 50)
    assert limit.limit == 36
    _feed(limit, 50)
    assert limit.limit == 40


def test_never_exceeds_the_maximum():
    limit = AdaptiveLimit(initial=32, maximum=34, window=10)
    _feed(limit, 100)
    assert limit.limit == 34


def test_initial_equal_to_maximum_never_grows():
    limit = AdaptiveLimit(initial=8, maximum=8, window=10)
    _feed(limit, 100)
    assert limit.limit == 8


def test_a_failure_halves_at_once():
    limit = AdaptiveLimit(initial=32, maximum=64)
    limit.record(100.0, True, None, 0.0)
    assert limit.limit == 16


def test_failures_already_in_flight_do_not_halve_again():
    """Requests sent before a cut report their 429s after it; counting them
    would collapse the limit to the minimum on a single burst."""
    limit = AdaptiveLimit(initial=32, maximum=64)
    _feed(limit, 20, failed=True)   # all from the same burst of 32
    assert limit.limit == 16
    _feed(limit, 16)                # the cut has now been "seen" by 16 requests
    limit.record(100.0, True, None, 0.0)
    assert limit.limit == 8


def test_never_below_the_minimum():
    limit = AdaptiveLimit(initial=8, maximum=64, minimum=4)
    for _ in range(10):
        limit.record(100.0, True, None, 0.0)
        _feed(limit, limit.limit)
    assert limit.limit == 4


def test_a_slow_window_halves():
    limit = AdaptiveLimit(initial=32, maximum=64, window=10)
    _feed(limit, 10, ms=100.0)      # baseline 100
    _feed(limit, 10, ms=250.0)      # median 2.5x baseline
    assert limit.limit == 16


def test_a_moderately_slower_window_holds_steady():
    limit = AdaptiveLimit(initial=32, maximum=64, window=10)
    _feed(limit, 10, ms=100.0)
    _feed(limit, 10, ms=180.0)      # 1.8x: not healthy enough to grow, not slow enough to cut
    assert limit.limit == 32


def test_retry_after_pauses_admission_and_is_capped():
    limit = AdaptiveLimit(initial=32, maximum=64)
    limit.record(None, True, 5.0, now=100.0)
    assert limit.paused_until == 105.0
    limit.record(None, True, 600.0, now=200.0)
    assert limit.paused_until == 260.0


def test_responses_without_timing_still_count_as_healthy():
    """Test fakes and some error paths carry no response time."""
    limit = AdaptiveLimit(initial=32, maximum=64, window=10)
    _feed(limit, 20, ms=None)
    assert limit.limit == 36
