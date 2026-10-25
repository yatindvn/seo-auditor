"""Core Web Vitals rating: Google's thresholds, field data before lab, and
the issues a measurement raises."""

import pytest

from app.vitals.model import VitalsResult, metric_ratings, rate, rate_metric, vitals_issues


@pytest.mark.parametrize("metric, value, expected", [
    ("lcp_ms", 2500, "good"), ("lcp_ms", 2501, "needs_improvement"),
    ("lcp_ms", 4000, "needs_improvement"), ("lcp_ms", 4001, "poor"),
    ("inp_ms", 200, "good"), ("inp_ms", 500, "needs_improvement"), ("inp_ms", 501, "poor"),
    ("cls", 0.1, "good"), ("cls", 0.25, "needs_improvement"), ("cls", 0.26, "poor"),
    ("tbt_ms", 200, "good"), ("tbt_ms", 600, "needs_improvement"), ("tbt_ms", 601, "poor"),
    ("lcp_ms", None, None),
])
def test_rate_metric_boundaries(metric, value, expected):
    assert rate_metric(metric, value) == expected


def test_field_data_rates_on_inp_and_ignores_tbt():
    r = VitalsResult(url="u", source="psi", data_kind="field", lcp_ms=2000, inp_ms=150, cls=0.05, tbt_ms=900)
    assert rate(r) == "good"


def test_lab_data_rates_on_tbt_in_place_of_inp():
    r = VitalsResult(url="u", source="lighthouse", data_kind="lab", lcp_ms=2000, cls=0.05, tbt_ms=900)
    assert rate(r) == "poor"


def test_the_page_rating_is_its_worst_metric_and_missing_ones_are_ignored():
    r = VitalsResult(url="u", source="psi", data_kind="lab", lcp_ms=3000, cls=None, tbt_ms=100)
    assert rate(r) == "needs_improvement"
    assert rate(VitalsResult(url="u", source="psi", data_kind="lab")) is None


def test_issues_name_value_threshold_and_data_kind():
    r = VitalsResult(url="u", source="lighthouse", data_kind="lab", lcp_ms=4800, cls=0.12, tbt_ms=100)
    issues = {i["code"]: i for i in vitals_issues(r)}
    assert set(issues) == {"CWV_LCP_POOR", "CWV_CLS_NEEDS_IMPROVEMENT"}
    assert issues["CWV_LCP_POOR"]["severity"] == "warning"
    assert issues["CWV_LCP_POOR"]["message"] == "LCP 4.8 s (lab) — poor, over 4.0 s"
    assert issues["CWV_CLS_NEEDS_IMPROVEMENT"]["severity"] == "info"
    assert issues["CWV_CLS_NEEDS_IMPROVEMENT"]["message"] == "CLS 0.12 (lab) — needs improvement, over 0.10"


def test_lab_tbt_gets_its_own_code():
    r = VitalsResult(url="u", source="psi", data_kind="lab", tbt_ms=700)
    assert [i["code"] for i in vitals_issues(r)] == ["CWV_TBT_POOR"]


def test_a_failed_measurement_raises_no_issues():
    r = VitalsResult(url="u", source="not_measured", error="timeout", lcp_ms=9000)
    assert vitals_issues(r) == []


def test_to_dict_carries_per_metric_ratings():
    d = VitalsResult(url="u", source="psi", data_kind="field", lcp_ms=5000, cls=0.01).to_dict()
    assert d["url"] == "u" and d["lcp_ms"] == 5000
    assert d["metric_ratings"] == {"lcp_ms": "poor", "inp_ms": None, "cls": "good", "tbt_ms": None}
    assert metric_ratings(VitalsResult(url="u")) == {"lcp_ms": None, "inp_ms": None, "cls": None, "tbt_ms": None}
