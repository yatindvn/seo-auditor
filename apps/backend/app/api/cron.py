"""POST /api/cron/run -- lets an external cron service trigger due audits.

Absent (404) until CRON_SECRET is set, so an unconfigured deployment exposes
nothing; otherwise the bearer token must match, compared in constant time.
"""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from app.config import config
from app.scheduler import jobs

router = APIRouter()


@router.post("/cron/run", status_code=202)
def cron_run(background_tasks: BackgroundTasks, authorization: Optional[str] = Header(default=None)):
    if not config.CRON_SECRET:
        raise HTTPException(status_code=404, detail="Not Found")
    expected = f"Bearer {config.CRON_SECRET}"
    if not authorization or not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid cron token")
    background_tasks.add_task(jobs.run_due_audits)
    return {"status": "accepted"}
