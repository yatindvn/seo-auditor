"""
checks.py — Per-page audit checks.

Each check_* function takes a PageResult (+ optional site-wide context) and
returns a list of issue dicts: {"severity": "critical|warning|info", "code": str, "message": str}
Plus some functions return raw extracted data used later for duplicate/content analysis.
"""

from __future__ import annotations

import json
import re
import urllib.parse as up
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

STOP_WORDS = set("""a an the and or but if then else for of on in to with is are was were be been being
this that these those it its as at by from not no so such than too very can will just""".split())


def _soup(html: str) -> Optional[BeautifulSoup]:
    if not html:
        return None
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return None


def issue(severity: str, code: str, message: str) -> Dict:
    return {"severity": severity, "code": code, "message": message}


# ------------------------------------------------------------------ technical
def check_status_and_https(page, redirect_chain_lengths: Dict[str, int]) -> List[Dict]:
    out = []
    if page.error:
        out.append(issue("critical", "FETCH_ERROR", f"Failed to fetch: {page.error}"))
        return out
    sc = page.status_code
    if sc is None:
        out.append(issue("critical", "NO_RESPONSE", "No response received"))
    elif sc == 404:
        out.append(issue("critical", "STATUS_404", "Page returns 404 Not Found"))
    elif sc == 410:
        out.append(issue("warning", "STATUS_410", "Page returns 410 Gone"))
    elif sc >= 500:
        out.append(issue("critical", f"STATUS_{sc}", f"Server error {sc}"))
    elif sc in (301, 302, 307, 308):
        out.append(issue("info", f"STATUS_{sc}", f"Page redirects ({sc})"))

    if page.redirect_chain:
        if len(page.redirect_chain) > 1:
            out.append(issue("warning", "REDIRECT_CHAIN", f"Redirect chain of {len(page.redirect_chain)} hops"))
        temp_hops = [h for h in page.redirect_chain if h["status"] in (302, 307)]
        if temp_hops:
            out.append(issue("info", "TEMP_REDIRECT", "Uses a temporary redirect (302/307) instead of permanent"))
        seen = set()
        for hop in page.redirect_chain:
            if hop["from"] in seen:
                out.append(issue("critical", "REDIRECT_LOOP", "Redirect loop detected"))
                break
            seen.add(hop["from"])

    parsed = up.urlsplit(page.url)
    if parsed.scheme != "https":
        out.append(issue("critical", "NO_HTTPS", "Page is served over HTTP, not HTTPS"))

    return out


def check_mixed_content(page) -> List[Dict]:
    out = []
    soup = _soup(page.html)
    if not soup or up.urlsplit(page.final_url).scheme != "https":
        return out
    for tag, attr in [("img", "src"), ("script", "src"), ("link", "href"), ("iframe", "src")]:
        for el in soup.find_all(tag):
            val = el.get(attr)
            if val and val.startswith("http://"):
                out.append(issue("warning", "MIXED_CONTENT", f"Insecure {tag} resource: {val}"))
                break
    return out


def check_canonical(page, page_url: str):
    out = []
    soup = _soup(page.html)
    canonical_href = None
    if not soup:
        return out, canonical_href
    canon_tags = soup.find_all("link", rel=lambda x: x and "canonical" in x.lower())
    if len(canon_tags) == 0:
        out.append(issue("warning", "MISSING_CANONICAL", "No canonical tag found"))
    elif len(canon_tags) > 1:
        out.append(issue("warning", "MULTIPLE_CANONICALS", f"{len(canon_tags)} canonical tags found"))
        canonical_href = canon_tags[0].get("href")
    else:
        canonical_href = canon_tags[0].get("href")

    if canonical_href:
        abs_canonical = up.urljoin(page_url, canonical_href)
        from .crawler import normalize_url
        if normalize_url(abs_canonical) != normalize_url(page_url):
            out.append(issue("info", "CANONICAL_ELSEWHERE", f"Canonical points to a different URL: {abs_canonical}"))
    return out, canonical_href


def check_indexability(page) -> List[Dict]:
    out = []
    soup = _soup(page.html)
    robots_header = page.headers.get("X-Robots-Tag", "") if page.headers else ""
    meta_robots = ""
    if soup:
        tag = soup.find("meta", attrs={"name": re.compile("robots", re.I)})
        if tag and tag.get("content"):
            meta_robots = tag["content"].lower()

    combined = f"{robots_header.lower()} {meta_robots}"
    if "noindex" in combined:
        out.append(issue("warning", "NOINDEX", "Page is set to noindex"))
    if "nofollow" in combined:
        out.append(issue("info", "NOFOLLOW", "Page is set to nofollow"))
    return out


