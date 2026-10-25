"""Import audits saved before the central DB existed. Safe to re-run: any
session already imported is skipped.

    cd apps/backend
    python -m app.db.import_sessions [--session-dir DIR]
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from sqlalchemy import select

from app.config import config
from app.db import audit_store
from app.db.engine import get_session_factory
from app.db.models import Audit
from app.models.session_db import SessionDB

logger = logging.getLogger("seo_auditor")


def import_all(session_dir: Path, factory) -> Dict[str, int]:
    counts = {"imported": 0, "skipped": 0, "failed": 0}
    with factory() as session:
        known = set(session.scalars(select(Audit.session_id)).all())

    # Session files only: the central DB lives in central/, page caches in
    # page_cache/, and the glob does not descend into either.
    for path in sorted(Path(session_dir).glob("*.db")):
        session_id = path.stem
        if session_id in known:
            counts["skipped"] += 1
            continue
        db = SessionDB(path)
        try:
            summary = db.get_summary() or {}
            result = summary.get("auditResult")
            if not result or not summary.get("url"):
                counts["skipped"] += 1      # a crawl that never finished
                continue
            saved_ns = int(summary.get("saved_at") or 0)
            started = datetime.fromtimestamp(saved_ns / 1e9, tz=timezone.utc) if saved_ns else None
            audit_store.record_audit(factory, db, result, session_id=session_id,
                                     start_url=summary["url"], trigger="import", started_at=started)
            counts["imported"] += 1
        except Exception as exc:
            logger.error("Could not import %s: %s", path.name, exc, exc_info=exc)
            counts["failed"] += 1
        finally:
            db.close()
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", default=str(config.SESSION_DIR))
    args = parser.parse_args(argv)
    counts = import_all(Path(args.session_dir), get_session_factory())
    print(f"imported {counts['imported']}, skipped {counts['skipped']}, failed {counts['failed']}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
