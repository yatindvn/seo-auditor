"""Keywords competitors win that I don't, ranked by opportunity."""

import pytest

from app.keywords import gap
from app.providers.keywords import RankedKeyword as R


class Data:
    name = "dataforseo"

    def __init__(self, ranked):
        self.ranked, self.calls = ranked, []

    def ranked_keywords(self, domain, country, language, limit):
        self.calls.append(domain)
        return self.ranked.get(domain, [])


RANKED = {
    "example.com": [R("espresso machine", 5, "https://example.com/e", 9000, 60),
                    R("deep page", 150, "https://example.com/d", 500, 10)],
    "rival.org": [R("espresso machine", 1, "https://rival.org/e", 9000, 60),       # I rank: no gap
                  R("milk frother", 4, "https://rival.org/m", 4000, 20),
                  R("descaling", 25, "https://rival.org/d", 3000, 10),            # rival too low
                  R("deep page", 8, "https://rival.org/dp", 500, 10)],             # I'm beyond 100: gap
    "other.net": [R("milk frother", 2, "https://other.net/m", 4000, 20),
                  R("grinder", 9, "https://other.net/g", 8000, None)],
}


def test_gap_rules_and_opportunity_order():
    result = gap.content_gap("example.com", ["https://www.rival.org/", "other.net"], data=Data(RANKED))
    assert [r["keyword"] for r in result.rows] == ["grinder", "milk frother", "deep page"]
    frother = result.rows[1]
    assert frother["competitors"] == {"rival.org": {"position": 4, "url": "https://rival.org/m"},
                                      "other.net": {"position": 2, "url": "https://other.net/m"}}
    assert frother["best_competitor_position"] == 2
    assert result.rows[0]["opportunity"] == gap.opportunity(8000, None) == 4000.0
    assert result.total_gaps == 3 and result.competitors == ["rival.org", "other.net"]


def test_one_call_per_domain():
    data = Data(RANKED)
    gap.content_gap("example.com", ["rival.org", "other.net"], data=data)
    assert data.calls == ["example.com", "rival.org", "other.net"]


def test_opportunity_defaults():
    assert gap.opportunity(None, 30) == 0
    assert gap.opportunity(1000, 30) == 700.0


@pytest.mark.parametrize("competitors", [[], ["example.com"], [f"c{i}.com" for i in range(6)]])
def test_competitor_count_is_validated(competitors):
    with pytest.raises(ValueError):
        gap.content_gap("example.com", competitors, data=Data({}))


def test_dry_run_is_labelled():
    from app.providers.dry_run_keywords import DryRunKeywordProvider
    result = gap.content_gap("example.com", ["rival.org"], data=DryRunKeywordProvider())
    assert result.dry_run is True and result.rows
