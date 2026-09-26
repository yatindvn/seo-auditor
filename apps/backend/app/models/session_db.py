"""Per-session SQLite store.

One file per audit under `config.SESSION_DIR`. Written during the crawl by a
single writer thread -- SQLite permits one writer, and WAL mode lets the read
endpoints serve while that crawl is still running -- and read back a page at a
time.

This exists because the previous design held every page in a dict for the whole
audit and returned the lot from one endpoint: ~500 MB of retained HTML plus the
assembled result at 5000 pages, and a response too large for the dashboard to
store or parse.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
  url TEXT PRIMARY KEY, final_url TEXT, depth INTEGER, status INTEGER,
  response_time_ms REAL, content_type TEXT, title TEXT, meta_description TEXT,
  h1 TEXT, canonical TEXT, word_count INTEGER, char_count INTEGER,
  internal_links_count INTEGER, external_links_count INTEGER,
  images_count INTEGER, missing_alt_count INTEGER,
  meta_robots TEXT, lang TEXT, error TEXT, issue_count INTEGER DEFAULT 0,
  meta_json TEXT
);
CREATE TABLE IF NOT EXISTS issues (url TEXT, severity TEXT, code TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS links (src TEXT, dst TEXT, internal INTEGER);
CREATE TABLE IF NOT EXISTS signatures (url TEXT PRIMARY KEY, minhash BLOB);
CREATE TABLE IF NOT EXISTS summary (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT);
CREATE INDEX IF NOT EXISTS idx_issues_url ON issues(url);
CREATE INDEX IF NOT EXISTS idx_issues_code ON issues(code);
CREATE INDEX IF NOT EXISTS idx_issues_severity ON issues(severity);
CREATE INDEX IF NOT EXISTS idx_links_src ON links(src);
CREATE INDEX IF NOT EXISTS idx_pages_depth ON pages(depth);
"""

# A sort key reaches SQL as a column name, which cannot be parameterised. It is
# chosen from this set instead of interpolated, so an arbitrary string coming
# from a query parameter cannot become SQL.
SORTABLE = {
    "url", "depth", "status", "word_count", "response_time_ms",
    "internal_links_count", "issue_count",
}

PAGE_COLUMNS = [
    "url", "final_url", "depth", "status", "response_time_ms", "content_type",
    "title", "meta_description", "h1", "canonical", "word_count", "char_count",
    "internal_links_count", "external_links_count", "images_count",
    "missing_alt_count", "meta_robots", "lang", "error", "issue_count",
]

# issue_count is derived from the issues written alongside the row, never read
# from the caller's dict.
_CALLER_COLUMNS = PAGE_COLUMNS[:-1]


class SessionDB:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the writer thread and the request threads are
        # different threads sharing one connection, serialised by SQLite itself.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------ write
    def add_pages(self, rows: List[Dict[str, Any]]) -> None:
        """Insert a batch of page rows and their issues in one transaction.

        Batched because the crawl produces rows continuously and a transaction
        per page would fsync thousands of times.
        """
        page_values = []
        issue_values = []
        for row in rows:
            issues = row.get("issues") or []
            page_values.append(
                tuple(row.get(column) for column in _CALLER_COLUMNS)
                + (len(issues), json.dumps(row.get("meta") or {}))
            )
            issue_values.extend(
                (row["url"], issue["severity"], issue["code"], issue["message"])
                for issue in issues
            )

        placeholders = ",".join("?" * (len(PAGE_COLUMNS) + 1))
        with self._conn:
            # A retried page must replace its row, not add a second one.
            self._conn.executemany(
                "DELETE FROM issues WHERE url = ?", [(row["url"],) for row in rows]
            )
            self._conn.executemany(
                f"INSERT OR REPLACE INTO pages ({','.join(PAGE_COLUMNS)},meta_json) "
                f"VALUES ({placeholders})",
                page_values,
            )
            if issue_values:
                self._conn.executemany("INSERT INTO issues VALUES (?,?,?,?)", issue_values)

    def add_links(self, edges: List[Tuple[str, str, bool]]) -> None:
        with self._conn:
            self._conn.executemany(
                "INSERT INTO links VALUES (?,?,?)",
                [(src, dst, 1 if internal else 0) for src, dst, internal in edges],
            )

    def add_signature(self, url: str, signature: bytes) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO signatures VALUES (?,?)", (url, signature)
            )

    def set_summary(self, summary: Dict[str, Any]) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO summary (id, json) VALUES (1, ?)",
                (json.dumps(summary),),
            )

    # ------------------------------------------------------------------- read
    def get_summary(self) -> Optional[Dict[str, Any]]:
        row = self._conn.execute("SELECT json FROM summary WHERE id = 1").fetchone()
        return json.loads(row["json"]) if row else None

    def _row_to_page(self, row: sqlite3.Row) -> Dict[str, Any]:
        page = {column: row[column] for column in PAGE_COLUMNS}
        page["meta"] = json.loads(row["meta_json"] or "{}")
        return page

    def get_pages(
        self,
        offset: int = 0,
        limit: int = 50,
        sort: str = "depth",
        order: str = "asc",
        filter_text: Optional[str] = None,
        status: Optional[int] = None,
        has_issues: Optional[bool] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Return (rows, total). `total` counts every matching row, not just the
        returned slice, so a client can size its pagination."""
        if sort not in SORTABLE:
            raise ValueError(f"unsortable column {sort!r}; allowed: {sorted(SORTABLE)}")
        direction = "DESC" if str(order).lower() == "desc" else "ASC"

        where: List[str] = []
        params: List[Any] = []
        if filter_text:
            where.append("url LIKE ?")
            params.append(f"%{filter_text}%")
        if status is not None:
            where.append("status = ?")
            params.append(status)
        if has_issues is not None:
            where.append("issue_count > 0" if has_issues else "issue_count = 0")
        clause = f" WHERE {' AND '.join(where)}" if where else ""

        total = self._conn.execute(
            f"SELECT COUNT(*) AS c FROM pages{clause}", params
        ).fetchone()["c"]
        # url as a tiebreaker keeps paging stable when the sort column ties.
        rows = self._conn.execute(
            f"SELECT * FROM pages{clause} ORDER BY {sort} {direction}, url ASC "
            f"LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [self._row_to_page(row) for row in rows], total

    def get_issues(
        self,
        offset: int = 0,
        limit: int = 50,
        severity: Optional[str] = None,
        code: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        where: List[str] = []
        params: List[Any] = []
        if severity:
            where.append("severity = ?")
            params.append(severity)
        if code:
            where.append("code = ?")
            params.append(code)
        clause = f" WHERE {' AND '.join(where)}" if where else ""

        total = self._conn.execute(
            f"SELECT COUNT(*) AS c FROM issues{clause}", params
        ).fetchone()["c"]
        rows = self._conn.execute(
            f"SELECT * FROM issues{clause} ORDER BY url LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [dict(row) for row in rows], total

    def get_page(self, url: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM pages WHERE url = ?", (url,)).fetchone()
        return self._row_to_page(row) if row else None

    def get_signatures(self) -> Dict[str, bytes]:
        return {
            row["url"]: row["minhash"]
            for row in self._conn.execute("SELECT url, minhash FROM signatures")
        }

    def get_links(self) -> List[Tuple[str, str]]:
        """Internal edges only: this feeds PageRank, which scores the site's own
        link graph."""
        return [
            (row["src"], row["dst"])
            for row in self._conn.execute("SELECT src, dst FROM links WHERE internal = 1")
        ]

    def close(self) -> None:
        self._conn.close()
