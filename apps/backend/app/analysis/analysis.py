"""
analysis.py — Site-wide (cross-page) analysis.

- Internal link graph + orphan page detection + crawl/click depth
- PageRank-style importance approximation (via networkx if available)
- Duplicate title / description / H1 / content / canonical detection
- Redirect chain / loop aggregation across the whole site
- Broken internal link aggregation
"""

from __future__ import annotations

import math

import hashlib
from collections import defaultdict
from typing import Dict, List

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


def build_link_graph_stats(crawler) -> Dict:
    graph = crawler.link_graph
    all_pages = set(crawler.results.keys())
    inbound = crawler.inbound_links

    orphan_pages = sorted(
        [u for u in all_pages if len(inbound.get(u, set())) == 0 and u != crawler.start_url]
    )

    pages_no_outbound = sorted([u for u in all_pages if not graph.get(u)])

    over_linked = sorted(
        [(u, len(children)) for u, children in graph.items() if len(children) > 150],
        key=lambda x: -x[1],
    )

    depth_map = {u: r.depth for u, r in crawler.results.items()}
    max_depth_seen = max(depth_map.values()) if depth_map else 0

    pagerank = {}
    if HAS_NETWORKX and graph:
        g = nx.DiGraph()
        g.add_nodes_from(all_pages)
        for src, targets in graph.items():
            for t in targets:
                if t in all_pages:
                    g.add_edge(src, t)
        try:
            pagerank = nx.pagerank(g, alpha=0.85)
        except Exception:
            pagerank = {}

    top_pages = sorted(pagerank.items(), key=lambda x: -x[1])[:20] if pagerank else []

    return {
        "total_pages": len(all_pages),
        "orphan_pages": orphan_pages,
        "orphan_count": len(orphan_pages),
        "dead_end_pages": pages_no_outbound,
        "dead_end_count": len(pages_no_outbound),
        "hub_pages_over_linked": over_linked[:20],
        "max_crawl_depth": max_depth_seen,
        "depth_distribution": _depth_distribution(depth_map),
        "top_pages_by_importance": [{"url": u, "score": round(s, 5)} for u, s in top_pages],
        "pagerank_available": HAS_NETWORKX,
    }


def _depth_distribution(depth_map: Dict[str, int]) -> Dict[int, int]:
    dist = defaultdict(int)
    for d in depth_map.values():
        dist[d] += 1
    return dict(sorted(dist.items()))


def find_duplicates(page_data: List[Dict]) -> Dict:
    """page_data: list of {url, title, meta_description, h1, content_hash, canonical}"""
    def group_by(key):
        groups = defaultdict(list)
        for p in page_data:
            val = p.get(key)
            if val:
                groups[val].append(p["url"])
        return {k: v for k, v in groups.items() if len(v) > 1}

    return {
        "duplicate_titles": group_by("title"),
        "duplicate_meta_descriptions": group_by("meta_description"),
        "duplicate_h1": group_by("h1"),
        "duplicate_content": group_by("content_hash"),
        "duplicate_canonicals": group_by("canonical"),
    }


def content_hash(text: str) -> str:
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()[:16]


