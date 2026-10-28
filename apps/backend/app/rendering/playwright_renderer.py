"""Render pages in headless Chromium through Playwright.

Imported lazily: the default server image has the playwright package but no
browser, and an audit must then report rendering as unavailable, not fail."""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, List, Optional, Tuple

from app.rendering.model import RenderResult

logger = logging.getLogger(__name__)

_BLOCKED = {"image", "media", "font"}
NETWORK_IDLE_MS = 2000


def _load_playwright():
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
    return sync_playwright, PlaywrightTimeout


def _block_heavy(route) -> None:
    """Images, media and fonts change nothing an SEO check reads, and cost
    most of a page's bytes."""
    if route.request.resource_type in _BLOCKED:
        route.abort()
    else:
        route.continue_()


def _short(exc: Exception) -> str:
    first = (str(exc).splitlines() or [""])[0][:200]
    return f"{type(exc).__name__}: {first}" if first else type(exc).__name__


def _chromium_path() -> Tuple[Optional[str], str]:
    try:
        sync_playwright, _ = _load_playwright()
    except ImportError:
        return None, "Playwright is not installed"
    try:
        with sync_playwright() as pw:
            path = pw.chromium.executable_path
    except Exception as exc:
        return None, f"Playwright could not start: {_short(exc)}"
    if not path or not os.path.exists(path):
        return None, "Chromium is not installed (run: python -m playwright install chromium)"
    return path, ""


def renderer_available() -> Tuple[bool, str]:
    path, reason = _chromium_path()
    return (True, "") if path else (False, reason)


def playwright_chromium() -> Optional[str]:
    """Playwright's Chromium binary, if installed -- also used as Lighthouse's Chrome."""
    return _chromium_path()[0]


class PlaywrightRenderer:
    name = "playwright"

    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms

    def render(self, urls: List[str],
               on_progress: Optional[Callable[[int, int, str], None]] = None) -> List[RenderResult]:
        """One browser for the whole batch, one page at a time (the sync API
        is single-threaded). A page's failure is that page's error."""
        sync_playwright, timeout_error = _load_playwright()
        results: List[RenderResult] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for done, url in enumerate(urls, start=1):
                    results.append(self._render_one(browser, url, timeout_error))
                    if on_progress:
                        on_progress(done, len(urls), url)
            finally:
                browser.close()
        return results

    def _render_one(self, browser, url: str, timeout_error) -> RenderResult:
        # A fresh context per page: no cookies, storage or service workers
        # carried from one page to the next, and nothing downloaded.
        context = browser.new_context(java_script_enabled=True, accept_downloads=False,
                                      service_workers="block")
        try:
            page = context.new_page()
            page.route("**/*", _block_heavy)
            started = time.monotonic()
            response = page.goto(url, wait_until="load", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_MS)
            except timeout_error:
                pass  # long-polling pages never go idle; what has rendered by now counts
            html = page.content()
            return RenderResult(url=url, html=html, final_url=page.url,
                                status=response.status if response else None,
                                render_ms=round((time.monotonic() - started) * 1000, 1))
        except Exception as exc:
            logger.warning("Rendering %s failed: %s", url, _short(exc))
            return RenderResult(url=url, error=_short(exc))
        finally:
            context.close()
