"""Provider response cache: a repeat request within its TTL costs nothing.

Callers must not route dry-run providers through here -- made-up data must
never be served later as if it were real.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.engine import get_session_factory
from app.db.models import ProviderCache, as_utc, utcnow


def request_hash(request: dict) -> str:
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cached_call(provider: str, endpoint: str, request: dict, ttl: timedelta,
                fetch: Callable[[], Any], factory=None, now: Optional[datetime] = None) -> Any:
    factory = factory or get_session_factory()
    now = now or utcnow()
    key = request_hash(request)
    where = (ProviderCache.provider == provider, ProviderCache.endpoint == endpoint,
             ProviderCache.request_hash == key)

    with factory() as session:
        row = session.scalar(select(ProviderCache).where(*where))
        if row is not None and as_utc(row.fetched_at) >= now - ttl:
            return row.response_json

    value = fetch()   # raises on failure: nothing is stored

    with factory.begin() as session:
        row = session.scalar(select(ProviderCache).where(*where))
        if row is None:
            try:
                with session.begin_nested():
                    session.add(ProviderCache(provider=provider, endpoint=endpoint, request_hash=key,
                                              response_json=value, fetched_at=now))
            except IntegrityError:
                pass  # a concurrent caller stored it first
        else:
            row.response_json, row.fetched_at = value, now
    return value
