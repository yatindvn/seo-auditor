"""The `app/seo/` and `seo_auditor/seo_auditor/seo/` trees are maintained as
behavioural twins — commit 8f18529 ("mirror keyword-suggestions/logging/event-leak
fixes in CLI tree") exists solely to keep them in step.

They are deliberately NOT byte-identical: the CLI tree uses relative imports
(`from . import keyword_extraction`) where app/ uses absolute ones
(`from app.seo import keyword_extraction`). So parity is asserted on *behaviour*,
which is what actually matters, and which a `diff` would drown in import noise.

Each test below encodes a bug that was fixed in app/ and would be a live bug in
the CLI if the mirror lapsed.
"""

import builtins
import inspect
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.seo import keyword_suggestions as app_suggestions
from app.seo import rank_checker as app_rank_checker
from seo_auditor.seo import keyword_suggestions as cli_suggestions
from seo_auditor.seo import rank_checker as cli_rank_checker

FAKE_CONFIG = SimpleNamespace(
    GOOGLE_CSE_API_KEY="test-key",
    GOOGLE_CSE_CX="test-cx",
    GOOGLE_CSE_DAILY_QUOTA=100,
    GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3,
    GOOGLE_CSE_CACHE_TTL_HOURS=24,
)

BOTH_RANK_CHECKERS = [
    pytest.param(app_rank_checker, id="app"),
    pytest.param(cli_rank_checker, id="cli"),
]
BOTH_SUGGESTIONS = [
    pytest.param(app_suggestions, id="app"),
    pytest.param(cli_suggestions, id="cli"),
]


@pytest.fixture(autouse=True)
def _reset_rank_state():
    app_rank_checker._state.reset()
    cli_rank_checker._state.reset()
    yield
    app_rank_checker._state.reset()
    cli_rank_checker._state.reset()


def _canned_response(items):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"items": items}
    return resp


@pytest.mark.parametrize("module", BOTH_RANK_CHECKERS)
def test_cse_failure_never_logs_the_api_key(module, caplog):
    """requests.raise_for_status() embeds the full request URL — including
    `key=<API key>` — in its exception message. Logging the exception (or
    exc_info) leaks the credential."""
    leaky = Exception(
        "401 Client Error: Unauthorized for url: "
        "https://www.googleapis.com/customsearch/v1?key=AIzaFAKESECRETKEY&cx=cx123&q=espresso"
    )

    with patch.object(module.requests, "get", side_effect=leaky):
        with caplog.at_level(logging.ERROR):
            result = module.check_rankings("https://example.com/page", ["espresso"], FAKE_CONFIG)

    assert "AIzaFAKESECRETKEY" not in caplog.text
    assert result[0]["position"] is None


@pytest.mark.parametrize("module", BOTH_RANK_CHECKERS)
def test_check_rankings_accepts_max_keywords_override(module):
    """The per-page config cap guards automatic extraction; an explicit caller
    must be able to override it so hand-picked keywords aren't silently dropped."""
    assert "max_keywords" in inspect.signature(module.check_rankings).parameters

    items = [{"link": "https://other.com/"}]
    keywords = ["one", "two", "three", "four", "five"]

    with patch.object(module.requests, "get", return_value=_canned_response(items)) as mock_get:
        result = module.check_rankings(
            "https://example.com/page", keywords, FAKE_CONFIG, max_keywords=5
        )

    assert len(result) == 5
    assert mock_get.call_count == 5


@pytest.mark.parametrize("module", BOTH_RANK_CHECKERS)
def test_results_carry_an_explicit_status(module):
    """`position is None` is ambiguous — it means both "genuinely absent from the
    top 10" and "the check never ran". Only `status` distinguishes them."""
    # Distinct keywords per phase: the module caches on (keyword, domain), so
    # reusing one keyword would serve phase 1's cached URLs to phase 2 and the
    # "not_ranked" assertion would see "ranked".
    with patch.object(module.requests, "get", return_value=_canned_response([{"link": "https://example.com/page"}])):
        ranked = module.check_rankings("https://example.com/page", ["kw ranked"], FAKE_CONFIG)
    assert ranked[0]["status"] == "ranked"
    assert ranked[0]["position"] == 1

    with patch.object(module.requests, "get", return_value=_canned_response([{"link": f"https://c{i}.com/"} for i in range(10)])):
        not_ranked = module.check_rankings("https://example.com/page", ["kw absent"], FAKE_CONFIG)
    assert not_ranked[0]["status"] == "not_ranked"
    assert not_ranked[0]["position"] is None

    unconfigured = SimpleNamespace(
        GOOGLE_CSE_API_KEY="", GOOGLE_CSE_CX="",
        GOOGLE_CSE_DAILY_QUOTA=100, GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3,
        GOOGLE_CSE_CACHE_TTL_HOURS=24,
    )
    skipped = module.check_rankings("https://example.com/page", ["kw unchecked"], unconfigured)
    assert skipped[0]["status"] == "skipped"
    assert skipped[0]["position"] is None


