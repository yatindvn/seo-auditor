"""Which Core Web Vitals sources an audit gets, tried in order."""

from __future__ import annotations

import logging
import shutil
from typing import List, Optional

from app.config import config
from app.vitals.lighthouse import LighthouseProvider, find_chrome, find_lighthouse_cli
from app.vitals.model import VitalsProvider, VitalsResult
from app.vitals.psi import PsiProvider

logger = logging.getLogger(__name__)


class FallbackChain:
    """The first provider whose result has no error wins. If they all fail,
    the result is `not_measured`, with every provider's reason."""

    name = "chain"

    def __init__(self, providers: List[VitalsProvider]) -> None:
        self.providers = list(providers)

    def measure(self, url: str, strategy: str = "mobile") -> VitalsResult:
        reasons = []
        for provider in self.providers:
            try:
                result = provider.measure(url, strategy)
            except Exception as exc:
                logger.error("%s failed on %s: %s", provider.name, url, exc, exc_info=exc)
                reasons.append(f"{provider.name}: unexpected error ({type(exc).__name__})")
                continue
            if not result.error:
                return result
            reasons.append(f"{provider.name}: {result.error}")
        return VitalsResult(url=url, strategy=strategy, source="not_measured", error="; ".join(reasons))


def build_vitals_provider(psi_key: Optional[str] = None) -> Optional[FallbackChain]:
    """PSI if a key is set (the CLI's --psi-key overrides PSI_API_KEY), then
    Lighthouse if it's enabled and Chrome, Node and the CLI are all found.
    Returns None when neither is available."""
    chain: List[VitalsProvider] = []
    key = psi_key or config.PSI_API_KEY
    if key:
        chain.append(PsiProvider(key, config.PSI_DAILY_CAP))
    if config.LIGHTHOUSE_ENABLED:
        chrome = find_chrome(config.CHROME_PATH)
        cli = find_lighthouse_cli(config.LIGHTHOUSE_CLI)
        node = shutil.which("node")
        if chrome and cli and node:
            chain.append(LighthouseProvider(chrome, cli, node))
        else:
            missing = [n for n, v in (("Chrome", chrome), ("Lighthouse CLI", cli), ("node", node)) if not v]
            logger.warning("LIGHTHOUSE_ENABLED, but not found: %s", ", ".join(missing))
    return FallbackChain(chain) if chain else None
