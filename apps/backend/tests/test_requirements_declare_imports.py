"""Every third-party module `app/` imports must be declared in the requirements
file production actually installs.

The bug this file exists for: `app/analysis/analysis.py` imports networkx behind
a `try: import` guard to compute PageRank, and networkx was declared only in
`seo_auditor/requirements.txt` — the CLI package's file. The Dockerfile installs
`apps/backend/requirements.txt` (`apps/backend/Dockerfile:18`), so networkx was
never present in production, the guard swallowed the ImportError, and every audit
shipped `pagerank_available: false` with an empty `top_pages_by_importance`. A
guarded import degrades silently by design, which is exactly why the declaration
needs a test rather than trust.

The scan is deliberately general rather than naming networkx: the next
undeclared dependency should fail here too. A lazily-imported dependency is
still a real one — `openpyxl` and `reportlab` are imported inside functions in
the report writers and are declared for that reason.
"""

import ast
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_ROOT / "app"
REQUIREMENTS = BACKEND_ROOT / "requirements.txt"

# Import name -> distribution name, for the cases where they differ. A module
# whose import name matches its distribution name needs no entry.
DISTRIBUTION_NAMES = {
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
}

# Packages that live in this repository, not on PyPI.
FIRST_PARTY = {"app", "seo_auditor", "tests"}


def _imported_top_level_modules(directory: Path) -> set[str]:
    """Top-level module names imported anywhere under `directory`.

    Walks the AST rather than importing anything: importing `app.main` would
    start building a FastAPI app, and an undeclared dependency is precisely the
    thing that would make the import fail.
    """
    modules: set[str] = set()
    for source_file in sorted(directory.rglob("*.py")):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".")[0])
            # level > 0 is a relative import, which is first-party by definition.
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return modules


def _declared_distributions(requirements: Path) -> set[str]:
    declared = set()
    for raw_line in requirements.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        # Strip version specifiers and extras: "uvicorn[standard]>=0.30.0" -> "uvicorn".
        name = line.split("[", 1)[0]
        for separator in (">=", "<=", "==", "!=", "~=", ">", "<"):
            name = name.split(separator, 1)[0]
        declared.add(name.strip().lower())
    return declared


def test_every_third_party_import_in_app_is_declared():
    imported = _imported_top_level_modules(APP_DIR)
    third_party = {
        module
        for module in imported
        if module not in sys.stdlib_module_names and module not in FIRST_PARTY
    }
    declared = _declared_distributions(REQUIREMENTS)

    undeclared = sorted(
        module
        for module in third_party
        if DISTRIBUTION_NAMES.get(module, module).lower() not in declared
    )

    assert not undeclared, (
        f"app/ imports {undeclared} but requirements.txt does not declare them. "
        "The Dockerfile installs only this file, so these are missing in production."
    )


def test_the_scan_actually_finds_third_party_imports():
    """Guards the guard: if the AST walk or the stdlib filter broke, the test
    above would pass by finding nothing at all rather than by finding everything
    declared."""
    imported = _imported_top_level_modules(APP_DIR)
    third_party = {
        module
        for module in imported
        if module not in sys.stdlib_module_names and module not in FIRST_PARTY
    }

    assert "fastapi" in third_party
    assert "networkx" in third_party, (
        "networkx is imported by app/analysis/analysis.py behind a try/except "
        "guard; if this scan stops seeing it, the declaration test is toothless"
    )
