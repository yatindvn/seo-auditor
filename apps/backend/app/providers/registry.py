"""Which SERP provider to use, and the rule that paid ones start in dry run."""

from __future__ import annotations

import logging

from app.config import config
from app.providers.dry_run import DryRunProvider
from app.providers.serp import ProviderSkipped, SerpProvider
from app.providers.spend import SpendGuard

logger = logging.getLogger("seo_auditor")


def is_live(provider) -> bool:
    return getattr(provider, "name", "dry_run") != "dry_run"


def get_serp_provider(cfg=config) -> SerpProvider:
    name = cfg.SERP_PROVIDER or ("google_cse" if cfg.GOOGLE_CSE_API_KEY and cfg.GOOGLE_CSE_CX else "dry_run")

    if name == "dataforseo":
        if cfg.SERP_DRY_RUN:
            logger.info("SERP_PROVIDER=dataforseo but SERP_DRY_RUN is not 'false': using dry run")
            return DryRunProvider()
        if not (cfg.DATAFORSEO_LOGIN and cfg.DATAFORSEO_PASSWORD):
            raise ProviderSkipped("DataForSEO not configured")
        from app.providers.dataforseo import DataForSeoProvider
        return SpendGuard(DataForSeoProvider(cfg.DATAFORSEO_LOGIN, cfg.DATAFORSEO_PASSWORD),
                          cap=cfg.SERP_DAILY_CAP)

    if name == "google_cse":
        if not (cfg.GOOGLE_CSE_API_KEY and cfg.GOOGLE_CSE_CX):
            raise ProviderSkipped("Google CSE not configured")
        from app.providers.google_cse import GoogleCseProvider
        return SpendGuard(GoogleCseProvider(cfg), cap=cfg.GOOGLE_CSE_DAILY_QUOTA)

    return DryRunProvider()