# -------------------------------------------------------------------- onpage
def check_title(page):
    out = []
    soup = _soup(page.html)
    title = None
    if not soup:
        return out, title
    titles = soup.find_all("title")
    if len(titles) == 0:
        out.append(issue("critical", "MISSING_TITLE", "Missing <title> tag"))
    else:
        title = titles[0].get_text(strip=True)
        if len(titles) > 1:
            out.append(issue("warning", "MULTIPLE_TITLES", f"{len(titles)} <title> tags found"))
        if not title:
            out.append(issue("critical", "EMPTY_TITLE", "Title tag is empty"))
        elif len(title) < 15:
            out.append(issue("info", "TITLE_TOO_SHORT", f"Title is short ({len(title)} chars)"))
        elif len(title) > 60:
            out.append(issue("info", "TITLE_TOO_LONG", f"Title may be truncated in SERPs ({len(title)} chars)"))
    return out, title


def check_meta_description(page):
    out = []
    soup = _soup(page.html)
    desc = None
    if not soup:
        return out, desc
    tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if not tag or not tag.get("content", "").strip():
        out.append(issue("warning", "MISSING_META_DESCRIPTION", "Missing meta description"))
    else:
        desc = tag["content"].strip()
        if len(desc) < 50:
            out.append(issue("info", "META_DESC_TOO_SHORT", f"Meta description is short ({len(desc)} chars)"))
        elif len(desc) > 160:
            out.append(issue("info", "META_DESC_TOO_LONG", f"Meta description may be truncated ({len(desc)} chars)"))
    return out, desc


def check_headings(page):
    out = []
    soup = _soup(page.html)
    h1_text = None
    if not soup:
        return out, h1_text
    h1s = soup.find_all("h1")
    if len(h1s) == 0:
        out.append(issue("warning", "MISSING_H1", "No H1 heading found"))
    elif len(h1s) > 1:
        out.append(issue("warning", "MULTIPLE_H1", f"{len(h1s)} H1 tags found"))
    if h1s:
        h1_text = h1s[0].get_text(strip=True)
        if not h1_text:
            out.append(issue("warning", "EMPTY_H1", "H1 tag is empty"))

    levels = []
    for h in soup.find_all(re.compile("^h[1-6]$")):
        levels.append(int(h.name[1]))
        if not h.get_text(strip=True):
            out.append(issue("info", "EMPTY_HEADING", f"Empty <{h.name}> tag"))
    prev = 0
    for lvl in levels:
        if prev and lvl - prev > 1:
            out.append(issue("info", "HEADING_HIERARCHY_SKIP", f"Heading level jumps from H{prev} to H{lvl}"))
            break
        prev = lvl
    return out, h1_text


def check_images(page) -> List[Dict]:
    out = []
    soup = _soup(page.html)
    if not soup:
        return out
    imgs = soup.find_all("img")
    missing_alt = 0
    missing_dims = 0
    no_lazy = 0
    for img in imgs:
        if not img.get("alt", "").strip():
            missing_alt += 1
        if not (img.get("width") and img.get("height")):
            missing_dims += 1
        if img.get("loading") != "lazy" and not img.get("data-src"):
            no_lazy += 1
    if missing_alt:
        out.append(issue("warning", "MISSING_ALT", f"{missing_alt} of {len(imgs)} images missing alt text"))
    if missing_dims:
        out.append(issue("info", "MISSING_IMG_DIMENSIONS", f"{missing_dims} images missing width/height (can cause CLS)"))
    if imgs and no_lazy == len(imgs) and len(imgs) > 5:
        out.append(issue("info", "NO_LAZY_LOADING", "No images use native lazy loading"))
    return out


def check_links(page) -> List[Dict]:
    out = []
    soup = _soup(page.html)
    if not soup:
        return out
    anchors = soup.find_all("a", href=True)
    empty_anchor = sum(1 for a in anchors if not a.get_text(strip=True) and not a.find("img"))
    if empty_anchor:
        out.append(issue("info", "EMPTY_ANCHOR_TEXT", f"{empty_anchor} links have empty anchor text"))
    target_blank_no_rel = [
        a for a in anchors
        if a.get("target") == "_blank" and "noopener" not in (a.get("rel") or [])
    ]
    if target_blank_no_rel:
        out.append(issue("info", "MISSING_NOOPENER", f"{len(target_blank_no_rel)} target=_blank links missing rel=noopener"))
    return out


