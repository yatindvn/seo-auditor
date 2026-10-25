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
import hashlib
import heapq
import itertools
import threading
import time
import urllib.parse as up
import urllib.robotparser as robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from app.crawler.throttle import AdaptiveLimit

DEFAULT_HEADERS = {
    "User-Agent": "SEOAuditorBot/1.0 (+https://example.com/bot)"
}

REDIRECT_CODES = {301, 302, 303, 307, 308}


# Query params that only identify where a click came from. They never change
# which page the server returns, so two URLs differing only in these are one page.
TRACKING_PARAMS = frozenset({
    "gclid", "fbclid", "msclkid", "dclid", "yclid",
    "mc_cid", "mc_eid", "_ga", "_gl", "ref_src",
})
DEFAULT_PORTS = {"http": 80, "https": 443}


def _is_tracking_param(segment: str) -> bool:
    name = up.unquote(segment.split("=", 1)[0]).lower()
    return name.startswith("utm_") or name in TRACKING_PARAMS


def normalize_url(url: str) -> str:
    """Canonical spelling of a URL for dedup.

    Only lossless rewrites: fragment, host case, default port, tracking params,
    and param order. Query segments are filtered and sorted as raw text rather
    than parsed and re-encoded, so `?print` stays `?print` and percent-escapes
    are untouched. The sort is stable and keyed on the name alone, so repeated
    keys keep their relative order.
    """
    parts = up.urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is not None and DEFAULT_PORTS.get(scheme) == port:
        netloc = netloc.rsplit(":", 1)[0]

    path = parts.path or "/"
    # collapse duplicate slashes
    while "//" in path:
        path = path.replace("//", "/")

    segments = [s for s in parts.query.split("&") if s and not _is_tracking_param(s)]
    segments.sort(key=lambda s: s.split("=", 1)[0])
    query = "&".join(segments)

    return up.urlunsplit((scheme, netloc, path, query, ""))


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
    # Set when this URL turned out to be a page already represented by another:
    # alias_of after a redirect landed on a claimed URL, duplicate_of after the
    # body matched one already seen byte for byte.
    alias_of: Optional[str] = None
    duplicate_of: Optional[str] = None
    found_via: str = "link"
    # "not_modified" when the server answered 304, "same_hash" when it sent a
    # body identical to the cached one; None for anything to analyse afresh.
    cache_status: Optional[str] = None
    body_hash: Optional[str] = None
    # True when the site answered 429/503 at any point while fetching this
    # page (even if a retry then succeeded) -- the signal the limit cuts on.
    throttled: bool = False
    retry_after: Optional[float] = None


@dataclass
class Validators:
    """What a previous audit learned about a URL, enough to ask the server
    whether it changed: its validators, its body hash, and its headers (a 304
    carries few headers of its own, so the stored ones are merged under it)."""
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    body_hash: Optional[str] = None
    headers: Dict = field(default_factory=dict)


THROTTLE_CODES = {429, 503}


def _retry_after_seconds(response) -> Optional[float]:
    """Retry-After in its seconds form; the HTTP-date form is ignored."""
    value = response.headers.get("Retry-After") if response is not None else None
    try:
        return max(float(value), 0.0) if value is not None else None
    except (TypeError, ValueError):
        return None


def _merge_headers(stored: Dict, fresh) -> Dict:
    """A 304's headers laid over the stored response's (RFC 9111 4.3.4).

    Case-insensitive: the store and the 304 may spell a field differently, and
    a plain dict merge would then hold both, with checks reading the stale one.
    """
    merged = dict(stored or {})
    by_lower = {key.lower(): key for key in merged}
    for key, value in dict(fresh).items():
        existing = by_lower.get(key.lower())
        if existing is not None:
            del merged[existing]
        merged[key] = value
        by_lower[key.lower()] = key
    return merged


