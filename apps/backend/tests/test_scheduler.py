"""Scheduled audits: due projects run once, from either trigger."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import config
from app.db.engine import get_session_factory
from app.db.models import Project, utcnow
from app.main import app
from app.scheduler import jobs


def _project(domain, schedule, last=None, options=None):
    with get_session_factory().begin() as s:
        p = Project(name=domain, domain=domain, audit_schedule=schedule,
                    audit_options_json=options or {}, last_scheduled_at=last)
        s.add(p)
        s.flush()
        return p.id


def _runner(calls):
    def run(**kwargs):
        calls.append(kwargs)
        return {}
    return run


def test_only_due_projects_run():
    now = utcnow()
    _project("daily-due.com", "daily", last=now - timedelta(hours=25))
    _project("daily-fresh.com", "daily", last=now - timedelta(hours=2))
    _project("weekly-due.com", "weekly", last=now - timedelta(days=8))
    _project("weekly-fresh.com", "weekly", last=now - timedelta(days=3))
    _project("never.com", "daily")
    _project("unscheduled.com", None)
    calls = []

    jobs.run_due_audits(now=now, runner=_runner(calls))

    assert sorted(c["url"] for c in calls) == [
        "https://daily-due.com/", "https://never.com/", "https://weekly-due.com/",
    ]
    assert all(c["trigger"] == "scheduled" for c in calls)


def test_project_options_are_passed_to_the_audit():
    _project("opts.com", "daily", options={"max_pages": 40, "max_depth": 3, "ignore_robots": True})
    calls = []

    jobs.run_due_audits(runner=_runner(calls))

    assert calls[0]["max_pages"] == 40 and calls[0]["max_depth"] == 3 and calls[0]["ignore_robots"] is True


def test_render_js_comes_from_the_project_options():
    _project("render.com", "daily", options={"render_js": True})
    _project("plain.com", "daily")
    calls = []

    jobs.run_due_audits(runner=_runner(calls))

    by_url = {c["url"]: c["render_js"] for c in calls}
    assert by_url == {"https://render.com/": True, "https://plain.com/": False}


def test_accessibility_comes_from_the_project_options():
    _project("a11y.com", "daily", options={"accessibility": True})
    _project("plain2.com", "daily")
    calls = []

    jobs.run_due_audits(runner=_runner(calls))

    assert {c["url"]: c["accessibility"] for c in calls} == {
        "https://a11y.com/": True, "https://plain2.com/": False}

def test_a_project_is_claimed_once():
    project_id = _project("race.com", "daily")
    now = utcnow()
    with get_session_factory()() as s:
        assert jobs.claim(s, project_id, None, now) is True
    with get_session_factory()() as s:
        assert jobs.claim(s, project_id, None, now) is False      # the other trigger lost


def test_one_failing_audit_does_not_stop_the_rest():
    _project("a-fails.com", "daily")
    _project("b-works.com", "daily")
    calls = []

    def runner(**kwargs):
        if "a-fails" in kwargs["url"]:
            raise RuntimeError("boom")
        calls.append(kwargs)
        return {}

    started = jobs.run_due_audits(runner=runner)

    assert [c["url"] for c in calls] == ["https://b-works.com/"]
    assert len(started) == 1


@pytest.fixture
def client():
    return TestClient(app)


def test_cron_route_is_absent_without_a_secret(client, monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", "")
    assert client.post("/api/cron/run").status_code == 404


def test_cron_route_rejects_a_wrong_token(client, monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", "s3cret")
    assert client.post("/api/cron/run").status_code == 401
    assert client.post("/api/cron/run", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_cron_route_runs_due_audits(client, monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", "s3cret")
    ran = []
    monkeypatch.setattr(jobs, "run_due_audits", lambda: ran.append(True) or [])

    response = client.post("/api/cron/run", headers={"Authorization": "Bearer s3cret"})

    assert response.status_code == 202
    assert ran == [True]
