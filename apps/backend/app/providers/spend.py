"""The spend guard: a hard daily cap on provider calls, counted in the DB so it
survives restarts and holds across threads and processes."""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db.engine import get_session_factory
from app.db.models import ProviderUsage, utcnow
from app.providers.serp import ProviderSkipped, SerpQuery, SerpResult


def reserve(provider_name: str, cap: int, factory=None, today: Optional[date] = None) -> None:
    """Take one unit of today's budget, or raise ProviderSkipped. A unit is
    never refunded: a call that errored may still have been billed."""
    factory = factory or get_session_factory()
    day = today or utcnow().date()
    with factory.begin() as session:
        if session.scalar(select(ProviderUsage.id).where(
            ProviderUsage.provider == provider_name, ProviderUsage.day == day,
        )) is None:
            try:
                with session.begin_nested():
                    session.add(ProviderUsage(provider=provider_name, day=day, calls=0))
            except IntegrityError:
                pass  # another caller created today's row first
        claimed = session.execute(
            update(ProviderUsage)
            .where(ProviderUsage.provider == provider_name, ProviderUsage.day == day,
                   ProviderUsage.calls < cap)
            .values(calls=ProviderUsage.calls + 1)
        ).rowcount
    if claimed != 1:
        raise ProviderSkipped(f"daily cap of {cap} {provider_name} calls reached")


class SpendGuard:
    def __init__(self, provider, cap: int) -> None:
        self.provider = provider
        self.cap = cap
        self.name = provider.name

    def search(self, query: SerpQuery) -> SerpResult:
        reserve(self.name, self.cap)
        return self.provider.search(query)