def test_cli_config_loads_the_same_dotenv_file_as_the_app():
    """The CLI has no config module of its own, so it must load apps/backend/.env
    itself. Without this it silently ignored credentials pasted into that file and
    reported "not configured" forever — the trap the app tree had before
    python-dotenv was added there.

    Asserted on the resolved path and on override=False, not on a config value:
    every value in that file happens to equal its own code default, so reading a
    matching value back would prove nothing.
    """
    from seo_auditor import cli as cli_module

    expected = (Path(cli_module.__file__).resolve().parents[2] / ".env")
    assert expected.name == ".env"
    assert expected.parent.name == "backend", f"resolved to {expected}, not apps/backend/.env"

    with patch("dotenv.load_dotenv") as mock_load:
        cli_module._keyword_intel_config()

    mock_load.assert_called_once()
    called_path, kwargs = mock_load.call_args[0][0], mock_load.call_args[1]
    assert Path(called_path) == expected
    assert kwargs.get("override") is False, "a real exported env var must beat the file"


def test_cli_survives_python_dotenv_being_absent():
    """python-dotenv is declared in this package's requirements, but an older
    installed copy may predate that. A missing optional dependency must degrade to
    "no .env loaded", never take down the CLI."""
    from seo_auditor import cli as cli_module

    real_import = builtins.__import__

    def no_dotenv(name, *args, **kwargs):
        if name == "dotenv":
            raise ImportError("No module named 'dotenv'")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", side_effect=no_dotenv):
        config = cli_module._keyword_intel_config()

    assert config.GOOGLE_CSE_DAILY_QUOTA == 100


def _rank(keyword, status):
    return {"keyword": keyword, "position": None, "status": status,
            "note": None, "checked_at": "", "top_urls": []}


@pytest.mark.parametrize("module", BOTH_SUGGESTIONS)
def test_skipped_status_produces_no_suggestions(module):
    """The invariant the whole feature turns on: "skipped" means nothing was
    measured, so seeding replacements from it fabricates advice from missing
    data — worst before credentials exist, when every keyword looks like a
    failure."""
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]

    with patch.object(module, "_autocomplete_suggestions", return_value=["anything"]) as mock_ac:
        out = module.suggest_keywords(
            seeds, [_rank("espresso machine", "skipped")], FAKE_CONFIG,
            fetch_page=lambda u: None, page_url="https://example.com/",
        )

    assert out == []
    mock_ac.assert_not_called()


@pytest.mark.parametrize("module", BOTH_SUGGESTIONS)
def test_not_ranked_seeds_suggestions_and_names_what_it_replaces(module):
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]

    with patch.object(module, "_autocomplete_suggestions", return_value=["espresso machine reviews"]):
        out = module.suggest_keywords(
            seeds, [_rank("espresso machine", "not_ranked")], FAKE_CONFIG,
            fetch_page=lambda u: None, page_url="https://example.com/",
        )

    assert [s["phrase"] for s in out] == ["espresso machine reviews"]
    assert out[0]["replaces"] == "espresso machine"


@pytest.mark.parametrize("module", BOTH_SUGGESTIONS)
def test_no_rank_data_falls_back_to_seed_keywords(module):
    """Backward compatibility: with rank checking off, suggestions still work and
    claim no replacement."""
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]

    with patch.object(module, "_autocomplete_suggestions", return_value=["espresso grinder"]):
        out = module.suggest_keywords(
            seeds, [], FAKE_CONFIG, fetch_page=lambda u: None, page_url="https://example.com/",
        )

    assert [s["phrase"] for s in out] == ["espresso grinder"]
    assert out[0]["replaces"] is None


@pytest.mark.parametrize("module", BOTH_SUGGESTIONS)
def test_competitor_gap_not_seeded_from_an_unmeasured_keyword(module):
    """A transient "error" skip can retry successfully inside _competitor_gap, so
    the gap path needs the same gate as the autocomplete path."""
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]

    with patch.object(module, "_autocomplete_suggestions", return_value=[]), \
         patch.object(module, "_competitor_gap", return_value=[{"phrase": "x", "reason": "r", "competitor_examples": ["u"]}]) as mock_gap:
        out = module.suggest_keywords(
            seeds, [_rank("espresso machine", "skipped")], FAKE_CONFIG,
            fetch_page=lambda u: None, page_url="https://example.com/",
            enable_competitor_gap=True,
        )

    mock_gap.assert_not_called()
    assert out == []
