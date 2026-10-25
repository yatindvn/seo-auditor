"""One SERP per keyword: my position, my ranking URL, competitors' positions."""

import pytest

from app.db.engine import get_session_factory
from app.db.models import Competitor, Keyword, Project, RankCheck
from app.providers.dry_run import DryRunProvider
from app.providers.serp import ProviderSkipped, SerpItem
from app.rank import tracker

SERP = [
    SerpItem(1, "https://rival.org/a", "rival.org"),
    SerpItem(2, "https://blog.example.com/espresso", "blog.example.com"),
    SerpItem(3, "https://example.com/espresso", "example.com"),
    SerpItem(5, "https://other.net/", "other.net"),
]


def _project(keywords=("espresso",), competitors=("rival.org", "absent.io")):
    with get_session_factory().begin() as s:
        p = Project(name="example.com", domain="example.com", audit_options_json={})
        s.add(p)
        s.flush()
        for phrase in keywords:
            s.add(Keyword(project_id=p.id, phrase=phrase, country="US", device="desktop"))
        for d in competitors:
            s.add(Competitor(project_id=p.id, domain=d))
        s.flush()
        return p.id


def test_position_counts_subdomains_as_mine():
    assert tracker.position_for(SERP, "example.com") == (2, "https://blog.example.com/espresso")
    assert tracker.position_for(SERP, "nowhere.com") == (None, None)


def test_a_run_records_position_url_competitors_and_serp():
    project_id = _project()
    report = tracker.run_project(project_id, provider=DryRunProvider(items=SERP))

    assert report.checked == 1 and report.skipped == 0
    with get_session_factory()() as s:
        check = s.query(RankCheck).one()
        assert check.status == "ranked" and check.position == 2
        assert check.ranking_url == "https://blog.example.com/espresso"
        assert check.competitor_positions_json == {"rival.org": 1, "absent.io": None}
        assert check.serp_json[0] == {"position": 1, "url": "https://rival.org/a", "domain": "rival.org"}
        assert check.audit_id is None and check.provider == "dry_run"


def test_not_ranking_is_recorded_as_not_ranked():
    project_id = _project()
    tracker.run_project(project_id, provider=DryRunProvider(items=[SERP[0]]))
    with get_session_factory()() as s:
        assert s.query(RankCheck).one().status == "not_ranked"


def test_a_skipped_call_records_why_and_the_run_continues():
    project_id = _project(keywords=("espresso", "grinder"))

    class Capped:
        name = "dataforseo"
        calls = 0

        def search(self, query):
            Capped.calls += 1
            if Capped.calls == 1:
                raise ProviderSkipped("daily cap of 1 dataforseo calls reached")
            return DryRunProvider(items=SERP).search(query)

    report = tracker.run_project(project_id, provider=Capped())
    assert report.checked == 2 and report.skipped == 1
    with get_session_factory()() as s:
        notes = {c.status: c.note for c in s.query(RankCheck).all()}
        assert "cap" in notes["skipped"]


def test_disabled_keywords_are_not_checked():
    project_id = _project(keywords=("espresso", "grinder"))
    with get_session_factory().begin() as s:
        s.query(Keyword).filter_by(phrase="grinder").update({"enabled": False})
    report = tracker.run_project(project_id, provider=DryRunProvider(items=SERP))
    assert report.checked == 1


def test_previous_real_check_skips_over_skipped_ones():
    project_id = _project()
    factory = get_session_factory()
    tracker.run_project(project_id, provider=DryRunProvider(items=SERP))

    class Down:
        name = "dataforseo"

        def search(self, query):
            raise ProviderSkipped("cap")

    tracker.run_project(project_id, provider=Down())
    with factory() as s:
        last = s.query(RankCheck).order_by(RankCheck.id.desc()).first()
        previous = tracker.previous_real_check(s, last.keyword_id, last.id)
        assert previous.status == "ranked" and previous.position == 2
