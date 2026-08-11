"""
report.py — Aggregation of audit results into health scores, category scores, and page reports.
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from datetime import datetime
from typing import Dict, List


def compute_category_scores(all_page_issues: Dict[str, List[Dict]], total_pages: int) -> Dict[str, float]:
    if total_pages == 0:
        return {
            "technical_seo": 100.0,
            "content": 100.0,
            "internal_linking": 100.0,
            "accessibility": 100.0,
            "performance": 100.0,
            "security": 100.0,
        }

    cat_map = {
        "technical_seo": {"STATUS_", "REDIRECT_", "NO_HTTPS", "FETCH_ERROR", "NOINDEX", "CANONICAL", "URL_"},
        "content": {"THIN_CONTENT", "MISSING_TITLE", "TITLE_", "MISSING_META_DESC", "META_DESC_", "MISSING_H1", "MULTIPLE_H1"},
        "internal_linking": {"ORPHAN", "DEAD_END", "EMPTY_ANCHOR", "BROKEN_LINK"},
        "accessibility": {"A11Y_", "MISSING_ALT", "SMALL_FONT", "MISSING_VIEWPORT"},
        "performance": {"PERF_", "LARGE_HTML", "SLOW_RESPONSE", "NO_LAZY_LOADING", "MISSING_IMG_DIMENSIONS"},
        "security": {"MISSING_HEADER_", "MIXED_CONTENT", "NO_HTTPS"},
    }

    deductions = {cat: 0.0 for cat in cat_map}

    for issues in all_page_issues.values():
        for iss in issues:
            code = iss.get("code", "")
            sev = iss.get("severity", "info")
            weight = 5.0 if sev == "critical" else (2.5 if sev == "warning" else 1.0)
            matched = False
            for cat, codes in cat_map.items():
                if any(c in code for c in codes):
                    deductions[cat] += weight
                    matched = True
            if not matched:
                deductions["technical_seo"] += weight

    scores = {}
    for cat, ded in deductions.items():
        avg = ded / max(total_pages, 1)
        val = max(0.0, min(100.0, round(100.0 - avg * 6.0, 1)))
        scores[cat] = val
    return scores


def compute_health_score(all_page_issues: Dict[str, List[Dict]], total_pages: int) -> Dict:
    """0-100 score with category breakdowns."""
    if total_pages == 0:
        return {
            "score": 0,
            "grade": "N/A",
            "critical_issues": 0,
            "warning_issues": 0,
            "info_issues": 0,
            "categories": {
                "technical_seo": 100,
                "content": 100,
                "internal_linking": 100,
                "accessibility": 100,
                "performance": 100,
                "security": 100,
            },
        }

    sev_weight = {"critical": 5, "warning": 2, "info": 0.5}
    total_deduction = 0
    counts = Counter()
    for issues in all_page_issues.values():
        for iss in issues:
            total_deduction += sev_weight.get(iss["severity"], 1)
            counts[iss["severity"]] += 1

    avg_deduction_per_page = total_deduction / total_pages
    score = max(0, 100 - avg_deduction_per_page * 4)
    score = round(min(score, 100), 1)

    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    elif score >= 40:
        grade = "D"
    else:
        grade = "F"

    categories = compute_category_scores(all_page_issues, total_pages)

    return {
        "score": score,
        "grade": grade,
        "critical_issues": counts.get("critical", 0),
        "warning_issues": counts.get("warning", 0),
        "info_issues": counts.get("info", 0),
        "categories": categories,
    }


def build_executive_summary(crawler, all_page_issues, site_wide, duplicates, redirects, broken_links, recommendations) -> Dict:
    health = compute_health_score(all_page_issues, len(crawler.results))
    status_counts = Counter(r.status_code for r in crawler.results.values())

    return {
        "audit_date": datetime.utcnow().isoformat() + "Z",
        "start_url": crawler.start_url,
        "pages_crawled": len(crawler.results),
        "health_score": health,
        "status_code_breakdown": dict(status_counts),
        "orphan_pages": site_wide.get("orphan_count", 0),
        "broken_links": len(broken_links),
        "redirect_chains": len(redirects.get("redirect_chains", [])),
        "redirect_loops": len(redirects.get("redirect_loops", [])),
        "duplicate_titles": len(duplicates.get("duplicate_titles", {})),
        "duplicate_meta_descriptions": len(duplicates.get("duplicate_meta_descriptions", {})),
        "duplicate_content_groups": len(duplicates.get("duplicate_content", {})),
        "top_recommendations": recommendations[:10],
        "robots_txt_found": crawler.robots_txt_content is not None,
        "robots_txt_content": crawler.robots_txt_content,
        "sitemaps_found": crawler.sitemaps_found,
        "sitemap_url_count": len(crawler.sitemap_urls),
        "sitemap_urls": list(crawler.sitemap_urls),
    }


def build_page_level_report(crawler, all_page_issues, page_meta: Dict[str, Dict]) -> List[Dict]:
    rows = []
    for url, result in crawler.results.items():
        meta = page_meta.get(url, {})
        issues = all_page_issues.get(url, [])
        crit = sum(1 for i in issues if i["severity"] == "critical")
        warn = sum(1 for i in issues if i["severity"] == "warning")
        inf = sum(1 for i in issues if i["severity"] == "info")
        seo_score = max(0, min(100, 100 - (crit * 15 + warn * 5 + inf * 1)))

        rows.append({
            "url": url,
            "status_code": result.status_code,
            "depth": result.depth,
            "response_time_ms": result.response_time_ms,
            "title": meta.get("title"),
            "meta_description": meta.get("meta_description"),
            "h1": meta.get("h1"),
            "word_count": meta.get("word_count", 0),
            "canonical": meta.get("canonical"),
            "critical_issues": crit,
            "warning_issues": warn,
            "info_issues": inf,
            "issue_codes": ", ".join(sorted({i["code"] for i in issues})),

            # Rich Page Data (Phase 1)
            "redirect_chain": result.redirect_chain,
            "redirect_count": len(result.redirect_chain),
            "meta_robots": meta.get("meta_robots"),
            "lang": meta.get("lang"),
            "open_graph": meta.get("open_graph", {}),
            "twitter_cards": meta.get("twitter_cards", {}),
            "h2_count": meta.get("h2_count", 0),
            "h3_count": meta.get("h3_count", 0),
            "heading_hierarchy": meta.get("heading_hierarchy", []),
            "char_count": meta.get("char_count", 0),
            "reading_time_mins": meta.get("reading_time_mins", 0),
            "html_size_bytes": len(result.html.encode("utf-8")) if result.html else 0,
            "internal_links_count": meta.get("internal_links_count", 0),
            "external_links_count": meta.get("external_links_count", 0),
            "images_count": meta.get("images_count", 0),
            "missing_alt_count": meta.get("missing_alt_count", 0),
            "structured_data": meta.get("structured_data", []),
            "last_modified": result.headers.get("Last-Modified") if result.headers else None,
            "security_headers": meta.get("security_headers", {}),
            "seo_score": seo_score,
            "keyword_analysis": meta.get("keyword_analysis"),
        })
    return rows
