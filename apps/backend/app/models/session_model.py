"""Audit history: an index over per-session SQLite files.

This used to be a list of up to 50 complete audit results held in process
memory. That was affordable only while audits were small -- at 5000 pages one
result is tens of megabytes -- and every one of them was lost on restart, so a
redeploy erased the history the dashboard compares against.

Each audit is now a file under `config.SESSION_DIR`. The public methods keep the
shapes `app/api/routes.py` and the dashboard's historical-comparison panel
already read.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import config
from app.models.session_db import SessionDB


class SessionStore:
    # Twenty audits of history, against fifty before. Each is now a file rather
    # than a resident dict, but they are not free: the dashboard reads them.
    RETENTION = 20

    def __init__(self, session_dir: Optional[Path] = None) -> None:
        self._dir = Path(session_dir) if session_dir is not None else Path(config.SESSION_DIR)
        # Deliberately not created here: importing this module must not have the
        # side effect of making a directory, since it is imported by tests and by
        # tooling that never writes a session.
        self._open: Dict[str, SessionDB] = {}

    # ------------------------------------------------------------- internals
    def _ensure_dir(self) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._dir

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.db"

    def _close(self, session_id: str) -> None:
        db = self._open.pop(session_id, None)
        if db is not None:
            db.close()

    def _saved_at(self, path: Path) -> int:
        """Ordering key. Read from the file rather than taken from its mtime:
        mtime resolution is coarse enough on some filesystems that two audits
        saved in the same moment would order arbitrarily."""
        db = SessionDB(path)
        try:
            summary = db.get_summary() or {}
        finally:
            db.close()
        return int(summary.get("saved_at") or 0)

    def _enforce_retention(self) -> None:
        files = sorted(self._dir.glob("*.db"), key=self._saved_at, reverse=True)
        for stale in files[self.RETENTION:]:
            self._close(stale.stem)
            stale.unlink(missing_ok=True)

    # ----------------------------------------------------------------- write
    def open_session(self, session_id: str) -> SessionDB:
        """Create (or reopen) this session's database and return it for writing."""
        self._ensure_dir()
        self._close(session_id)
        db = SessionDB(self._path(session_id))
        self._open[session_id] = db
        return db

    def save_session(self, session_data: Dict[str, Any]) -> None:
        """Store one finished audit.

        The result still arrives whole here; the crawl pipeline will write rows
        as it goes instead, and this becomes the summary-only path.
        """
        session_id = session_data["id"]
        db = self.open_session(session_id)
        db.set_summary({
            "url": session_data.get("url"),
            "timestamp": session_data.get("timestamp"),
            "saved_at": time.time_ns(),
            "auditResult": session_data.get("auditResult") or {},
        })
        self._enforce_retention()

    # ------------------------------------------------------------------ read
    def get(self, session_id: str) -> Optional[SessionDB]:
        if session_id in self._open:
            return self._open[session_id]
        path = self._path(session_id)
        if not path.exists():
            return None
        db = SessionDB(path)
        self._open[session_id] = db
        return db

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        db = self.get(session_id)
        if db is None:
            return None
        summary = db.get_summary() or {}
        return {
            "id": session_id,
            "url": summary.get("url"),
            "timestamp": summary.get("timestamp"),
            "auditResult": summary.get("auditResult", {}),
        }

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Newest first. Carries `auditResult`, which the dashboard's history
        panel reads directly to restore a past audit."""
        if not self._dir.exists():
            return []
        sessions = []
        for path in self._dir.glob("*.db"):
            db = SessionDB(path)
            try:
                summary = db.get_summary() or {}
            finally:
                db.close()
            sessions.append({
                "id": path.stem,
                "url": summary.get("url"),
                "timestamp": summary.get("timestamp"),
                "auditResult": summary.get("auditResult", {}),
                "_saved_at": int(summary.get("saved_at") or 0),
            })
        sessions.sort(key=lambda s: (s["_saved_at"], s["id"]), reverse=True)
        for session in sessions:
            session.pop("_saved_at")
        return sessions

    def delete_session(self, session_id: str) -> bool:
        path = self._path(session_id)
        if not path.exists():
            return False
        self._close(session_id)
        path.unlink(missing_ok=True)
        return True

    def get_history_comparison(self, current_audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sessions = self.get_all_sessions()
        if len(sessions) < 2:
            return None
        previous = sessions[1].get("auditResult", {})

        curr_score = current_audit.get("executive_summary", {}).get("health_score", {}).get("score", 0)
        prev_score = previous.get("executive_summary", {}).get("health_score", {}).get("score", 0)

        curr_recs = {r["code"] for r in current_audit.get("recommendations", [])}
        prev_recs = {r["code"] for r in previous.get("recommendations", [])}

        new_issues = list(curr_recs - prev_recs)
        resolved_issues = list(prev_recs - curr_recs)

        return {
            "previousDate": previous.get("executive_summary", {}).get("audit_date", ""),
            "currentDate": current_audit.get("executive_summary", {}).get("audit_date", ""),
            "scoreChange": round(curr_score - prev_score, 1),
            "previousScore": prev_score,
            "currentScore": curr_score,
            "newIssuesCount": len(new_issues),
            "resolvedIssuesCount": len(resolved_issues),
            "newIssues": new_issues,
            "resolvedIssues": resolved_issues,
            "pagesCountDelta": len(current_audit.get("pages", [])) - len(previous.get("pages", [])),
        }


session_store = SessionStore()
