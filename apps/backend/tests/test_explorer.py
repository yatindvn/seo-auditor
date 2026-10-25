"""Exploring a seed: ideas, metrics, the traffic estimate, clusters."""

import pytest

from app.keywords import explorer
from app.providers.keywords import KeywordMetrics
from app.providers.serp import ProviderSkipped, SerpItem, SerpResult
from app.seo import keyword_suggestions


@pytest.fixture(autouse=True)
def no_real_autocomplete(monkeypatch):
    monkeypatch.setattr(keyword_suggestions, "_autocomplete_suggestions",
                        lambda seed: ["Espresso Machine Price", "espresso machine", "best  espresso machine"])


class Data:
    name = "dataforseo"

    def __init__(self, volumes=None, kd=None, fail=None):
        self.volumes, self.kd, self.fail, self.calls = volumes or {}, kd or {}, fail, []

    def metrics(self, keywords, country, language):
        self.calls.append(("metrics", list(keywords)))
        if self.fail:
            raise self.fail
        return {k: KeywordMetrics(k, self.volumes.get(k), 1.0, "LOW") for k in keywords}

    def difficulty(self, keywords, country, language):
        self.calls.append(("difficulty", list(keywords)))
        return {k: v for k, v in self.kd.items() if k in keywords}


class Serp:
    name = "dataforseo"

    def __init__(self, tops=None, questions=None, skip=()):
        self.tops, self.questions, self.skip, self.calls = tops or {}, questions or [], set(skip), []

    def search(self, query):
        self.calls.append(query.keyword)
        if query.keyword in self.skip:
            raise ProviderSkipped("cap")
        urls = self.tops.get(query.keyword, [f"https://{query.keyword.replace(' ', '')}{i}.test/" for i in range(10)])
        return SerpResult(items=[SerpItem(i + 1, u, u.split('/')[2]) for i, u in enumerate(urls)],
                          provider=self.name,
                          questions=self.questions if query.keyword == "espresso machine" else [])


def test_ideas_merge_autocomplete_and_people_also_ask_without_the_seed():
    serp = Serp(questions=["Is an espresso machine worth it?"])
    result = explorer.explore("Espresso Machine", serp=serp, data=Data())
    by_keyword = {k["keyword"]: k["source"] for k in result.keywords}
    assert by_keyword == {
        "espresso machine": "seed",
        "espresso machine price": "autocomplete",
        "best espresso machine": "autocomplete",
        "is an espresso machine worth it?": "people_also_ask",
    }
    assert serp.calls == ["espresso machine"]


def test_metrics_and_difficulty_are_one_call_each():
    data = Data(volumes={"espresso machine": 1000}, kd={"espresso machine": 60})
    explorer.explore("espresso machine", serp=Serp(), data=data)
    assert [c[0] for c in data.calls] == ["metrics", "difficulty"]


def test_traffic_estimate_and_sorting():
    data = Data(volumes={"espresso machine": 1000, "best espresso machine": 5000})
    rows = explorer.explore("espresso machine", serp=Serp(), data=data).keywords
    assert [r["keyword"] for r in rows][:2] == ["best espresso machine", "espresso machine"]
    assert rows[0]["traffic_potential_estimate"] == round(5000 * explorer.CTR_TOP1)
    assert rows[-1]["search_volume"] is None


def test_ideas_are_capped(monkeypatch):
    monkeypatch.setattr(keyword_suggestions, "_autocomplete_suggestions",
                        lambda seed: [f"idea {i}" for i in range(80)])
    result = explorer.explore("seed", serp=Serp(), data=Data())
    assert len(result.keywords) == 1 + explorer.MAX_IDEAS


def test_a_metrics_failure_still_returns_ideas_with_a_note():
    result = explorer.explore("espresso machine", serp=Serp(), data=Data(fail=RuntimeError("boom")))
    assert result.keywords and all(k["search_volume"] is None for k in result.keywords)
    assert any("RuntimeError" in n for n in result.notes)


def test_the_cap_is_raised_to_the_caller():
    with pytest.raises(ProviderSkipped):
        explorer.explore("espresso machine", serp=Serp(), data=Data(fail=ProviderSkipped("cap")))


def test_clustering_joins_keywords_sharing_three_urls_transitively():
    shared_ab = [f"https://ab{i}.test/" for i in range(3)]
    shared_bc = [f"https://bc{i}.test/" for i in range(3)]
    tops = {
        "a": shared_ab + [f"https://a{i}.test/" for i in range(7)],
        "b": shared_ab + shared_bc + [f"https://b{i}.test/" for i in range(4)],
        "c": shared_bc + [f"https://c{i}.test/" for i in range(7)],
        "d": [f"https://d{i}.test/" for i in range(10)],
    }
    clusters, notes = explorer.cluster_keywords(["a", "b", "c", "d", "e"], Serp(tops=tops, skip={"e"}), "US", "en")
    assert sorted(map(sorted, clusters)) == [["a", "b", "c"], ["d"]]
    assert any("e" in n for n in notes)


def test_clustering_is_capped_and_reuses_the_seed_serp():
    serp = Serp()
    explorer.cluster_keywords([f"k{i}" for i in range(30)], serp, "US", "en",
                              prefetched={"k0": SerpResult(items=[], provider="x")})
    assert len(serp.calls) == explorer.MAX_CLUSTER - 1 and "k0" not in serp.calls


def test_dry_run_data_labels_the_result():
    from app.providers.dry_run_keywords import DryRunKeywordProvider
    result = explorer.explore("espresso machine", data=DryRunKeywordProvider())
    assert result.dry_run is True