def check_structured_data(page) -> List[Dict]:
    out = []
    soup = _soup(page.html)
    if not soup:
        return out
    ld_blocks = soup.find_all("script", type="application/ld+json")
    if not ld_blocks:
        out.append(issue("info", "NO_STRUCTURED_DATA", "No JSON-LD structured data found"))
    else:
        for block in ld_blocks:
            try:
                json.loads(block.string or "{}")
            except (json.JSONDecodeError, TypeError):
                out.append(issue("warning", "INVALID_JSON_LD", "JSON-LD block is not valid JSON"))
    return out


def check_open_graph_twitter(page) -> List[Dict]:
    out = []
    soup = _soup(page.html)
    if not soup:
        return out
    og_props = {m.get("property"): m.get("content") for m in soup.find_all("meta", property=re.compile("^og:"))}
    for required in ("og:title", "og:type", "og:url", "og:image"):
        if not og_props.get(required):
            out.append(issue("info", f"MISSING_{required.upper().replace(':', '_')}", f"Missing Open Graph tag: {required}"))
    if not soup.find("meta", attrs={"name": "twitter:card"}):
        out.append(issue("info", "MISSING_TWITTER_CARD", "Missing twitter:card meta tag"))
    return out


def check_url_structure(page_url: str) -> List[Dict]:
    out = []
    parsed = up.urlsplit(page_url)
    if any(c.isupper() for c in parsed.path):
        out.append(issue("info", "URL_UPPERCASE", "URL path contains uppercase characters"))
    if "_" in parsed.path:
        out.append(issue("info", "URL_UNDERSCORE", "URL uses underscores instead of hyphens"))
    if len(page_url) > 115:
        out.append(issue("info", "URL_TOO_LONG", f"URL is long ({len(page_url)} chars)"))
    if parsed.query:
        params = up.parse_qs(parsed.query)
        if len(params) > 3:
            out.append(issue("info", "TOO_MANY_PARAMS", f"URL has {len(params)} query parameters"))
    return out


# ------------------------------------------------------------------- content
def check_content(page):
    out = []
    soup = _soup(page.html)
    stats = {"word_count": 0, "text": ""}
    if not soup:
        return out, stats
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    words = re.findall(r"[A-Za-z']+", text.lower())
    word_count = len(words)
    stats["word_count"] = word_count
    stats["text"] = text[:20000]

    if word_count < 150:
        out.append(issue("warning", "THIN_CONTENT", f"Thin content: only {word_count} words"))

    return out, stats


def keyword_density(words: List[str], top_n: int = 10) -> List[Dict]:
    from collections import Counter
    filtered = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    counts = Counter(filtered)
    total = max(len(filtered), 1)
    return [
        {"keyword": w, "count": c, "density_pct": round(c / total * 100, 2)}
        for w, c in counts.most_common(top_n)
    ]


def readability_flesch(text: str) -> Optional[float]:
    sentences = re.split(r"[.!?]+", text)
    sentences = [s for s in sentences if s.strip()]
    words = re.findall(r"[A-Za-z']+", text)
    if not sentences or not words:
        return None

    def count_syllables(word):
        word = word.lower()
        vowels = "aeiouy"
        count = 0
        prev_vowel = False
        for ch in word:
            is_vowel = ch in vowels
            if is_vowel and not prev_vowel:
                count += 1
            prev_vowel = is_vowel
        if word.endswith("e") and count > 1:
            count -= 1
        return max(count, 1)

    syllables = sum(count_syllables(w) for w in words)
    n_words = len(words)
    n_sentences = len(sentences)
    score = 206.835 - 1.015 * (n_words / n_sentences) - 84.6 * (syllables / n_words)
    return round(score, 1)


# -------------------------------------------------------------------- mobile
def check_mobile(page) -> List[Dict]:
    out = []
    soup = _soup(page.html)
    if not soup:
        return out
    viewport = soup.find("meta", attrs={"name": "viewport"})
    if not viewport:
        out.append(issue("critical", "MISSING_VIEWPORT", "Missing viewport meta tag (not mobile responsive)"))
    elif "width=device-width" not in (viewport.get("content", "").replace(" ", "")):
        out.append(issue("warning", "VIEWPORT_MISCONFIGURED", "Viewport meta tag doesn't set width=device-width"))

    small_font_inline = soup.find_all(style=re.compile(r"font-size:\s*(?:[0-9]|1[01])px"))
    if small_font_inline:
        out.append(issue("info", "SMALL_FONT", f"{len(small_font_inline)} elements with inline font-size under 12px"))
    return out