def near_duplicate_content(page_data: List[Dict], shingle_size: int = 5, threshold: float = 0.85) -> List[Dict]:
    """Near-duplicate detection by Jaccard similarity over word shingles.

    Exact: this returns the same pairs a brute-force all-against-all comparison
    would, but prunes the candidate set first so it is usable on a full-site
    crawl. The previous implementation was openly O(n^2) -- at the 5000-page
    preset that is ~12.5 million pairwise set operations, which pinned a CPU
    core indefinitely and meant the audit never returned.

    Three things do the work:

    * Shingles are stored as 64-bit hashes rather than joined strings, which
      cuts memory sharply and makes the set operations faster.
    * Size filter: J(A,B) >= t requires |B| >= t*|A|, so pages are processed in
      increasing size order and anything too small to qualify is skipped.
    * Prefix filter: with a consistent global token order, two sets whose
      Jaccard is >= t must share at least one token within their prefixes
      (|X| - ceil(t*|X|) + 1 tokens). Only prefixes go into the inverted index,
      so most pairs are never compared at all.

    Both filters are lossless -- they can only exclude pairs that could not have
    met the threshold -- so every surviving candidate is still verified with a
    real Jaccard computation before being reported.
    """

    def shingle_hashes(text: str) -> set:
        # hash() is SipHash-64 here: fast, and collisions are negligible at this
        # scale. Values are only compared within a single process, so per-process
        # hash randomisation does not matter.
        words = text.lower().split()
        limit = max(len(words) - shingle_size + 1, 1)
        return {hash(" ".join(words[i:i + shingle_size])) for i in range(limit)}

    shingle_sets = {}
    original_order = {}
    for position, page in enumerate(page_data):
        text = page.get("text")
        if not text:
            continue
        url = page["url"]
        tokens = shingle_hashes(text)
        if tokens:
            shingle_sets[url] = tokens
            original_order[url] = position

    # Ascending size makes the size filter one-sided: anything already indexed is
    # no larger than the page being probed.
    urls = sorted(shingle_sets, key=lambda u: len(shingle_sets[u]))
    prefixes = {}
    for url in urls:
        size = len(shingle_sets[url])
        prefix_len = size - math.ceil(threshold * size) + 1
        prefixes[url] = sorted(shingle_sets[url])[:max(prefix_len, 1)]

    index: Dict[int, List[str]] = {}
    pairs = []
    for url in urls:
        current = shingle_sets[url]
        size = len(current)
        smallest_possible_partner = threshold * size

        candidates = set()
        for token in prefixes[url]:
            bucket = index.get(token)
            if bucket:
                candidates.update(bucket)

        for other in candidates:
            other_set = shingle_sets[other]
            if len(other_set) < smallest_possible_partner:
                continue
            intersection = len(current & other_set)
            union = size + len(other_set) - intersection
            if not union:
                continue
            similarity = intersection / union
            if similarity >= threshold:
                # Emit in the caller's page order so output is independent of the
                # size ordering used internally.
                a, b = (other, url) if original_order[other] < original_order[url] else (url, other)
                pairs.append({"url_a": a, "url_b": b, "similarity": round(similarity, 3)})

        for token in prefixes[url]:
            index.setdefault(token, []).append(url)

    return pairs


def redirect_report(crawler) -> Dict:
    chains = []
    loops = []
    for url, result in crawler.results.items():
        if result.redirect_chain:
            entry = {"start_url": url, "hops": result.redirect_chain, "final_status": result.status_code}
            if len(result.redirect_chain) > 1:
                chains.append(entry)
            seen = set()
            for hop in result.redirect_chain:
                if hop["from"] in seen:
                    loops.append(entry)
                    break
                seen.add(hop["from"])
    return {"redirect_chains": chains, "redirect_loops": loops, "total_redirecting_urls": len(
        [r for r in crawler.results.values() if r.redirect_chain]
    )}


def broken_link_report(crawler) -> List[Dict]:
    broken = []
    for url, result in crawler.results.items():
        if result.error or (result.status_code and result.status_code >= 400):
            referrers = sorted(crawler.inbound_links.get(url, set()))
            broken.append({
                "url": url,
                "status": result.status_code,
                "error": result.error,
                "linked_from": referrers[:10],
                "linked_from_count": len(referrers),
            })
    for ext_url, status in crawler.external_links_checked.items():
        if status is None or status >= 400:
            referrers = sorted(crawler.inbound_links.get(ext_url, set()))
            broken.append({
                "url": ext_url,
                "status": status,
                "error": "unreachable" if status is None else None,
                "linked_from": referrers[:10],
                "linked_from_count": len(referrers),
                "external": True,
            })
    return broken
