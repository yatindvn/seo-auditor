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
        "sitemaps_found": crawler.sitemaps_found,
        "sitemap_url_count": len(crawler.sitemap_urls),
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


def export_json(path, data):
    import json
    js = json.dumps(data, indent=2)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(js)
    return js.encode("utf-8")


def export_csv(path, page_rows):
    import io, csv
    output = io.StringIO()
    if not page_rows:
        return b""
    writer = csv.DictWriter(output, fieldnames=page_rows[0].keys())
    writer.writeheader()
    for row in page_rows:
        writer.writerow({k: str(v) for k, v in row.items()})
    csv_str = output.getvalue()
    if path:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(csv_str)
    return csv_str.encode("utf-8")


def export_excel(path, sheets_dict):
    import io
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)  # remove default sheet
    for sheet_name, rows in sheets_dict.items():
        ws = wb.create_sheet(title=sheet_name[:31])
        if rows:
            if isinstance(rows[0], dict):
                headers = list(rows[0].keys())
                ws.append(headers)
                for row in rows:
                    ws.append([str(row.get(h, "")) for h in headers])
            else:
                for row in rows:
                    ws.append(list(row) if isinstance(row, (list, tuple)) else [str(row)])
    
    if path:
        wb.save(path)
        return b""
    else:
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()


def export_pdf_summary(path, exec_summary):
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    
    out = io.BytesIO() if not path else path
    c = canvas.Canvas(out, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 750, "SEO Audit Executive Summary")
    c.setFont("Helvetica", 12)
    
    y = 710
    health = exec_summary.get("health_score", {})
    lines = [
        f"Audit Date: {exec_summary.get('audit_date')}",
        f"Start URL: {exec_summary.get('start_url')}",
        f"Pages Crawled: {exec_summary.get('pages_crawled')}",
        f"Health Score: {health.get('score', 0)} / 100 (Grade {health.get('grade', 'N/A')})",
        f"Critical Issues: {health.get('critical_issues', 0)}",
        f"Warnings: {health.get('warning_issues', 0)}",
        f"Info: {health.get('info_issues', 0)}",
        f"Orphan Pages: {exec_summary.get('orphan_pages', 0)}",
        f"Broken Links: {exec_summary.get('broken_links', 0)}",
    ]
    
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
        
    c.setFont("Helvetica-Bold", 14)
    y -= 20
    c.drawString(50, y, "Top Recommendations")
    y -= 20
    
    c.setFont("Helvetica", 10)
    for i, rec in enumerate(exec_summary.get("top_recommendations", [])[:10], 1):
        if y < 50:
            c.showPage()
            y = 750
            c.setFont("Helvetica", 10)
        text = f"{i}. [{rec.get('severity', '').upper()}] {rec.get('recommendation')} ({rec.get('affected_pages')} pages)"
        c.drawString(50, y, text[:100] + ("..." if len(text) > 100 else ""))
        y -= 20

    c.save()
    if not path:
        return out.getvalue()
    return b""


def export_html_report(path, exec_summary, pages):
    html = f"<html><head><title>SEO Audit Report</title></head><body>"
    html += f"<h1>SEO Audit Report: {exec_summary.get('start_url')}</h1>"
    health = exec_summary.get("health_score", {})
    html += f"<p><strong>Health Score:</strong> {health.get('score', 0)} (Grade {health.get('grade', 'N/A')})</p>"
    html += f"<p><strong>Pages Crawled:</strong> {exec_summary.get('pages_crawled')}</p>"
    html += f"<h2>Top Recommendations</h2><ul>"
    for rec in exec_summary.get("top_recommendations", []):
        html += f"<li>[{rec.get('severity', '').upper()}] {rec.get('recommendation')} ({rec.get('affected_pages')} pages)</li>"
    html += f"</ul>"
    html += "</body></html>"
    
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    return html.encode("utf-8")
