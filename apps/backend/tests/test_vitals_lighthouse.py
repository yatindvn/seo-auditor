"""Local Lighthouse (opt-in fallback), the fallback chain, and which
providers an audit gets."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from app.config import config
from app.vitals import lighthouse, providers
from app.vitals.lighthouse import LighthouseProvider, find_chrome, find_lighthouse_cli, parse_lighthouse
from app.vitals.model import VitalsResult
from app.vitals.providers import FallbackChain, build_vitals_provider

LHR = {"categories": {"performance": {"score": 0.9}},
       "audits": {"largest-contentful-paint": {"numericValue": 1800},
                  "cumulative-layout-shift": {"numericValue": 0.01},
                  "total-blocking-time": {"numericValue": 90}}}


def _provider():
    return LighthouseProvider("C:/chrome.exe", "C:/npm/lighthouse/cli/index.js", "C:/node.exe")


def test_the_command_runs_node_directly_never_a_shell_script():
    cmd = _provider().command("https://a.com/?q=1&x=2", "mobile")
    assert cmd[:3] == ["C:/node.exe", "C:/npm/lighthouse/cli/index.js", "https://a.com/?q=1&x=2"]
    assert "--output=json" in cmd and "--output-path=stdout" in cmd
    assert "--only-categories=performance" in cmd


def test_measure_parses_lab_results_and_passes_chrome_path():
    proc = MagicMock(returncode=0, stdout=json.dumps(LHR), stderr="")
    with patch.object(lighthouse.subprocess, "run", return_value=proc) as run:
        r = _provider().measure("https://a.com/")
    args, kwargs = run.call_args
    assert isinstance(args[0], list) and "shell" not in kwargs
    assert kwargs["timeout"] == 90 and kwargs["env"]["CHROME_PATH"] == "C:/chrome.exe"
    assert (r.source, r.data_kind, r.lcp_ms, r.tbt_ms, r.rating) == ("lighthouse", "lab", 1800.0, 90.0, "good")


def test_timeouts_and_failures_become_errors():
    with patch.object(lighthouse.subprocess, "run", side_effect=subprocess.TimeoutExpired("node", 90)):
        assert _provider().measure("https://a.com/").error == "Lighthouse timed out after 90s"
    with patch.object(lighthouse.subprocess, "run", return_value=MagicMock(returncode=1, stdout="", stderr="x" * 500 + "Chrome not found")):
        error = _provider().measure("https://a.com/").error
    assert error.startswith("Lighthouse failed (exit 1): ") and error.endswith("Chrome not found") and len(error) < 260
    with patch.object(lighthouse.subprocess, "run", return_value=MagicMock(returncode=0, stdout="not json", stderr="")):
        assert _provider().measure("https://a.com/").error == "Lighthouse returned no JSON"


def test_a_lighthouse_runtime_error_is_an_error():
    r = parse_lighthouse("https://a.com/", "mobile", {"runtimeError": {"code": "NO_FCP", "message": "No content"}})
    assert r.error == "Lighthouse: No content"


def test_finders_honour_explicit_paths(tmp_path):
    chrome = tmp_path / "chrome.exe"; chrome.write_text("")
    cli = tmp_path / "index.js"; cli.write_text("")
    assert find_chrome(str(chrome)) == str(chrome)
    assert find_chrome(str(tmp_path / "missing")) is None
    assert find_lighthouse_cli(str(cli)) == str(cli)
    assert find_lighthouse_cli(str(tmp_path / "missing.js")) is None


class _Stub:
    def __init__(self, name, result=None, raises=None):
        self.name, self.result, self.raises, self.calls = name, result, raises, 0

    def measure(self, url, strategy="mobile"):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.result


def test_the_chain_returns_the_first_success():
    ok = VitalsResult(url="u", source="lighthouse", data_kind="lab", lcp_ms=1)
    psi = _Stub("psi", VitalsResult(url="u", source="psi", error="PSI returned 500: x"))
    lh = _Stub("lighthouse", ok)
    assert FallbackChain([psi, lh]).measure("u") is ok


def test_the_chain_reports_every_reason_when_all_fail():
    chain = FallbackChain([_Stub("psi", VitalsResult(url="u", error="cap")), _Stub("lighthouse", raises=RuntimeError("boom"))])
    r = chain.measure("u")
    assert r.source == "not_measured" and r.error == "psi: cap; lighthouse: unexpected error (RuntimeError)"


def test_build_returns_none_when_nothing_is_configured():
    assert build_vitals_provider() is None


def test_build_uses_psi_then_lighthouse(monkeypatch):
    monkeypatch.setattr(config, "PSI_API_KEY", "env-key")
    monkeypatch.setattr(config, "LIGHTHOUSE_ENABLED", True)
    monkeypatch.setattr(providers, "find_chrome", lambda explicit="": "C:/chrome.exe")
    monkeypatch.setattr(providers, "find_lighthouse_cli", lambda explicit="": "C:/cli.js")
    monkeypatch.setattr(providers.shutil, "which", lambda name: "C:/node.exe")
    chain = build_vitals_provider()
    assert [p.name for p in chain.providers] == ["psi", "lighthouse"]
    assert chain.providers[0].api_key == "env-key"
    assert build_vitals_provider(psi_key="cli-key").providers[0].api_key == "cli-key"


def test_lighthouse_is_skipped_when_chrome_is_missing(monkeypatch):
    monkeypatch.setattr(config, "LIGHTHOUSE_ENABLED", True)
    monkeypatch.setattr(providers, "find_chrome", lambda explicit="": None)
    monkeypatch.setattr(providers, "find_lighthouse_cli", lambda explicit="": "C:/cli.js")
    assert build_vitals_provider() is None
