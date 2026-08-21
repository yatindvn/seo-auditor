"""CORS must be configurable for deployment.

`allow_origins=["*"]` together with `allow_credentials=True` is not a valid
combination: the CORS spec forbids the wildcard on a credentialed request, and
browsers reject the response. Starlette resolves it by emitting
`Access-Control-Allow-Origin: *` and simply never sending
`Access-Control-Allow-Credentials`, so the wildcard silently wins and the
credentials flag is a lie. Fine while the frontend is same-origin localhost;
wrong once it is served from another domain.
"""

import importlib

import pytest


def _origins(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("ALLOWED_ORIGINS", value)
    from app.config import config as config_module
    return importlib.reload(config_module).ALLOWED_ORIGINS


def test_unset_means_no_configured_origins(monkeypatch):
    assert _origins(monkeypatch, None) == []


def test_single_origin_is_parsed(monkeypatch):
    assert _origins(monkeypatch, "https://app.example.com") == ["https://app.example.com"]


def test_comma_separated_origins_are_split_and_trimmed(monkeypatch):
    got = _origins(monkeypatch, " https://a.example.com , https://b.example.com ")
    assert got == ["https://a.example.com", "https://b.example.com"]


def test_blank_entries_are_discarded(monkeypatch):
    assert _origins(monkeypatch, "https://a.example.com,,  ,") == ["https://a.example.com"]


@pytest.fixture(autouse=True)
def _restore_config():
    yield
    from app.config import config as config_module
    importlib.reload(config_module)


def test_credentials_are_only_allowed_with_explicit_origins(monkeypatch):
    """The heart of it: credentials may never ride along with a wildcard."""
    from app import main as main_module

    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example.com")
    importlib.reload(importlib.import_module("app.config.config"))
    reloaded = importlib.reload(main_module)
    opts = reloaded._cors_options()
    assert opts["allow_origins"] == ["https://app.example.com"]
    assert opts["allow_credentials"] is True

    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    importlib.reload(importlib.import_module("app.config.config"))
    reloaded = importlib.reload(main_module)
    opts = reloaded._cors_options()
    assert opts["allow_origins"] == ["*"]
    assert opts["allow_credentials"] is False, "wildcard + credentials is invalid"
