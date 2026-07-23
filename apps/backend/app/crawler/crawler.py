"""
crawler.py — Core crawl engine.

Handles:
- BFS crawling from a start URL, restricted to the same registered domain
- robots.txt parsing (optional respect)
- sitemap.xml discovery + parsing
- redirect chain tracking (301/302/307/308)
- URL de-duplication + canonicalization of URLs for the visited-set
- crawl depth control
- retries on transient failures
- multi-threaded fetching
- orphan-page / broken-link bookkeeping
"""

from __future__ import annotations

import concurrent.futures
import time
import urllib.parse as up
import urllib.robotparser as robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup

DEFAULT_HEADERS = {
    "User-Agent": "SEOAuditorBot/1.0 (+https://example.com/bot)"
}

REDIRECT_CODES = {301, 302, 303, 307, 308}


def normalize_url(url: str) -> str:
    """Strip fragments, normalize trailing behaviour for dedup purposes."""
    parts = up.urlsplit(url)
    path = parts.path or "/"
    # collapse duplicate slashes
    while "//" in path:
        path = path.replace("//", "/")
    normalized = up.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))
    return normalized


def same_registrable_domain(url: str, root_netloc: str) -> bool:
    netloc = up.urlsplit(url).netloc.lower()
    root = root_netloc.lower()
    return netloc == root or netloc.endswith("." + root) or root.endswith("." + netloc)


@dataclass
class PageResult:
    url: str
    final_url: str
    status_code: Optional[int]
    redirect_chain: List[Dict] = field(default_factory=list)
    response_time_ms: Optional[float] = None
    content_type: str = ""
    html: str = ""
    headers: Dict = field(default_factory=dict)
    depth: int = 0
    referrers: Set[str] = field(default_factory=set)
    error: Optional[str] = None
    fetched_at: float = field(default_factory=time.time)


