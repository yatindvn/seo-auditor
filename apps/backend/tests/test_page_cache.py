"""The page cache: HTML analyses kept per site, usable only while still valid."""

import time

import pytest

from app.crawler.crawler import Validators
from app.models import page_cache
from app.models.page_cache import PageCache, analyzer_fingerprint, cache_file_name
from app.services.page_pipeline import HtmlAnalysis

START = "https://example.com/"
URL = "https://example.com/a"


def _part(n=1):
    return HtmlAnalysis(
        issues=[{"severity": "info", "code": f"C{n}", "message": "m"}],
        meta={"title": f"T{n}"}, weight={"html_size_bytes": 10},
        meta_robots_content="", dupe_row={"url": URL, "text": "words " * 50},
        keyword_data=[], internal_links=["https://example.com/b"],
        external_links=["https://other.com/"], signature=b"\x01\x02",
    )


def _validators():
    return Validators(etag='"v1"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT",
                      body_hash="abc", headers={"Content-Security-Policy": "default-src 'self'"})


def test_a_stored_entry_round_trips(tmp_path):
    cache = PageCache.open(tmp_path, START, "fp")
    cache.put(URL, _validators(), _part())

    assert cache.validators()[URL] == _validators()
    part = cache.get_html_part(URL)
    assert part == _part()
    assert part.signature == b"\x01\x02"


def test_entries_survive_reopening(tmp_path):
    PageCache.open(tmp_path, START, "fp").put(URL, _validators(), _part())

    assert URL in PageCache.open(tmp_path, START, "fp").validators()


def test_an_entry_from_another_fingerprint_is_not_usable(tmp_path):
    PageCache.open(tmp_path, START, "old").put(URL, _validators(), _part())

    cache = PageCache.open(tmp_path, START, "new")
    assert cache.validators() == {}
    assert cache.get_html_part(URL) is None


@pytest.mark.parametrize("age_days, usable", [(29, True), (31, False)])
def test_entries_expire_after_max_age(tmp_path, age_days, usable):
    then = 1_000_000_000.0
    PageCache.open(tmp_path, START, "fp", clock=lambda: then).put(URL, _validators(), _part())

    later = PageCache.open(tmp_path, START, "fp", max_age_days=30,
                           clock=lambda: then + age_days * 86400)
    assert (URL in later.validators()) is usable
    assert (later.get_html_part(URL) is not None) is usable


def test_a_corrupt_cache_file_is_ignored_not_fatal(tmp_path):
    (tmp_path / cache_file_name(START)).write_bytes(b"this is not a database" * 100)

    assert PageCache.open(tmp_path, START, "fp") is None


def test_each_site_has_its_own_file():
    assert cache_file_name("https://Example.com/x") == "example.com.db"
    assert cache_file_name("http://localhost:8080/") == "localhost_8080.db"


def test_fingerprint_is_stable_and_follows_the_options():
    base = analyzer_fingerprint(True, ["b", "a"], False)
    assert base == analyzer_fingerprint(True, ["a", "b"], False)
    assert base != analyzer_fingerprint(False, ["a", "b"], False)
    assert base != analyzer_fingerprint(True, ["a"], False)
    assert base != analyzer_fingerprint(True, ["a", "b"], True)


def test_fingerprint_changes_when_a_check_changes(monkeypatch):
    before = analyzer_fingerprint(True, None, False)
    original = page_cache._read_source

    def edited(rel):
        data = original(rel)
        return data + b"\n# edited" if rel == "auditor/checks.py" else data

    monkeypatch.setattr(page_cache, "_read_source", edited)
    assert analyzer_fingerprint(True, None, False) != before


def test_the_cache_lives_beside_the_session_history(isolated_session_dir):
    assert isolated_session_dir.page_cache_dir.name == "page_cache"
    assert isolated_session_dir.page_cache_dir.parent == isolated_session_dir._dir
