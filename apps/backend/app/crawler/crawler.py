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
import heapq
import itertools
import threading
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

    def crawl(self, progress_callback=None, event_callback=None, on_page=None) -> Dict[str, PageResult]:
        """BFS crawl with a continuous worker pool.

        The frontier is a heap keyed on (depth, sequence), so pages are still
        discovered in click-depth order -- the order that makes crawl depth and
        the architecture graph mean anything. What changed is that workers draw
        from it continuously instead of in lockstep batches: a batch previously
        had to drain before the next began, so one slow page idled every other
        worker until it finished.

        `on_page`, when given, receives each PageResult as it completes and
        returns (internal_links, external_links). Stage 2 supplies it so each
        page's HTML is parsed exactly once, in the worker, rather than again
        here. Without it the crawler parses the page itself, which is how the
        CLI and any direct caller still work.
        """
        self.event_callback = event_callback
        sequence = itertools.count()
        frontier = [(0, next(sequence), self.start_url, None)]
        self.queued.add(self.start_url)

        in_flight = {}
        admitted = 0
        # Admission is counted under a lock rather than from len(self.visited):
        # with many fetches outstanding, each could pass a `visited < max_pages`
        # check before any of them has recorded a result, and the crawl would
        # overshoot the cap.
        lock = threading.Lock()
        # Bounded so the frontier cannot run far ahead of the work, which is
        # what keeps un-analysed HTML from accumulating.
        max_in_flight = max(self.concurrency * 2, 1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            while frontier or in_flight:
                if self.is_stopped:
                    break
                if self.is_paused:
                    time.sleep(0.5)
                    continue

                while frontier and len(in_flight) < max_in_flight:
                    depth, _, url, referrer = heapq.heappop(frontier)
                    if url in self.visited or not self._allowed(url):
                        continue
                    with lock:
                        if admitted >= self.max_pages:
                            frontier.clear()
                            break
                        admitted += 1
                    in_flight[pool.submit(self._fetch, url)] = (url, depth, referrer)

                if not in_flight:
                    # Nothing outstanding and nothing admissible: the crawl is
                    # done, whether the frontier emptied or the cap was reached.
                    break

                done, _ = concurrent.futures.wait(
                    in_flight, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in done:
                    url, depth, referrer = in_flight.pop(future)
                    self._handle_result(
                        future, url, depth, referrer, frontier, sequence,
                        progress_callback, on_page,
                    )

        return self.results

    def _handle_result(self, future, url, depth, referrer, frontier, sequence,
                       progress_callback, on_page):
        """Record one fetched page and push whatever it links to."""
        result = future.result()
        result.depth = depth
        if referrer:
            result.referrers.add(referrer)
            self.inbound_links.setdefault(url, set()).add(referrer)
        self.visited.add(url)
        self.results[url] = result

        if progress_callback:
            progress_callback(len(self.visited), self.max_pages, url)
        if self.event_callback:
            self.event_callback("page_crawled", {
                "url": result.url,
                "status": result.status_code,
                "depth": result.depth,
                "response_time": result.response_time_ms,
                "timestamp": time.time() * 1000,
            })

        if self.delay:
            time.sleep(self.delay)

        # on_page runs even at the depth limit and even for an empty page: it is
        # how stage 2 receives the page at all, not merely how links arrive.
        internal_links, external_links = [], []
        if on_page is not None:
            internal_links, external_links = on_page(result)
        elif result.html:
            for link in self._extract_links(result.final_url, result.html):
                normalized = normalize_url(link)
                if same_registrable_domain(normalized, self.root_netloc):
                    internal_links.append(normalized)
                else:
                    external_links.append(normalized)

        self.link_graph[url] = set(internal_links)
        for target in external_links:
            self.external_links.add(target)

        if depth >= self.max_depth:
            return
        for target in internal_links:
            if target not in self.queued and target not in self.visited:
                self.queued.add(target)
                heapq.heappush(frontier, (depth + 1, next(sequence), target, url))

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
