import time
import asyncio
from typing import Dict, Any
from app.crawler.crawler import Crawler
from app.auditor import checks
from app.analysis import analysis
from app.ai import ai_suggestions
from app.utils import performance, report
from app.models.session_model import session_store
from app.websocket.ws_manager import ws_manager


current_crawler: Crawler | None = None

def run_full_audit(
    url: str,
    max_pages: int = 15,
    max_depth: int = 2,
    ignore_robots: bool = False,
    progress_callback=None,
    event_callback=None,
) -> Dict[str, Any]:
    global current_crawler
    crawler = Crawler(
        start_url=url,
        max_pages=max_pages,
        max_depth=max_depth,
        respect_robots=not ignore_robots,
        concurrency=10,
        timeout=10,
        retries=1,
    )

    current_crawler = crawler

    crawler.crawl(progress_callback=progress_callback, event_callback=event_callback)
    crawler.check_external_links(max_check=25)

    all_page_issues = {}
    page_meta = {}
    page_data_for_dupes = []

    for page_url, page in crawler.results.items():
        issues = []
        issues += checks.check_status_and_https(page, {})
        issues += checks.check_mixed_content(page)
        canon_issues, canonical = checks.check_canonical(page, page_url)
        issues += canon_issues
        issues += checks.check_indexability(page)

        title_issues, title = checks.check_title(page)
        issues += title_issues
        desc_issues, desc = checks.check_meta_description(page)
        issues += desc_issues
        heading_issues, h1 = checks.check_headings(page)
        issues += heading_issues
        issues += checks.check_images(page)
        issues += checks.check_links(page)
        issues += checks.check_structured_data(page)
        issues += checks.check_open_graph_twitter(page)
        issues += checks.check_url_structure(page_url)

        content_issues, content_stats = checks.check_content(page)
        issues += content_issues

        issues += checks.check_mobile(page)
        issues += checks.check_accessibility(page)
        issues += checks.check_security_headers(page)
        issues += checks.check_hreflang(page)
        issues += checks.check_media(page)
        issues += checks.check_js_rendering_signal(page)

        weight = performance.analyze_page_weight(page)
        issues += performance.check_performance_proxies(page, weight)

        soup = checks._soup(page.html)
        meta_robots = None
        lang = None
        open_graph = {}
        twitter_cards = {}
        h2_count = 0
        h3_count = 0
        heading_hierarchy = []
        images_count = 0
        missing_alt_count = 0
        structured_data = []
        security_headers = {}

        if soup:
            html_el = soup.find("html")
            lang = html_el.get("lang") if html_el else None
            robots_tag = soup.find("meta", attrs={"name": "robots"})
            meta_robots = robots_tag.get("content") if robots_tag else None

            for meta_tag in soup.find_all("meta"):
                prop = meta_tag.get("property", "")
                name = meta_tag.get("name", "")
                content = meta_tag.get("content", "")
                if prop.startswith("og:"):
                    open_graph[prop] = content
                if name.startswith("twitter:"):
                    twitter_cards[name] = content

            h2s = soup.find_all("h2")
            h3s = soup.find_all("h3")
            h2_count = len(h2s)
            h3_count = len(h3s)

            for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                text = h.get_text(strip=True)
                if text:
                    level = int(h.name[1])
                    heading_hierarchy.append({"level": level, "text": text[:100]})

            imgs = soup.find_all("img")
            images_count = len(imgs)
            missing_alt_count = sum(1 for img in imgs if not img.get("alt", "").strip())

            for script in soup.find_all("script", type="application/ld+json"):
                if script.string:
                    structured_data.append({"type": "JSON-LD", "raw": script.string.strip()[:500]})

        if page.headers:
            headers_lower = {k.lower(): v for k, v in page.headers.items()}
            for h in ("strict-transport-security", "content-security-policy", "x-frame-options", "x-content-type-options", "referrer-policy"):
                security_headers[h] = headers_lower.get(h, False)

        int_links = len(crawler.link_graph.get(page_url, set()))
        ext_links = len([u for u in crawler.external_links_checked if page_url in crawler.inbound_links.get(u, set())])
        word_cnt = content_stats.get("word_count", 0)

        all_page_issues[page_url] = issues
        page_meta[page_url] = {
            "title": title,
            "meta_description": desc,
            "h1": h1,
            "word_count": word_cnt,
            "canonical": canonical,
            "performance": weight,
            "meta_robots": meta_robots,
            "lang": lang,
            "open_graph": open_graph,
            "twitter_cards": twitter_cards,
            "h2_count": h2_count,
            "h3_count": h3_count,
            "heading_hierarchy": heading_hierarchy,
            "char_count": len(content_stats.get("text", "")),
            "reading_time_mins": max(1, round(word_cnt / 200)) if word_cnt else 0,
            "internal_links_count": int_links,
            "external_links_count": ext_links,
            "images_count": images_count,
            "missing_alt_count": missing_alt_count,
            "structured_data": structured_data,
            "security_headers": security_headers,
        }
        page_data_for_dupes.append({
            "url": page_url,
            "title": title,
            "meta_description": desc,
            "h1": h1,
            "canonical": canonical,
            "content_hash": analysis.content_hash(content_stats["text"]) if content_stats["text"] else None,
            "text": content_stats["text"],
        })

    site_wide = analysis.build_link_graph_stats(crawler)
    duplicates = analysis.find_duplicates(page_data_for_dupes)
    near_dupes = analysis.near_duplicate_content(page_data_for_dupes)
    redirects = analysis.redirect_report(crawler)
    broken_links = analysis.broken_link_report(crawler)

    recommendations = ai_suggestions.generate_recommendations(all_page_issues, site_wide)
    issue_freq = ai_suggestions.issue_frequency_summary(all_page_issues)

    exec_summary = report.build_executive_summary(
        crawler, all_page_issues, site_wide, duplicates, redirects, broken_links, recommendations
    )
    page_rows = report.build_page_level_report(crawler, all_page_issues, page_meta)

    arch_nodes = []
    arch_links = []
    orphan_set = set(site_wide.get("orphan_pages", []))
    dead_end_set = set(site_wide.get("dead_end_pages", []))
    broken_set = {b["url"] for b in broken_links}
    hub_set = {h[0] for h in site_wide.get("hub_pages_over_linked", [])}

    for url, res in crawler.results.items():
        arch_nodes.append({
            "id": url,
            "url": url,
            "label": url.replace("https://", "").replace("http://", "").split("?")[0],
            "depth": res.depth,
            "isBroken": url in broken_set or (res.status_code is not None and res.status_code >= 400),
            "isOrphan": url in orphan_set,
            "isDeadEnd": url in dead_end_set,
            "isDeep": res.depth >= 3,
            "isHub": url in hub_set,
            "inboundCount": len(crawler.inbound_links.get(url, set())),
            "outboundCount": len(crawler.link_graph.get(url, set())),
        })

    for src, targets in crawler.link_graph.items():
        for tgt in targets:
            if tgt in crawler.results:
                arch_links.append({"source": src, "target": tgt})

    result_data = {
        "executive_summary": exec_summary,
        "site_wide_analysis": site_wide,
        "duplicates": duplicates,
        "near_duplicate_content": near_dupes,
        "redirects": redirects,
        "broken_links": broken_links,
        "recommendations": recommendations,
        "issue_frequency": issue_freq,
        "pages": page_rows,
        "architecture": {
            "nodes": arch_nodes,
            "links": arch_links,
        },
        "page_issues_detail": {u: v for u, v in all_page_issues.items()},
        "robots_txt": crawler.robots_txt_content,
        "sitemaps_found": crawler.sitemaps_found,
        "sitemap_urls": list(crawler.sitemap_urls),
        "elapsed_seconds": round(time.time(), 1),
        "note": "Audit executed directly via native Python engine.",
    }

    session_store.save_session({
        "id": f"sess_{int(time.time())}",
        "url": url,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "auditResult": result_data,
    })

    current_crawler = None
    return result_data
