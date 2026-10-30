"""
ai_suggestions.py — Rule-based recommendation / prioritization engine.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List

IMPACT_WEIGHTS = {
    "FETCH_ERROR": 10, "NO_RESPONSE": 10, "STATUS_404": 9, "STATUS_500": 10,
    "REDIRECT_LOOP": 10, "NO_HTTPS": 9, "MISSING_TITLE": 8, "EMPTY_TITLE": 8,
    "MISSING_VIEWPORT": 8, "MISSING_H1": 6, "MULTIPLE_H1": 4,
    "MISSING_META_DESCRIPTION": 5, "MISSING_CANONICAL": 6, "MULTIPLE_CANONICALS": 6,
    "NOINDEX": 7, "THIN_CONTENT": 6, "MISSING_ALT": 4, "REDIRECT_CHAIN": 5,
    "MIXED_CONTENT": 6, "A11Y_IMG_NO_ALT_ATTR": 4, "A11Y_UNLABELED_FORM_FIELD": 4,
    "SLOW_TTFB": 6, "LARGE_DOM": 4, "NO_STRUCTURED_DATA": 3, "DUPLICATE_TITLE": 6,
    "DUPLICATE_CONTENT": 7, "MISSING_HEADER_STRICT_TRANSPORT_SECURITY": 4,
    "POSSIBLE_CSR_ONLY": 5, "NO_COMPRESSION": 4, "RENDER_BLOCKING_CSS": 3,
    "RENDER_BLOCKING_JS": 3, "TITLE_TOO_LONG": 2, "TITLE_TOO_SHORT": 2,
    "META_DESC_TOO_LONG": 2, "META_DESC_TOO_SHORT": 2,
    "CWV_LCP_POOR": 7, "CWV_INP_POOR": 7, "CWV_CLS_POOR": 7, "CWV_TBT_POOR": 5,
    "CWV_LCP_NEEDS_IMPROVEMENT": 3, "CWV_INP_NEEDS_IMPROVEMENT": 3,
    "CWV_CLS_NEEDS_IMPROVEMENT": 3, "CWV_TBT_NEEDS_IMPROVEMENT": 2,
    "JS_CONTENT_DEPENDENT": 6, "JS_ROBOTS_CHANGED": 8, "JS_CANONICAL_CHANGED": 7, "JS_TITLE_CHANGED": 5,
    "JS_META_DESCRIPTION_CHANGED": 2, "JS_H1_CHANGED": 2, "JS_ONLY_LINKS": 3,
    "GSC_NOT_INDEXED": 8, "GSC_CANONICAL_MISMATCH": 4,
}

RECOMMENDATION_TEXT = {
    "FETCH_ERROR": "Fix the server/network error preventing this page from loading.",
    "STATUS_404": "Fix or redirect this broken page (404) to relevant content.",
    "STATUS_500": "Investigate and fix the server error on this page.",
    "REDIRECT_LOOP": "Break the redirect loop — it prevents users and crawlers from reaching the page.",
    "REDIRECT_CHAIN": "Shorten the redirect chain to a single hop to preserve link equity and speed.",
    "NO_HTTPS": "Migrate this page to HTTPS and set up an HTTP -> HTTPS redirect.",
    "MIXED_CONTENT": "Update insecure (http://) resource references to https:// to avoid mixed-content warnings.",
    "MISSING_TITLE": "Add a unique, descriptive <title> tag (50-60 characters).",
    "EMPTY_TITLE": "The title tag is empty - add descriptive text.",
    "TITLE_TOO_LONG": "Shorten the title so it isn't truncated in search results.",
    "TITLE_TOO_SHORT": "Expand the title to better describe the page (aim for 50-60 characters).",
    "MULTIPLE_TITLES": "Remove duplicate <title> tags - only one should exist per page.",
    "MISSING_META_DESCRIPTION": "Add a compelling meta description (~150-160 characters).",
    "META_DESC_TOO_LONG": "Shorten the meta description to avoid truncation in SERPs.",
    "META_DESC_TOO_SHORT": "Expand the meta description for better click-through rate.",
    "MISSING_H1": "Add a single, descriptive H1 heading to the page.",
    "MULTIPLE_H1": "Consolidate to a single H1; use H2/H3 for subsections.",
    "EMPTY_H1": "The H1 tag has no text - add descriptive heading text.",
    "HEADING_HIERARCHY_SKIP": "Fix heading order so levels don't skip (e.g. H2 -> H4).",
    "MISSING_ALT": "Add descriptive alt text to images for accessibility and image SEO.",
    "MISSING_IMG_DIMENSIONS": "Add width/height attributes to images to prevent layout shift (CLS).",
    "NO_LAZY_LOADING": "Add loading=\"lazy\" to below-the-fold images to improve load performance.",
    "MISSING_CANONICAL": "Add a self-referencing canonical tag to clarify the preferred URL.",
    "MULTIPLE_CANONICALS": "Keep only one canonical tag per page.",
    "CANONICAL_ELSEWHERE": "Verify the canonical target is correct and intended.",
    "NOINDEX": "Confirm this page is intentionally excluded from search indexing.",
    "NOFOLLOW": "Confirm links on this page are intentionally not being followed.",
    "THIN_CONTENT": "Expand this page with more substantive, useful content.",
    "DUPLICATE_TITLE": "Write a unique title for each of these duplicate pages.",
    "DUPLICATE_CONTENT": "Differentiate or canonicalize duplicate-content pages to avoid cannibalization.",
    "NO_STRUCTURED_DATA": "Add JSON-LD structured data (e.g. Article, Product, FAQ) where relevant.",
    "INVALID_JSON_LD": "Fix the malformed JSON-LD so search engines can parse it.",
    "MISSING_OG_TITLE": "Add an og:title tag for better social-share previews.",
    "MISSING_OG_IMAGE": "Add an og:image tag so shared links show a preview image.",
    "MISSING_TWITTER_CARD": "Add a twitter:card meta tag for Twitter/X share previews.",
    "MISSING_VIEWPORT": "Add a responsive viewport meta tag - this page is not mobile-friendly.",
    "VIEWPORT_MISCONFIGURED": "Set the viewport to width=device-width, initial-scale=1.",
    "A11Y_IMG_NO_ALT_ATTR": "Add an alt attribute to every image (empty alt=\"\" is fine for decorative images).",
    "A11Y_UNLABELED_FORM_FIELD": "Associate a <label> or aria-label with every form field.",
    "A11Y_MISSING_LANG": "Add a lang attribute to the <html> tag.",
    "SLOW_TTFB": "Improve server response time (caching, CDN, backend optimization).",
    "CWV_LCP_POOR": "Speed up the largest element: optimise the hero image, preload it, and cut server response time.",
    "CWV_LCP_NEEDS_IMPROVEMENT": "Speed up the largest element: optimise the hero image, preload it, and cut server response time.",
    "CWV_INP_POOR": "Break up long JavaScript tasks and defer non-critical scripts so the page responds to input quickly.",
    "CWV_INP_NEEDS_IMPROVEMENT": "Break up long JavaScript tasks and defer non-critical scripts so the page responds to input quickly.",
    "CWV_CLS_POOR": "Reserve space for images, ads and embeds (width/height or aspect-ratio) so the layout doesn't shift.",
    "CWV_CLS_NEEDS_IMPROVEMENT": "Reserve space for images, ads and embeds (width/height or aspect-ratio) so the layout doesn't shift.",
    "CWV_TBT_POOR": "Reduce main-thread JavaScript work (split bundles, remove unused code) to unblock the page.",
    "CWV_TBT_NEEDS_IMPROVEMENT": "Reduce main-thread JavaScript work (split bundles, remove unused code) to unblock the page.",
    "JS_CONTENT_DEPENDENT": "Server-render (SSR/SSG) the main content so it is in the HTML, not only after JavaScript runs.",
    "JS_ROBOTS_CHANGED": "Set meta robots in the server HTML; changing it with JavaScript gives crawlers conflicting signals.",
    "JS_CANONICAL_CHANGED": "Put the final canonical in the server HTML; don't change it with JavaScript.",
    "JS_TITLE_CHANGED": "Render the real title on the server so every crawler and social preview sees it.",
    "JS_META_DESCRIPTION_CHANGED": "Render the meta description on the server.",
    "JS_H1_CHANGED": "Render the main heading on the server.",
    "JS_ONLY_LINKS": "Use plain <a href> links in the server HTML so crawlers can discover these pages without JavaScript.",
    "GSC_NOT_INDEXED": "Google isn't indexing this page: check its content quality, internal links and canonical, then request indexing in Search Console.",
    "GSC_CANONICAL_MISMATCH": "Google picked a different canonical: make the canonical, internal links and sitemap agree on one URL.",
    "LARGE_DOM": "Reduce DOM complexity/size to improve rendering performance.",
    "RENDER_BLOCKING_CSS": "Defer or inline critical CSS to reduce render-blocking resources.",
    "RENDER_BLOCKING_JS": "Add async/defer to non-critical scripts.",
    "NO_COMPRESSION": "Enable gzip/Brotli compression on the server.",
    "NO_CACHE_HEADER": "Set Cache-Control headers to leverage browser caching.",
    "POSSIBLE_CSR_ONLY": "Consider server-side rendering or pre-rendering so content is visible without JS.",
    "MISSING_HEADER_STRICT_TRANSPORT_SECURITY": "Add a Strict-Transport-Security header to enforce HTTPS.",
    "MISSING_HEADER_CONTENT_SECURITY_POLICY": "Add a Content-Security-Policy header to mitigate XSS risk.",
    "MISSING_HEADER_X_FRAME_OPTIONS": "Add an X-Frame-Options header to prevent clickjacking.",
    "DUPLICATE_HREFLANG": "Remove duplicate hreflang declarations.",
    "NO_X_DEFAULT": "Add an x-default hreflang for users outside targeted locales.",
    "URL_UPPERCASE": "Use lowercase URLs to avoid duplicate-content issues on case-sensitive servers.",
    "URL_UNDERSCORE": "Use hyphens instead of underscores as word separators in URLs.",
    "TOO_MANY_PARAMS": "Simplify the URL / use canonical tags to consolidate parameterized variants.",
}


A11Y_RECOMMENDATION = ("Fix this accessibility problem: the Accessibility section on the Site Audit "
                       "tab lists the affected elements and links to how to fix it.")


def recommendation_text(code: str):
    """Per-code advice; axe rule codes (A11Y_*) share one pointer to their details."""
    if code in RECOMMENDATION_TEXT:
        return RECOMMENDATION_TEXT[code]
    return A11Y_RECOMMENDATION if code.startswith("A11Y_") else None


def generate_recommendations(all_page_issues: Dict[str, List[Dict]], site_wide_findings: Dict) -> List[Dict]:
    code_pages = {}
    code_severity = {}
    for url, issues in all_page_issues.items():
        for iss in issues:
            code = iss["code"]
            code_pages.setdefault(code, set()).add(url)
            code_severity[code] = iss["severity"]

    recs = []
    for code, pages in code_pages.items():
        weight = IMPACT_WEIGHTS.get(code, 2)
        severity = code_severity.get(code, "info")
        affected = len(pages)
        priority_score = weight * min(affected, 50)

        impact = "High" if weight >= 7 else ("Medium" if weight >= 4 else "Low")
        effort = "Quick Win" if code in ("MISSING_TITLE", "MISSING_ALT", "MISSING_CANONICAL", "A11Y_MISSING_LANG") else ("Major" if weight >= 8 else "Moderate")

        recs.append({
            "code": code,
            "severity": severity,
            "affected_pages": affected,
            "example_urls": sorted(pages)[:5],
            "recommendation": recommendation_text(code) or f"Review and resolve: {code}",
            "priority_score": priority_score,
            "impact": impact,
            "estimated_effort": effort,
            "description": f"Detected {affected} instances of {code} across audited pages.",
            "suggested_resolution": recommendation_text(code) or "Review implementation and apply standard web practices.",
        })

    if site_wide_findings.get("orphan_count", 0) > 0:
        count = site_wide_findings["orphan_count"]
        recs.append({
            "code": "ORPHAN_PAGES",
            "severity": "warning",
            "affected_pages": count,
            "example_urls": site_wide_findings["orphan_pages"][:5],
            "recommendation": "Add internal links to orphan pages so crawlers and users can discover them.",
            "priority_score": IMPACT_WEIGHTS.get("MISSING_CANONICAL", 6) * min(count, 50),
            "impact": "High",
            "estimated_effort": "Quick Win",
            "description": f"Found {count} orphan pages without incoming internal links.",
            "suggested_resolution": "Add contextual internal links from relevant category or navigation pages.",
        })

    recs.sort(key=lambda r: -r["priority_score"])
    return recs


def issue_frequency_summary(all_page_issues: Dict[str, List[Dict]]) -> List[Dict]:
    counter = Counter()
    for issues in all_page_issues.values():
        for iss in issues:
            counter[iss["code"]] += 1
    return [{"code": c, "count": n} for c, n in counter.most_common()]
