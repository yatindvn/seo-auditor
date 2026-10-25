"""Daily rank checks write history, and a simulated drop fires one alert."""

from datetime import timedelta

from app.db.engine import get_session_factory
from app.db.models import Keyword, Project, RankCheck, utcnow
from app.providers.dry_run import DryRunProvider
from app.providers.serp import SerpItem, SerpResult
from app.scheduler import jobs


class SequenceProvider:
    """A live-looking provider whose SERP changes between calls."""
    name = "dataforseo"

    def __init__(self, positions):
        self.positions = list(positions)

    def search(self, query):
        position = self.positions.pop(0)
        items = [SerpItem(p, f"https://filler{p}.test/", f"filler{p}.test") for p in range(1, 20) if p != position]
        items.append(SerpItem(position, "https://example.com/espresso", "example.com"))
        return SerpResult(items=sorted(items, key=lambda i: i.position), provider=self.name)


class Recorder:
    def __init__(self, channel):
        self.channel, self.sent = channel, []

    def send(self, subject, text):
        self.sent.append((subject, text))


def _tracked_project(schedule="daily"):
    with get_session_factory().begin() as s:
        p = Project(name="example.com", domain="example.com", audit_options_json={}, rank_schedule=schedule)
        s.add(p)
        s.flush()
        s.add(Keyword(project_id=p.id, phrase="espresso", country="US", device="desktop"))
        return p.id


def test_scheduled_daily_checks_write_history_and_alert_once_on_a_drop():
    """The Phase 2 definition of done."""
    project_id = _tracked_project()
    provider = SequenceProvider([4, 9])
    slack, email = Recorder("slack"), Recorder("email")
    day1 = utcnow()

    assert jobs.run_due_rank_checks(now=day1, provider=provider, notifiers=[slack, email]) == [project_id]
    assert jobs.run_due_rank_checks(now=day1 + timedelta(hours=2), provider=provider,
                                    notifiers=[slack, email]) == []          # not due yet
    assert jobs.run_due_rank_checks(now=day1 + timedelta(hours=25), provider=provider,
                                    notifiers=[slack, email]) == [project_id]

    with get_session_factory()() as s:
        assert [c.position for c in s.query(RankCheck).order_by(RankCheck.id)] == [4, 9]
    assert len(slack.sent) == 1 and len(email.sent) == 1
    assert "4 → 9" in slack.sent[0][1] and "dropped" in slack.sent[0][1]


def test_dry_run_never_writes_history():
    _tracked_project()
    assert jobs.run_due_rank_checks(provider=DryRunProvider()) == []
    with get_session_factory()() as s:
        assert s.query(RankCheck).count() == 0


def test_projects_without_enabled_keywords_or_schedule_are_not_due():
    unscheduled = _tracked_project(schedule=None)
    with get_session_factory().begin() as s:
        empty = Project(name="empty.com", domain="empty.com", audit_options_json={}, rank_schedule="daily")
        s.add(empty)
    assert jobs.run_due_rank_checks(provider=SequenceProvider([1])) == []
    assert unscheduled


def test_cron_runs_both_jobs(monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import config
    from app.main import app

    monkeypatch.setattr(config, "CRON_SECRET", "s")
    ran = []
    monkeypatch.setattr(jobs, "run_due_audits", lambda: ran.append("audits") or [])
    monkeypatch.setattr(jobs, "run_due_rank_checks", lambda: ran.append("ranks") or [])

    assert TestClient(app).post("/api/cron/run", headers={"Authorization": "Bearer s"}).status_code == 202
    assert ran == ["audits", "ranks"]
