"""Local Lighthouse: the fallback when PageSpeed Insights isn't available.

Run as `node <lighthouse>/cli/index.js`, never through npx or a .cmd shim. On
Windows those are batch files, and cmd.exe would interpret characters like `&`
in a crawled URL. Lighthouse must be installed once with
`npm i -g lighthouse@12`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.vitals.model import VitalsResult, rate
from app.vitals.psi import parse_lab


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
    return None


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


class LighthouseProvider:
    name = "lighthouse"

    def __init__(self, chrome_path: str, cli_path: str, node_path: str, timeout: int = 90) -> None:
        self.chrome_path = chrome_path
        self.cli_path = cli_path
        self.node_path = node_path
        self.timeout = timeout

    def command(self, url: str, strategy: str = "mobile") -> List[str]:
        cmd = [self.node_path, self.cli_path, url, "--output=json", "--output-path=stdout",
               "--only-categories=performance", "--quiet",
               "--chrome-flags=--headless=new --no-sandbox"]
        if strategy == "desktop":
            cmd.append("--preset=desktop")
        return cmd

    def measure(self, url: str, strategy: str = "mobile") -> VitalsResult:
        def failed(message: str) -> VitalsResult:
            return VitalsResult(url=url, strategy=strategy, source="lighthouse", error=message)

        try:
            proc = subprocess.run(
                self.command(url, strategy), capture_output=True, text=True, encoding="utf-8",
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
        return parse_lighthouse(url, strategy, lhr)
