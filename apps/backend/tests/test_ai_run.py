"""AI Visibility runs: every prompt x model, stored and analysed; failures
isolated; the opt-in weekly job never runs on dry run."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.ai_visibility.providers import Answer, DryRunAI
from app.ai_visibility.run import load_brands, run_project
from app.db.engine import get_session_factory
from app.db.models import AiBrandTerm, AiPrompt, AiRun, AiVisibilityRun, Competitor, Project
from app.scheduler import jobs


def _project(prompts=("best rare books",), schedule=None, last=None, domain="books.toscrape.com"):
    with get_session_factory().begin() as s:
        p = Project(name="Books to Scrape", domain=domain, ai_schedule=schedule, last_ai_run_at=last)
        s.add(p); s.flush()
        s.add(Competitor(project_id=p.id, domain="amazon.com"))
        s.add(AiBrandTerm(project_id=p.id, owner="amazon.com", term="Amazon"))
        s.add(AiBrandTerm(project_id=p.id, owner=domain, term="BTS"))
        for text in prompts:
            s.add(AiPrompt(project_id=p.id, text=text))
        return p.id


class Fixed:
    dry_run = False

    def __init__(self, name, text="", error=None, raises=None):
        self.name, self.model, self.text, self.error, self.raises, self.prompts = name, f"{name}-1", text, error, raises, []

    def ask(self, prompt, brands_hint=None):
        self.prompts.append(prompt)
        if self.raises:
            raise self.raises
        return Answer(self.text, [{"url": "https://books.toscrape.com/x", "title": "x"}], self.model, self.error)


def test_brands_include_project_name_and_competitor_terms():
    pid = _project()
    with get_session_factory()() as s:
        brands = load_brands(s, s.get(Project, pid))
    me = brands[0]
    assert me.is_self and me.domain == "books.toscrape.com" and set(me.terms) == {"BTS", "Books to Scrape"}
    assert brands[1].owner == "amazon.com" and brands[1].terms == ("Amazon",)


def test_every_prompt_by_every_model_is_stored_and_analysed():
    pid = _project(prompts=("q1", "q2"))
    a = Fixed("claude", text="Amazon first, then Books to Scrape.")
    b = Fixed("openai", error="openai HTTP 500: boom")
    c = Fixed("gemini", raises=RuntimeError("bad"))
    result = run_project(pid, providers=[a, b, c])
    assert result["status"] == "ran" and result["calls"] == 6 and result["errors"] == 4 and result["mention_rate"] == 1.0
    assert sorted(a.prompts) == ["q1", "q2"]
    with get_session_factory()() as s:
        rows = s.scalars(select(AiVisibilityRun).where(AiVisibilityRun.run_id == result["run_id"])).all()
        ok = [r for r in rows if r.provider == "claude"]
        assert len(rows) == 6 and all(r.mentioned and r.position == 2 and r.cited for r in ok)
        assert ok[0].brands_json == ["amazon.com", "books.toscrape.com"]
        assert {r.error for r in rows if r.provider == "gemini"} == {"unexpected error (RuntimeError)"}
        run = s.get(AiRun, result["run_id"])
        assert (run.calls, run.errors, run.finished_at is not None) == (6, 4, True)
        assert s.get(Project, pid).last_ai_run_at is not None


def test_long_answers_are_trimmed_and_no_prompts_is_reported():
    pid = _project()
    run_project(pid, providers=[Fixed("claude", text="x" * 9000)])
    with get_session_factory()() as s:
        assert len(s.scalar(select(AiVisibilityRun.answer))) == 8000
    empty = _project(prompts=(), domain="empty.com")
    assert run_project(empty, providers=[Fixed("claude")]) == {"status": "no_prompts"}


def test_dry_run_flags_the_run():
    pid = _project()
    result = run_project(pid, providers=[DryRunAI("claude"), DryRunAI("openai")])
    assert result["dry_run"] is True and result["calls"] == 2


def test_weekly_job_is_opt_in_and_never_dry_run():
    now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
    due = _project(schedule="weekly")
    with get_session_factory().begin() as s:
        p = Project(name="fresh.com", domain="fresh.com", ai_schedule="weekly", last_ai_run_at=now - timedelta(days=1))
        s.add(p); s.flush(); s.add(AiPrompt(project_id=p.id, text="q"))
    assert jobs.run_due_ai_visibility(now=now, providers=[DryRunAI("claude")]) == []
    assert jobs.run_due_ai_visibility(now=now, providers=[Fixed("claude", text="BTS")]) == [due]