# -------------------------------------------------------------- accessibility
def check_accessibility(page) -> List[Dict]:
    out = []
    soup = _soup(page.html)
    if not soup:
        return out

    imgs_no_alt = [i for i in soup.find_all("img") if i.get("alt") is None]
    if imgs_no_alt:
        out.append(issue("warning", "A11Y_IMG_NO_ALT_ATTR", f"{len(imgs_no_alt)} images missing alt attribute entirely"))

    inputs = soup.find_all(["input", "select", "textarea"])
    unlabeled = 0
    for inp in inputs:
        if inp.get("type") in ("hidden", "submit", "button"):
            continue
        input_id = inp.get("id")
        has_label = bool(input_id and soup.find("label", attrs={"for": input_id}))
        has_aria = bool(inp.get("aria-label") or inp.get("aria-labelledby"))
        if not has_label and not has_aria:
            unlabeled += 1
    if unlabeled:
        out.append(issue("warning", "A11Y_UNLABELED_FORM_FIELD", f"{unlabeled} form fields without associated labels"))

    html_tag = soup.find("html")
    if not html_tag or not html_tag.get("lang"):
        out.append(issue("info", "A11Y_MISSING_LANG", "Missing lang attribute on <html>"))

    for el in soup.find_all(attrs={"aria-hidden": "true"}):
        if el.find(["a", "button", "input"]):
            out.append(issue("info", "A11Y_ARIA_HIDDEN_FOCUSABLE", "aria-hidden element contains a focusable child"))
            break

    return out


# ------------------------------------------------------------------ security
def check_security_headers(page) -> List[Dict]:
    out = []
    if not page.headers:
        return out
    headers_lower = {k.lower(): v for k, v in page.headers.items()}
    required = {
        "strict-transport-security": "warning",
        "content-security-policy": "info",
        "x-content-type-options": "info",
        "x-frame-options": "info",
        "referrer-policy": "info",
    }
    for h, sev in required.items():
        if h not in headers_lower:
            out.append(issue(sev, f"MISSING_HEADER_{h.upper().replace('-', '_')}", f"Missing security header: {h}"))
    return out


# -------------------------------------------------------------- international
def check_hreflang(page) -> List[Dict]:
    out = []
    soup = _soup(page.html)
    if not soup:
        return out
    tags = soup.find_all("link", rel="alternate", hreflang=True)
    if not tags:
        return out
    codes = [t.get("hreflang", "").lower() for t in tags]
    if len(codes) != len(set(codes)):
        out.append(issue("warning", "DUPLICATE_HREFLANG", "Duplicate hreflang values found"))
    has_x_default = any(c == "x-default" for c in codes)
    if not has_x_default:
        out.append(issue("info", "NO_X_DEFAULT", "No x-default hreflang declared"))
    return out


# -------------------------------------------------------------------- media
def check_media(page) -> List[Dict]:
    out = []
    soup = _soup(page.html)
    if not soup:
        return out
    videos = soup.find_all("video")
    for v in videos:
        if not v.get("poster"):
            out.append(issue("info", "VIDEO_NO_POSTER", "<video> element missing poster attribute"))
            break
    pdf_links = [a for a in soup.find_all("a", href=True) if a["href"].lower().endswith(".pdf")]
    if pdf_links:
        out.append(issue("info", "PDF_LINKS_FOUND", f"{len(pdf_links)} links to PDF files (verify accessibility/indexability)"))
    return out


# ------------------------------------------------------------ js seo (basic)
def check_js_rendering_signal(page) -> List[Dict]:
    out = []
    soup = _soup(page.html)
    if not soup:
        return out
    body = soup.find("body")
    if not body:
        return out
    text_len = len(body.get_text(strip=True))
    spa_roots = soup.find_all(id=re.compile("^(root|app|__next)$"))
    script_count = len(soup.find_all("script"))
    if text_len < 200 and spa_roots and script_count > 3:
        out.append(issue("warning", "POSSIBLE_CSR_ONLY", "Page may rely on client-side rendering; little content in raw HTML"))
    return out
