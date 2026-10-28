"""Per-site cache of HTML analyses, reused across audits.

One SQLite file per site. An entry is the HTML half of a page's analysis
(page_pipeline.HtmlAnalysis) plus the validators needed to ask the server
whether the page changed. It is usable only while its analyzer fingerprint
matches -- so editing any check, or auditing with different options, can never
serve a stale result -- and while younger than PAGE_CACHE_MAX_AGE_DAYS.

Every failure here is a cache miss, never an audit failure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import urllib.parse as up
import zlib
from pathlib import Path
from typing import Dict, List, Optional

from app.config import config
from app.crawler.crawler import Validators
from app.services.page_pipeline import HtmlAnalysis

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
  url TEXT PRIMARY KEY, etag TEXT, last_modified TEXT, body_hash TEXT,
  headers_json TEXT, html_blob BLOB, signature BLOB,
  fingerprint TEXT, analysed_at REAL
);
"""

APP_DIR = Path(__file__).resolve().parent.parent
# The code an HTML analysis depends on. A change to any of these files makes
# every cached analysis unusable, with no version number to remember to bump.
FINGERPRINT_SOURCES = (
    "auditor/checks.py",
    "services/page_pipeline.py",
    "utils/performance.py",
    "seo/keyword_extraction.py",
    "analysis/minhash.py",
    "rules/engine.py",
)


def _read_source(rel: str) -> bytes:
    return (APP_DIR / rel).read_bytes()


def analyzer_fingerprint(
    enable_keyword_analysis: bool,
    target_keywords: Optional[List[str]],
    compute_signature: bool,
    rules_digest: str = "",
) -> str:
    digest = hashlib.sha256()
    for rel in FINGERPRINT_SOURCES:
        digest.update(rel.encode())
        digest.update(_read_source(rel))
    options = {
        "keyword_analysis": bool(enable_keyword_analysis),
        "target_keywords": sorted(target_keywords or []),
        "signature": bool(compute_signature),
    }
    if rules_digest:
        options["rules"] = rules_digest
    digest.update(json.dumps(options, sort_keys=True).encode())
    return digest.hexdigest()


def cache_file_name(start_url: str) -> str:
    netloc = up.urlsplit(start_url).netloc.lower().replace(":", "_")
    return f"{netloc or 'unknown'}.db"


class PageCache:
    def __init__(self, path: Path, fingerprint: str, max_age_days: int, clock) -> None:
        self._fingerprint = fingerprint
        self._max_age = max_age_days * 86400
        self._clock = clock
        self._warned = False
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @classmethod
    def open(cls, cache_dir: Path, start_url: str, fingerprint: str,
             max_age_days: int = config.PAGE_CACHE_MAX_AGE_DAYS,
             clock=time.time) -> Optional["PageCache"]:
        path = Path(cache_dir) / cache_file_name(start_url)
        try:
            return cls(path, fingerprint, max_age_days, clock)
        except Exception as exc:
            logger.warning("Page cache %s unusable, auditing without it: %s", path, exc)
            return None

    def _warn(self, action: str, exc: Exception) -> None:
        if not self._warned:
            logger.warning("Page cache %s failed, continuing without it: %s", action, exc)
            self._warned = True

    def _usable_clause(self):
        return "fingerprint = ? AND analysed_at >= ?", (
            self._fingerprint, self._clock() - self._max_age,
        )

    def validators(self) -> Dict[str, Validators]:
        clause, params = self._usable_clause()
        try:
            rows = self._conn.execute(
                f"SELECT url, etag, last_modified, body_hash, headers_json FROM pages WHERE {clause}",
                params,
            ).fetchall()
        except sqlite3.Error as exc:
            self._warn("read", exc)
            return {}
        return {
            url: Validators(etag=etag, last_modified=last_modified, body_hash=body_hash,
                            headers=json.loads(headers_json or "{}"))
            for url, etag, last_modified, body_hash, headers_json in rows
        }

    def get_html_part(self, url: str) -> Optional[HtmlAnalysis]:
        clause, params = self._usable_clause()
        try:
            row = self._conn.execute(
                f"SELECT html_blob, signature FROM pages WHERE url = ? AND {clause}",
                (url, *params),
            ).fetchone()
            if row is None:
                return None
            data = json.loads(zlib.decompress(row[0]))
            return HtmlAnalysis.from_json(data, signature=row[1])
        except Exception as exc:
            self._warn("read", exc)
            return None

    def put(self, url: str, validators: Validators, html_part: HtmlAnalysis) -> None:
        try:
            blob = zlib.compress(json.dumps(html_part.to_json()).encode("utf-8"))
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?,?)",
                    (url, validators.etag, validators.last_modified, validators.body_hash,
                     json.dumps(validators.headers or {}), blob, html_part.signature,
                     self._fingerprint, self._clock()),
                )
        except Exception as exc:
            self._warn("write", exc)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
