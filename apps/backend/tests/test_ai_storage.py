"""AI Visibility tables and the opt-in weekly schedule."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db.engine import get_session_factory
from app.db.models import AiBrandTerm, Project
from app.main import app


def test_schedule_opt_in():
    client = TestClient(app)
    p = client.post("/api/projects", json={"domain": "shop.com"}).json()
    assert p["ai_schedule"] is None and p["last_ai_run_at"] is None
    assert client.patch(f"/api/projects/{p['id']}", json={"ai_schedule": "weekly"}).json()["ai_schedule"] == "weekly"
    assert client.patch(f"/api/projects/{p['id']}", json={"ai_schedule": "daily"}).status_code == 422


def test_brand_terms_are_unique_per_owner():
    with get_session_factory().begin() as s:
        p = Project(name="shop.com", domain="shop.com"); s.add(p); s.flush()
        s.add(AiBrandTerm(project_id=p.id, owner="shop.com", term="Shop"))
    with pytest.raises(IntegrityError):
        with get_session_factory().begin() as s:
            s.add(AiBrandTerm(project_id=p.id, owner="shop.com", term="Shop"))
