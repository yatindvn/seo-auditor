"""The CLI is a thin entry point over app/, not a second copy of the engine.

It used to duplicate the crawler, the checks, the analysis and the whole
per-page audit loop. Commit 8f18529 ("mirror keyword-suggestions/logging/
event-leak fixes in CLI tree") exists solely because that copy drifted, and
test_cli_tree_parity.py existed to police it. Deleting the duplicate removes the
drift at its source, so both are gone.
"""

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_cli_module_is_importable_and_reuses_the_app_engine():
    from app import cli

    assert callable(cli.main)
    # The CLI must run the same pipeline the API runs, not re-implement it.
    assert cli.audit_service is not None
    assert cli.Crawler is not None


def test_cli_has_no_config_loader_of_its_own():
    """Migrated intent from test_cli_tree_parity.py's two dotenv tests.

    Those tests existed because the CLI carried its own `_keyword_intel_config()`
    that had to load apps/backend/.env itself, and would silently report "not
    configured" if it stopped. There is nothing to keep in step now: the CLI
    reads app.config, whose dotenv loading is covered by test_config_env.py.
    """
    from app import cli
    from app.config import config as app_config

    assert not hasattr(cli, "_keyword_intel_config"), (
        "the CLI is back to building its own config; it must use app.config"
    )
    assert app_config.GOOGLE_CSE_DAILY_QUOTA == 100


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "--max-pages" in result.stdout


def test_the_duplicate_engine_directory_is_gone():
    assert not (BACKEND_ROOT / "seo_auditor").exists(), (
        "the duplicate engine is back; app/ is the single source"
    )


def test_psi_flags_reach_the_audit_pipeline():
    """--psi-key still selects PSI; --psi-max-pages bounds how many pages are
    measured (the CLI used to measure every page)."""
    from unittest.mock import patch

    from app import cli

    args = cli.build_parser().parse_args(
        ["https://example.com/", "--psi-key", "k", "--psi-max-pages", "7"])
    with patch.object(cli.audit_service, "_build_audit_result", return_value={}) as build:
        cli._run_audit(args)
    kwargs = build.call_args.kwargs
    assert kwargs["psi_key"] == "k" and kwargs["vitals_max_pages"] == 7


def test_render_js_flag_reaches_the_audit_pipeline():
    from unittest.mock import patch

    from app import cli

    args = cli.build_parser().parse_args(["https://example.com/", "--render-js"])
    with patch.object(cli.audit_service, "_build_audit_result", return_value={}) as build:
        cli._run_audit(args)
    assert build.call_args.kwargs["render_js"] is True
    args = cli.build_parser().parse_args(["https://example.com/"])
    with patch.object(cli.audit_service, "_build_audit_result", return_value={}) as build:
        cli._run_audit(args)
    assert build.call_args.kwargs["render_js"] is False


def test_a11y_flag_reaches_the_audit_pipeline():
    from unittest.mock import patch

    from app import cli

    for argv, expected in ((["https://example.com/", "--a11y"], True), (["https://example.com/"], False)):
        args = cli.build_parser().parse_args(argv)
        with patch.object(cli.audit_service, "_build_audit_result", return_value={}) as build:
            cli._run_audit(args)
        assert build.call_args.kwargs["accessibility"] is expected


def test_no_gsc_flag():
    from unittest.mock import patch

    from app import cli

    for argv, expected in ((["https://example.com/", "--no-gsc"], False), (["https://example.com/"], True)):
        with patch.object(cli.audit_service, "_build_audit_result", return_value={}) as build:
            cli._run_audit(cli.build_parser().parse_args(argv))
        assert build.call_args.kwargs["enable_gsc"] is expected
