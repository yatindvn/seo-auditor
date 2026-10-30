"""Search Console tables and the project's property setting."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db.engine import get_session_factory
from app.db.models import GscDaily, Project
from app.main import app


def test_daily_rows_are_unique_per_project_and_date():
    with get_session_factory().begin() as s:
        p = Project(name="a.com", domain="a.com"); s.add(p); s.flush()
        s.add(GscDaily(project_id=p.id, date=date(2026, 10, 1), clicks=1, impressions=10, ctr=0.1, position=5))
    with pytest.raises(IntegrityError):
        with get_session_factory().begin() as s:
            s.add(GscDaily(project_id=p.id, date=date(2026, 10, 1), clicks=2, impressions=10, ctr=0.2, position=4))


def test_property_is_set_and_cleared_through_patch():
    client = TestClient(app)
    pid = client.post("/api/projects", json={"domain": "shop.com"}).json()["id"]
    body = client.patch(f"/api/projects/{pid}", json={"gsc_property": "sc-domain:shop.com"}).json()
    assert body["gsc_property"] == "sc-domain:shop.com" and body["last_gsc_sync_at"] is None
    assert client.patch(f"/api/projects/{pid}", json={"gsc_property": ""}).json()["gsc_property"] is None
