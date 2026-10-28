"""The vendored axe-core (see vendor/README.md) and how it's run."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

VENDOR = Path(__file__).resolve().parent / "vendor"


def _version() -> str:
    try:
        return (VENDOR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


AXE_VERSION = _version()
AXE_TAGS: List[str] = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
# Evaluated with page.evaluate, not injected as a <script> tag: a page's
# Content-Security-Policy can block injected scripts, not evaluation.
AXE_RUN = ("async (tags) => await axe.run(document, "
           "{runOnly: {type: 'tag', values: tags}, resultTypes: ['violations']})")


@lru_cache(maxsize=1)
def axe_source() -> str:
    return (VENDOR / "axe.min.js").read_text(encoding="utf-8")


def axe_available() -> Tuple[bool, str]:
    if (VENDOR / "axe.min.js").exists():
        return True, ""
    return False, "axe-core not found (app/accessibility/vendor/axe.min.js)"
