"""Finding tracked brands and citations in an AI answer. Pure functions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

_DOMAIN = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")
_REDIRECT_HOSTS = ("vertexaisearch.cloud.google.com", "googleusercontent.com")


@dataclass(frozen=True)
class Brand:
    owner: str
    is_self: bool
    terms: Tuple[str, ...]
    domain: str


def _patterns(brand: Brand) -> List[re.Pattern]:
    words = {t.strip() for t in brand.terms if t and t.strip()}
    if brand.domain:
        words |= {brand.domain, f"www.{brand.domain}"}
    return [re.compile(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", re.IGNORECASE) for w in sorted(words, key=len, reverse=True)]


def spans(text: str, brand: Brand) -> List[Tuple[int, int]]:
    found = sorted({(m.start(), m.end()) for p in _patterns(brand) for m in p.finditer(text or "")})
    out: List[Tuple[int, int]] = []
    for start, end in found:                 # keep the longest of overlapping matches
        if out and start < out[-1][1]:
            if end - start > out[-1][1] - out[-1][0]:
                out[-1] = (start, end)
            continue
        out.append((start, end))
    return out


def first_index(text: str, brand: Brand) -> Optional[int]:
    found = spans(text, brand)
    return found[0][0] if found else None


def citation_domain(citation: Dict[str, Any]) -> Optional[str]:
    url = citation.get("url") or ""
    host = (urlsplit(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in _REDIRECT_HOSTS) or "grounding-api-redirect" in url:
        title = (citation.get("title") or "").strip().lower()
        if not _DOMAIN.fullmatch(title):
            return None
        host = title
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


def analyze(text: str, citations: Sequence[Dict[str, Any]], brands: Sequence[Brand]) -> Dict[str, Any]:
    order = sorted(((first_index(text, b), b) for b in brands if first_index(text, b) is not None), key=lambda x: x[0])
    mentioned_owners = [b.owner for _, b in order]
    me = next((b for b in brands if b.is_self), None)
    position = mentioned_owners.index(me.owner) + 1 if me and me.owner in mentioned_owners else None
    domains: List[str] = []
    for c in citations:
        d = citation_domain(c)
        if d and d not in domains:
            domains.append(d)
    cited = bool(me) and any(d == me.domain or d.endswith("." + me.domain) for d in domains)
    return {"mentioned": position is not None, "position": position, "brands_mentioned": mentioned_owners,
            "cited": cited, "cited_domains": domains}


def highlights(text: str, brands: Sequence[Brand]) -> List[Dict[str, Any]]:
    marks = sorted((s, e, b.owner) for b in brands for s, e in spans(text, b))
    out: List[Dict[str, Any]] = []
    for start, end, owner in marks:
        if out and start < out[-1]["end"]:
            continue
        out.append({"start": start, "end": end, "owner": owner})
    return out
