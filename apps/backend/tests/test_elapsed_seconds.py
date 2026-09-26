"""`elapsed_seconds` must be an audit *duration*, not a wall-clock timestamp.

The dashboard renders this value directly as "Completed in {elapsed_seconds}s"
(`apps/frontend/app/dashboard/page.tsx:313`). It was previously assigned
`round(time.time(), 1)` — the Unix epoch — so a finished audit reported
"Completed in 1786810788s", roughly 56,000 years.
"""

import itertools
from unittest.mock import patch

from app.services import audit_service

from test_audit_service_crawler_registry import FakeCrawler


def test_elapsed_seconds_is_a_duration_not_an_epoch_timestamp():
    """The bug this file exists for: an epoch timestamp is ~1.79e9, so any
    plausible-duration bound catches it. A real audit of one fake page takes
    well under a minute."""
    crawler = FakeCrawler()

    result = audit_service._build_audit_result(
        "https://example.com/", crawler, progress_callback=None, event_callback=None,
    )

    elapsed = result["elapsed_seconds"]
    assert elapsed >= 0, "a duration can never be negative"
    assert elapsed < 60, (
        f"elapsed_seconds={elapsed} is not a plausible duration for this audit — "
        "it looks like a wall-clock timestamp"
    )


def test_elapsed_seconds_measures_the_span_across_the_audit():
    """Pins the arithmetic, not just the magnitude: with the clock advanced by a
    known amount, elapsed_seconds must equal that amount. Uses monotonic so the
    value cannot be skewed by a system clock change mid-audit."""
    crawler = FakeCrawler()

    # First call is the start stamp, every later call is the end stamp, so extra
    # calls cannot exhaust the side_effect and the delta stays exactly 2.5.
    clock = itertools.chain([100.0], itertools.repeat(102.5))

    with patch.object(audit_service.time, "monotonic", side_effect=lambda: next(clock)):
        result = audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
        )

    assert result["elapsed_seconds"] == 2.5


def test_generated_session_id_still_uses_wall_clock_time():
    """The session `id` is a wall-clock-derived identifier and must NOT be
    switched to monotonic alongside the elapsed_seconds fix -- monotonic's origin
    is arbitrary, so ids built from it would not be time-ordered across process
    restarts.

    It now names the audit's database file rather than a dict key, which makes
    that ordering matter more, not less.
    """
    crawler = FakeCrawler()

    with patch.object(audit_service.session_store, "open_session") as mock_open,          patch.object(audit_service.time, "time", return_value=1786810788.0):
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
        )

    assert mock_open.call_args.args[0] == "sess_1786810788"


def test_a_supplied_session_id_is_used_as_given():
    """The API generates the id when it starts the audit, so the two must agree:
    a second id invented here would write rows the endpoints cannot find."""
    crawler = FakeCrawler()

    with patch.object(audit_service.session_store, "open_session") as mock_open:
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None,
            event_callback=None, session_id="sess_from_api",
        )

    assert mock_open.call_args.args[0] == "sess_from_api"