class Crawler:
    def __init__(
        self,
        start_url: str,
        max_pages: int = 200,
        max_depth: int = 5,
        respect_robots: bool = True,
        concurrency: int = 8,
        max_concurrency: Optional[int] = None,
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
        # Never above an explicit concurrency unless a ceiling was given: the
        # CLI's --concurrency and tests mean exactly that number.
        self.max_concurrency = max(max_concurrency or concurrency, concurrency)
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.include_external_link_check = include_external_link_check
        self.headers = {**DEFAULT_HEADERS, "User-Agent": user_agent}

        self.session = requests.Session()
        self.session.headers.update(self.headers)
        # requests' default pool keeps 10 connections per host; with more
        # workers than that, every surplus request opened (and TLS-shook) a
        # new connection and threw it away.
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=self.max_concurrency)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.visited: Set[str] = set()
        self.queued: Set[str] = set()
        self.results: Dict[str, PageResult] = {}
        
        self.is_paused = False
        # Links are counted and flushed periodically rather than emitted one
        # event each: 5000 pages is a few hundred thousand messages, which
        # stalls the browser long before the crawl finishes.
        self._link_counts = {"internal": 0, "external": 0}
        self._last_link_flush = 0.0
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

        # Dedup state. All three are touched only from the crawl loop's own
        # thread (_handle_result), never from a fetch worker, so need no lock.
        self.aliases: Dict[str, str] = {}      # url -> url whose result represents it
        self.claimed: Dict[str, str] = {}      # normalised final url -> first url to reach it
        self.body_owner: Dict[str, str] = {}   # sha256 of html -> first url serving it
        self.skipped: Dict[str, PageResult] = {}
        # A site that is all duplicates (endless calendar params, say) frees
        # every slot it takes; this bounds the fetches regardless.
        self.fetch_ceiling = max_pages * 2
        self._sitemap_pending: Set[str] = set()
        self._admitted = 0
        self._fetched = 0
        # Set by the audit from its page cache before crawl(). validators is
        # read by fetch workers but never written during a crawl.
        self.validators: Dict[str, Validators] = {}
        self.cached_links: Optional[Callable[[str], Optional[Tuple[List[str], List[str]]]]] = None

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
                # The site's stated rate wins over adaptivity.
                if self.respect_robots:
                    crawl_delay = rp.crawl_delay(self.headers["User-Agent"])
                    if crawl_delay:
                        self.delay = max(self.delay, float(crawl_delay))
                        self.concurrency = 1
                        self.max_concurrency = 1
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
    def _fetch(self, url: str, conditional: bool = True) -> PageResult:
        validators = self.validators.get(url) if conditional else None
        request_headers = {}
        if validators is not None:
            if validators.etag:
                request_headers["If-None-Match"] = validators.etag
            if validators.last_modified:
                request_headers["If-Modified-Since"] = validators.last_modified

        redirect_chain = []
        throttled = False
        retry_after = None
        attempt = 0
        last_exc = None
        while attempt <= self.retries:
            try:
                start = time.time()
                resp = self.session.get(url, timeout=self.timeout, allow_redirects=False,
                                        headers=request_headers or None)
                elapsed = (time.time() - start) * 1000

                if resp.status_code == 304 and validators is not None:
                    # Unchanged: no body, and few headers of its own. The page is
                    # the cached one, with today's headers laid over yesterday's.
                    headers = _merge_headers(validators.headers, resp.headers)
                    content_type = next(
                        (v for k, v in headers.items() if k.lower() == "content-type"), ""
                    )
                    return PageResult(
                        url=url, final_url=url, status_code=200,
                        response_time_ms=round(elapsed, 1), content_type=content_type,
                        html="", headers=headers,
                        cache_status="not_modified", body_hash=validators.body_hash,
                    )

                if resp.status_code in THROTTLE_CODES:
                    throttled = True
                    retry_after = _retry_after_seconds(resp)
                    if attempt < self.retries:
                        attempt += 1
                        time.sleep(min(retry_after if retry_after is not None else 0.5 * attempt, 60.0))
                        continue

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

                body_hash = (
                    hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest() if html else None
                )
                cache_status = (
                    "same_hash"
                    if validators is not None and body_hash and body_hash == validators.body_hash
                    else None
                )

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
                    cache_status=cache_status,
                    body_hash=body_hash,
                    throttled=throttled,
                    retry_after=retry_after,
                )
            except requests.RequestException as exc:
                last_exc = exc
                attempt += 1
                time.sleep(0.5 * attempt)
                
        if self.event_callback:
            self.event_callback("timeout", {"url": url, "error": str(last_exc)})
            
        return PageResult(url=url, final_url=url, status_code=None, error=str(last_exc))

    def _fetch_paced(self, url: str) -> PageResult:
        """The worker's entry point: this worker's politeness delay, then the fetch.

        The delay used to sleep on the crawl loop's own thread, which paused
        admission for every worker. Calls self._fetch at call time, so a test
        that replaces _fetch on the instance is still honoured.
        """
        if self.delay:
            time.sleep(self.delay)
        return self._fetch(url)

    def fetch_unconditional(self, url: str) -> PageResult:
        """A full fetch, never answered with a 304: for a page whose cached
        analysis turned out to be missing."""
        return self._fetch(url, conditional=False)

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

        `on_page`, when given, observes each PageResult as it completes; its
        return value is ignored, and it may release the page's markup.

        Stage 2 could instead parse each page once and hand the links back,
        saving the parse here -- but this loop would then have to block on a
        worker to learn them, and only one worker would ever be busy. Measured,
        this parse is 11% of a page's analysis while the parallelism it would
        forfeit is worth about 50%, so the duplicate parse is the cheaper half
        of the trade.

        A URL whose result turns out to be an alias or duplicate gives its
        admission back, so `max_pages` counts unique pages; `fetch_ceiling`
        bounds the total.
        """
        self.event_callback = event_callback
        sequence = itertools.count()
        frontier = [(0, next(sequence), self.start_url, None, "link")]
        self.queued.add(self.start_url)
        self._seed_sitemap(frontier, sequence)

        in_flight = {}
        in_flight_urls: Set[str] = set()
        self._admitted = 0
        self._fetched = 0
        # Admission is counted under a lock rather than from len(self.visited):
        # with many fetches outstanding, each could pass a `visited < max_pages`
        # check before any of them has recorded a result, and the crawl would
        # overshoot the cap.
        lock = threading.Lock()
        # The in-flight bound adapts to the site (see throttle.py). It also
        # keeps the frontier from running far ahead of the work, which is what
        # keeps un-analysed HTML from accumulating.
        self.limit = AdaptiveLimit(initial=self.concurrency, maximum=self.max_concurrency)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            while frontier or in_flight:
                if self.is_stopped:
                    break
                if self.is_paused:
                    time.sleep(0.5)
                    continue

                while (frontier and len(in_flight) < self.limit.limit
                       and time.monotonic() >= self.limit.paused_until):
                    with lock:
                        # Checked before popping: an in-flight result may yet
                        # turn out to be a duplicate and hand its slot back, so
                        # the frontier must survive reaching the cap.
                        if self._admitted >= self.max_pages or self._fetched >= self.fetch_ceiling:
                            break
                    # Heap order alone cannot put sitemap entries last: at the
                    # start the heap holds only the start URL and the sitemap.
                    # So a sitemap entry waits until no link fetch is in flight,
                    # since any of them may yet discover pages that go first.
                    if frontier[0][4] == "sitemap" and any(
                        entry[3] == "link" for entry in in_flight.values()
                    ):
                        break
                    priority, _, url, referrer, via = heapq.heappop(frontier)
                    # A URL can sit in the heap twice (a sitemap entry and a
                    # later link entry); whichever pops second is stale.
                    if url in self.visited or url in in_flight_urls or not self._allowed(url):
                        continue
                    self._sitemap_pending.discard(url)
                    with lock:
                        self._admitted += 1
                        self._fetched += 1
                    # The heap priority is the depth: links are pushed at
                    # depth + 1, sitemap entries at max_depth + 1.
                    in_flight[pool.submit(self._fetch_paced, url)] = (url, priority, referrer, via)
                    in_flight_urls.add(url)

                if not in_flight:
                    wait = self.limit.paused_until - time.monotonic()
                    if frontier and wait > 0:
                        # Paused by Retry-After with nothing outstanding: wait
                        # out the pause rather than ending the crawl.
                        time.sleep(min(wait, 1.0))
                        continue
                    # Nothing outstanding and nothing admissible: the crawl is
                    # done, whether the frontier emptied or the cap was reached.
                    break

                done, _ = concurrent.futures.wait(
                    in_flight, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in done:
                    url, depth, referrer, via = in_flight.pop(future)
                    in_flight_urls.discard(url)
                    fetched = future.result()
                    self.limit.record(
                        fetched.response_time_ms,
                        fetched.throttled or fetched.status_code is None
                        or fetched.status_code in THROTTLE_CODES,
                        fetched.retry_after,
                        time.monotonic(),
                    )
                    self._handle_result(
                        future, url, depth, referrer, via, frontier, sequence,
                        progress_callback, on_page,
                    )

        self._flush_link_progress(force=True)
        return self.results

    def _flush_link_progress(self, force: bool = False) -> None:
        """Emit the running link totals, at most once a second.

        `force` is used once the crawl ends: a crawl that finishes inside the
        flush window would otherwise report a stale total, or none at all.
        """
        if not self.event_callback:
            return
        now = time.monotonic()
        if not force and now - self._last_link_flush < 1.0:
            return
        self._last_link_flush = now
        self.event_callback("link_progress", {
            "internal_total": self._link_counts["internal"],
            "external_total": self._link_counts["external"],
        })

    def _owner_of(self, result: PageResult, url: str) -> Optional[str]:
        """The URL already representing this result, or None if it is a new page.

        Records this result's own claims when it is new. Redirect evidence is
        checked first: it is proof from the server. The body hash is checked
        second, and only for 200 HTML, so an error page or a binary file is
        never declared a duplicate of another.
        """
        if result.error or result.status_code is None:
            return None

        final = normalize_url(result.final_url or url)
        claimant = self.claimed.get(final)
        if claimant is not None and claimant != url:
            result.alias_of = claimant
            self.aliases[url] = claimant
            return claimant

        if (
            (result.html or result.body_hash)
            and result.status_code == 200
            and "text/html" in (result.content_type or "")
        ):
            # A 304 has no body, but carries the hash of the body it stands for.
            digest = result.body_hash or hashlib.sha256(
                result.html.encode("utf-8", errors="ignore")
            ).hexdigest()
            result.body_hash = digest
            first = self.body_owner.get(digest)
            if first is not None:
                result.duplicate_of = first
                self.aliases[url] = first
                self.claimed[final] = first
                return first
            self.body_owner[digest] = url

        self.claimed[final] = url
        if final != url:
            # The redirect target is now represented by this result: a later
            # link straight to it must not fetch it again.
            self.aliases[final] = url
            self.queued.add(final)
        return None

    def _seed_sitemap(self, frontier, sequence) -> None:
        """Queue sitemap-listed pages behind every link-discovered page.

        Priority max_depth + 1 sorts them after anything a link can reach, so
        sitemap-only pages -- often the orphans an audit exists to find -- fill
        whatever cap remains instead of displacing linked pages.
        """
        for url in sorted(self.sitemap_urls):
            if url in self.queued or not same_registrable_domain(url, self.root_netloc):
                continue
            self.queued.add(url)
            self._sitemap_pending.add(url)
            heapq.heappush(frontier, (self.max_depth + 1, next(sequence), url, None, "sitemap"))

    def _handle_result(self, future, url, depth, referrer, via, frontier, sequence,
                       progress_callback, on_page):
        """Record one fetched page and push whatever it links to."""
        result = future.result()
        cached = None
        if result.cache_status == "not_modified":
            cached = self.cached_links(url) if self.cached_links else None
            if cached is None:
                # A 304 with nothing behind it in the cache: there is no body
                # to analyse and no links to follow, so fetch it properly.
                result = self.fetch_unconditional(url)
        result.depth = depth
        result.found_via = via
        if referrer:
            result.referrers.add(referrer)
            self.inbound_links.setdefault(url, set()).add(referrer)
        self.visited.add(url)

        owner = self._owner_of(result, url)
        if owner is not None:
            # Already represented: give the cap slot back, credit the inbound
            # link to the page that represents it, and stop -- no analysis,
            # no link expansion.
            self._admitted -= 1
            self.skipped[url] = result
            moved = self.inbound_links.pop(url, set())
            if moved:
                self.inbound_links.setdefault(owner, set()).update(moved)
            result.html = ""
            if self.event_callback:
                self.event_callback("page_crawled", {
                    "url": result.url,
                    "status": result.status_code,
                    "depth": result.depth,
                    "response_time": result.response_time_ms,
                    "timestamp": time.time() * 1000,
                    "alias_of": result.alias_of,
                    "duplicate_of": result.duplicate_of,
                })
            return

        self.results[url] = result

        if progress_callback:
            progress_callback(len(self.results), self.max_pages, url)
        if self.event_callback:
            self.event_callback("page_crawled", {
                "url": result.url,
                "status": result.status_code,
                "depth": result.depth,
                "response_time": result.response_time_ms,
                "timestamp": time.time() * 1000,
            })

        internal_links, external_links = [], []
        if cached is not None:
            cached_internal, cached_external = cached
            internal_links = [self.aliases.get(link, link) for link in cached_internal]
            external_links = list(cached_external)
        elif result.html:
            for link in self._extract_links(result.final_url, result.html):
                normalized = normalize_url(link)
                if same_registrable_domain(normalized, self.root_netloc):
                    # Resolved through known aliases, so the graph points at the
                    # page that represents the URL rather than at a skipped one.
                    internal_links.append(self.aliases.get(normalized, normalized))
                else:
                    external_links.append(normalized)

        # Links are read before the observer runs, because stage 2 releases the
        # page's markup as soon as it has handed it to a worker -- extracting
        # afterwards would find an empty string and the crawl would stop at the
        # start URL. on_page runs for every page, including at the depth limit
        # and for an empty one: it is how stage 2 receives the page at all.
        if on_page is not None:
            on_page(result)

        self.link_graph[url] = set(internal_links)
        for target in external_links:
            self.external_links.add(target)

        self._link_counts["internal"] += len(internal_links)
        self._link_counts["external"] += len(external_links)
        self._flush_link_progress()

        # A sitemap-only page is analysed, but the sitemap adds the pages it
        # lists, not a second crawl rooted at each of them.
        if depth >= self.max_depth or via == "sitemap":
            return
        for target in internal_links:
            if target in self._sitemap_pending:
                # Found by a link after all: queue it again at its real depth.
                # The sitemap entry is skipped when it pops.
                self._sitemap_pending.discard(target)
                heapq.heappush(frontier, (depth + 1, next(sequence), target, url, "link"))
            elif target not in self.queued and target not in self.visited:
                self.queued.add(target)
                heapq.heappush(frontier, (depth + 1, next(sequence), target, url, "link"))

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
