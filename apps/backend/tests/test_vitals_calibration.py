"""Lighthouse's CPU slowdown follows the host's speed (docs/throttling.md:
4x assumes a high-end desktop host; slower hosts need less to imitate the
same mid-tier phone)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.config import config
from app.vitals import lighthouse
from app.vitals.lighthouse import LighthouseProvider, recommended_slowdown

FLAG = "--throttling.cpuSlowdownMultiplier="


def lhr(benchmark_index):
    return {"categories": {"performance": {"score": 0.9}}, "environment": {"benchmarkIndex": benchmark_index},
            "audits": {"largest-contentful-paint": {"numericValue": 1800}, "total-blocking-time": {"numericValue": 90},
                       "cumulative-layout-shift": {"numericValue": 0.0}}}


def runner(*benchmark_indexes):
    """subprocess.run stand-in: each call returns the next host speed."""
    procs = [MagicMock(returncode=0, stdout=json.dumps(lhr(b)), stderr="") for b in benchmark_indexes]
    return patch.object(lighthouse.subprocess, "run", side_effect=procs)


def flags(run):
    return [next((a for a in call.args[0] if a.startswith(FLAG)), None) for call in run.call_args_list]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(config, "LIGHTHOUSE_CPU_SLOWDOWN", "auto")
    lighthouse.reset_calibration()


def provider():
    return LighthouseProvider("C:/chrome.exe", "C:/lh/cli/index.js", "C:/node.exe")


@pytest.mark.parametrize("index, expected", [(2400, 4), (1500, 4), (1499, 2), (800, 2), (799, 1), (120, 1), (None, None)])
def test_recommended_slowdown_follows_lighthouse_device_classes(index, expected):
    assert recommended_slowdown(index) == expected


def test_a_slow_host_is_remeasured_once_then_remembered():
    p = provider()
    with runner(600, 600, 610) as run:
        first = p.measure("https://a.com/")
        second = p.measure("https://a.com/b")
    assert flags(run) == [None, f"{FLAG}1", f"{FLAG}1"]          # default 4x, re-run at 1x, then 1x straight away
    assert first.cpu_slowdown == 1 and second.cpu_slowdown == 1


def test_a_fast_host_keeps_the_default():
    with runner(1900) as run:
        r = provider().measure("https://a.com/")
    assert flags(run) == [None] and r.cpu_slowdown == 4


def test_a_fixed_setting_is_used_as_is(monkeypatch):
    monkeypatch.setattr(config, "LIGHTHOUSE_CPU_SLOWDOWN", "2.5")
    with runner(600) as run:
        r = provider().measure("https://a.com/")
    assert flags(run) == [f"{FLAG}2.5"] and r.cpu_slowdown == 2.5


def test_an_unreadable_setting_falls_back_to_auto(monkeypatch):
    monkeypatch.setattr(config, "LIGHTHOUSE_CPU_SLOWDOWN", "fast")
    with runner(1900) as run:
        assert provider().measure("https://a.com/").cpu_slowdown == 4
    assert flags(run) == [None]


def test_desktop_runs_are_left_alone():
    # The desktop preset already measures without CPU slowdown.
    with runner(600) as run:
        r = provider().measure("https://a.com/", "desktop")
    assert flags(run) == [None] and run.call_count == 1 and r.cpu_slowdown is None


def test_a_failed_remeasure_keeps_the_first_result():
    procs = [MagicMock(returncode=0, stdout=json.dumps(lhr(600)), stderr=""), MagicMock(returncode=1, stdout="", stderr="boom")]
    with patch.object(lighthouse.subprocess, "run", side_effect=procs):
        r = provider().measure("https://a.com/")
    assert r.error is None and r.cpu_slowdown == 4 and r.lcp_ms == 1800
