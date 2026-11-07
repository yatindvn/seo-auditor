"""Local Lighthouse: the fallback when PageSpeed Insights isn't available.

Run as `node <lighthouse>/cli/index.js`, never through npx or a .cmd shim. On
Windows those are batch files, and cmd.exe would interpret characters like `&`
in a crawled URL. Lighthouse must be installed once with
`npm i -g lighthouse@12`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import config
from app.rendering.playwright_renderer import playwright_chromium
from app.vitals.model import VitalsResult, rate
from app.vitals.psi import parse_lab

logger = logging.getLogger(__name__)


def _chrome_candidates() -> List[str]:
    local = os.environ.get("LOCALAPPDATA", "")
    return [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(local, r"Google\Chrome\Application\chrome.exe") if local else "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]


def find_chrome(explicit: str = "") -> Optional[str]:
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for path in _chrome_candidates():
        if path and os.path.exists(path):
            return path
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    # Last resort: Playwright's own Chromium (the WITH_BROWSER server image has
    # no system Chrome, only this one).
    return playwright_chromium()


def find_lighthouse_cli(explicit: str = "") -> Optional[str]:
    """The Lighthouse CLI entry script: LIGHTHOUSE_CLI, else the global npm
    install (`npm root -g`/lighthouse/cli/index.js)."""
    if explicit:
        return explicit if os.path.exists(explicit) else None
    npm = shutil.which("npm")
    if not npm:
        return None
    try:
        # Fixed arguments only, so running npm's .cmd shim here is safe.
        root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    cli = Path(root) / "lighthouse" / "cli" / "index.js"
    return str(cli) if root and cli.exists() else None


def parse_lighthouse(url: str, strategy: str, lhr: Dict[str, Any]) -> VitalsResult:
    runtime = lhr.get("runtimeError")
    if runtime:
        return VitalsResult(url=url, strategy=strategy, source="lighthouse",
                            error=f"Lighthouse: {runtime.get('message') or runtime.get('code')}")
    result = VitalsResult(url=url, strategy=strategy, source="lighthouse", data_kind="lab", **parse_lab(lhr))
    result.rating = rate(result)
    return result


DEFAULT_SLOWDOWN = 4.0
_calibrated: Optional[float] = None      # this process's host, once measured


def reset_calibration() -> None:
    global _calibrated
    _calibrated = None


def recommended_slowdown(benchmark_index: Optional[float]) -> Optional[float]:
    """The CPU slowdown that makes this host imitate a mid-tier phone, per
    Lighthouse's docs/throttling.md device classes: 4x on a high-end desktop
    (benchmark index 1500+), 2x on a low-end desktop or high-end phone (800+),
    1x on anything slower (already phone-class)."""
    if benchmark_index is None:
        return None
    if benchmark_index >= 1500:
        return 4.0
    if benchmark_index >= 800:
        return 2.0
    return 1.0


def _fixed_slowdown() -> Optional[float]:
    setting = config.LIGHTHOUSE_CPU_SLOWDOWN
    if setting == "auto":
        return None
    try:
        value = float(setting)
    except ValueError:
        logger.warning("LIGHTHOUSE_CPU_SLOWDOWN=%r is not a number or 'auto'; using auto", setting)
        return None
    return value if value > 0 else None


class LighthouseProvider:
    name = "lighthouse"

    def __init__(self, chrome_path: str, cli_path: str, node_path: str, timeout: int = 90) -> None:
        self.chrome_path = chrome_path
        self.cli_path = cli_path
        self.node_path = node_path
        self.timeout = timeout

    def command(self, url: str, strategy: str = "mobile", slowdown: Optional[float] = None) -> List[str]:
        cmd = [self.node_path, self.cli_path, url, "--output=json", "--output-path=stdout",
               "--only-categories=performance", "--quiet",
               "--chrome-flags=--headless=new --no-sandbox"]
        if strategy == "desktop":
            cmd.append("--preset=desktop")
        if slowdown is not None:
            cmd.append(f"--throttling.cpuSlowdownMultiplier={slowdown:g}")
        return cmd

    def measure(self, url: str, strategy: str = "mobile") -> VitalsResult:
        """One page. Mobile runs use a CPU slowdown suited to this host: fixed by
        LIGHTHOUSE_CPU_SLOWDOWN, or calibrated from Lighthouse's own benchmark of
        the host -- the first run that finds the slowdown wrong is re-measured
        once, and later runs use the right one straight away."""
        global _calibrated
        if strategy != "mobile":
            return self._run(url, strategy, None)[0]
        fixed = _fixed_slowdown()
        if fixed is not None:
            result, _ = self._run(url, strategy, fixed)
            if not result.error:
                result.cpu_slowdown = fixed
            return result
        used = _calibrated
        result, index = self._run(url, strategy, used)
        if result.error:
            return result
        applied = used if used is not None else DEFAULT_SLOWDOWN
        result.cpu_slowdown = applied
        right = recommended_slowdown(index)
        if right is None:
            return result
        _calibrated = right
        if right == applied:
            return result
        logger.info("Lighthouse: host benchmark index %s, re-measuring %s at %gx CPU slowdown", index, url, right)
        again, _ = self._run(url, strategy, right)
        if again.error:
            return result
        again.cpu_slowdown = right
        return again

    def _run(self, url: str, strategy: str, slowdown: Optional[float]) -> Tuple[VitalsResult, Optional[float]]:
        """One Lighthouse run: the result and the host's benchmark index."""
        def failed(message: str) -> Tuple[VitalsResult, Optional[float]]:
            return VitalsResult(url=url, strategy=strategy, source="lighthouse", error=message), None

        try:
            proc = subprocess.run(
                self.command(url, strategy, slowdown), capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=self.timeout, env={**os.environ, "CHROME_PATH": self.chrome_path},
            )
        except subprocess.TimeoutExpired:
            return failed(f"Lighthouse timed out after {self.timeout}s")
        except OSError as exc:
            return failed(f"Lighthouse could not start: {type(exc).__name__}")
        if proc.returncode != 0:
            return failed(f"Lighthouse failed (exit {proc.returncode}): {(proc.stderr or '').strip()[-200:]}")
        try:
            lhr = json.loads(proc.stdout)
        except ValueError:
            return failed("Lighthouse returned no JSON")
        index = (lhr.get("environment") or {}).get("benchmarkIndex")
        return parse_lighthouse(url, strategy, lhr), (float(index) if isinstance(index, (int, float)) else None)