class Crawler:
    def __init__(
        self,
        start_url: str,
        max_pages: int = 200,
        max_depth: int = 5,
        respect_robots: bool = True,
        concurrency: int = 8,
        timeout: int = 15,
        retries: int = 2,
        delay: float = 0.0,
        include_external_link_check: bool = True,
        user_agent: str = DEFAULT_HEADERS["User-Agent"],
    ):
        self.start_url = normalize_url(start_url)
        self.root_netloc = up.urlsplit(self.start_url).netloc
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.respect_robots = respect_robots
        self.concurrency = concurrency
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.include_external_link_check = include_external_link_check
        self.headers = {**DEFAULT_HEADERS, "User-Agent": user_agent}

        self.session = requests.Session()
        self.session.headers.update(self.headers)

        self.visited: Set[str] = set()
        self.queued: Set[str] = set()
        self.results: Dict[str, PageResult] = {}
        
        self.is_paused = False
        self.is_stopped = False
        self.event_callback = None
        self.link_graph: Dict[str, Set[str]] = {}  # url -> set(linked urls, internal only)
        self.inbound_links: Dict[str, Set[str]] = {}  # url -> set(referrers)
        self.external_links_checked: Dict[str, int] = {}  # external url -> status (best effort)
        self.external_links: Set[str] = set()
        self.broken_links: List[Dict] = []
        self.robots_txt_content: Optional[str] = None
        self.robots_parser: Optional[robotparser.RobotFileParser] = None
        self.sitemap_urls: Set[str] = set()
        self.sitemaps_found: List[str] = []

        self._load_robots()
        self._load_sitemaps()

    # ---------------------------------------------------------------- robots
    def _load_robots(self):
        robots_url = up.urljoin(self.start_url, "/robots.txt")
        try:
            resp = self.session.get(robots_url, timeout=self.timeout)
            if resp.status_code == 200:
                self.robots_txt_content = resp.text
                rp = robotparser.RobotFileParser()
                rp.parse(resp.text.splitlines())
                self.robots_parser = rp
                # discover sitemap declarations
                for line in resp.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sm = line.split(":", 1)[1].strip()
                        self.sitemaps_found.append(sm)
        except requests.RequestException:
            self.robots_txt_content = None

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots or not self.robots_parser:
            return True
        try:
            return self.robots_parser.can_fetch(self.headers["User-Agent"], url)
        except Exception:
            return True

    # --------------------------------------------------------------- sitemap
    def _load_sitemaps(self):
        candidates = list(self.sitemaps_found) or [up.urljoin(self.start_url, "/sitemap.xml")]
        seen = set()
        queue = list(candidates)
        while queue:
            sm_url = queue.pop(0)
            if sm_url in seen:
                continue
            seen.add(sm_url)
            try:
                resp = self.session.get(sm_url, timeout=self.timeout)
                if resp.status_code != 200:
                    continue
                self.sitemaps_found.append(sm_url) if sm_url not in self.sitemaps_found else None
                root = ET.fromstring(resp.content)
                tag = root.tag.lower()
                ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                if tag.endswith("sitemapindex"):
                    for sm in root.findall("sm:sitemap/sm:loc", ns):
                        if sm.text:
                            queue.append(sm.text.strip())
                elif tag.endswith("urlset"):
                    for url_el in root.findall("sm:url/sm:loc", ns):
                        if url_el.text:
                            self.sitemap_urls.add(normalize_url(url_el.text.strip()))
            except (requests.RequestException, ET.ParseError):
                continue

    # --------------------------------------------------------------- fetch
    def _fetch(self, url: str) -> PageResult:
        redirect_chain = []
        attempt = 0
        last_exc = None
        while attempt <= self.retries:
            try:
                start = time.time()
                resp = self.session.get(url, timeout=self.timeout, allow_redirects=False)
                elapsed = (time.time() - start) * 1000

                current_url = url
                current_resp = resp
                hops = 0
                while current_resp.status_code in REDIRECT_CODES and hops < 10:
                    location = current_resp.headers.get("Location")
                    if not location:
                        break
                    next_url = up.urljoin(current_url, location)
                    redirect_chain.append({
                        "from": current_url,
                        "to": next_url,
                        "status": current_resp.status_code,
                    })
                    current_url = next_url
                    current_resp = self.session.get(current_url, timeout=self.timeout, allow_redirects=False)
                    hops += 1

                content_type = current_resp.headers.get("Content-Type", "")
                html = ""
                if current_resp.status_code == 200 and "text/html" in content_type:
                    current_resp.encoding = current_resp.encoding or "utf-8"
                    html = current_resp.text

                if self.event_callback:
                    if current_resp.status_code >= 400:
                        self.event_callback("broken_link", {"url": url, "status": current_resp.status_code})
                    if redirect_chain:
                        self.event_callback("redirect", {"url": url, "to": current_url})
                        
                return PageResult(
                    url=url,
                    final_url=current_url,
                    status_code=current_resp.status_code,
                    redirect_chain=redirect_chain,
                    response_time_ms=round(elapsed, 1),
                    content_type=content_type,
                    html=html,
                    headers=dict(current_resp.headers),
                )
            except requests.RequestException as exc:
                last_exc = exc
                attempt += 1
                time.sleep(0.5 * attempt)
                
        if self.event_callback:
            self.event_callback("timeout", {"url": url, "error": str(last_exc)})
            
        return PageResult(url=url, final_url=url, status_code=None, error=str(last_exc))

    # ---------------------------------------------------------------- crawl
    def _extract_links(self, base_url: str, html: str) -> List[str]:
        links = []
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            return links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            absolute = up.urljoin(base_url, href)
            links.append(absolute)
        return links

    def crawl(self, progress_callback=None, event_callback=None) -> Dict[str, PageResult]:
        """BFS crawl honoring max_pages / max_depth, multi-threaded per depth level."""
        self.event_callback = event_callback
        frontier = [(self.start_url, 0, None)]
        self.queued.add(self.start_url)

        while frontier and len(self.visited) < self.max_pages:
            if self.is_stopped:
                break
            if self.is_paused:
                time.sleep(0.5)
                continue
                
            remaining = self.max_pages - len(self.visited)
            batch_size = min(self.concurrency, remaining)
            batch = frontier[:batch_size]
            frontier = frontier[batch_size:]

            batch = [b for b in batch if b[0] not in self.visited]
            if not batch:
                continue

            with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as ex:
                future_map = {}
                for u, depth, referrer in batch:
                    if len(self.visited) >= self.max_pages:
                        break
                    if not self._allowed(u):
                        continue
                    future_map[ex.submit(self._fetch, u)] = (u, depth, referrer)

                for fut in concurrent.futures.as_completed(future_map):
                    u, depth, referrer = future_map[fut]
                    result = fut.result()
                    result.depth = depth
                    if referrer:
                        result.referrers.add(referrer)
                        self.inbound_links.setdefault(u, set()).add(referrer)
                    self.visited.add(u)
                    self.results[u] = result

                    if progress_callback:
                        progress_callback(len(self.visited), self.max_pages, u)
                    if self.event_callback:
                        self.event_callback("page_crawled", {
                            "url": result.url,
                            "status": result.status_code,
                            "depth": result.depth,
                            "response_time": result.response_time_ms,
                            "timestamp": time.time() * 1000
                        })

                    if self.delay:
                        time.sleep(self.delay)

                    if not result.html or depth >= self.max_depth:
                        continue

                    child_links = self._extract_links(result.final_url, result.html)
                    internal_children = set()
                    for link in child_links:
                        norm = normalize_url(link)
                        if same_registrable_domain(norm, self.root_netloc):
                            internal_children.add(norm)
                            self.link_graph.setdefault(u, set()).add(norm)
                            if self.event_callback:
                                self.event_callback("internal_link", {"from": u, "to": norm})
                            if norm not in self.queued and norm not in self.visited:
                                self.queued.add(norm)
                                frontier.append((norm, depth + 1, u))
                        else:
                            if self.event_callback:
                                self.event_callback("external_link", {"from": u, "to": norm})
                            self.external_links.add(norm)
                            self.link_graph.setdefault(u, set()).add(norm)
                    self.link_graph[u] = internal_children

        return self.results

    # ------------------------------------------------------------ ext links
    def check_external_links(self, max_check: int = 100):
        """Best-effort HEAD (fallback GET) check of a sample of external links."""
        targets = list(self.external_links)[:max_check]

        def head(u):
            try:
                r = self.session.head(u, timeout=self.timeout, allow_redirects=True)
                if r.status_code >= 400:
                    r = self.session.get(u, timeout=self.timeout, allow_redirects=True)
                return u, r.status_code
            except requests.RequestException:
                return u, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            for u, status in ex.map(head, targets):
                self.external_links_checked[u] = status
