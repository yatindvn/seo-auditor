"""`GET /api/export/{fmt}` and the five report writers behind it.

History, because it explains the shape of these tests: the writers used to live
in a separate CLI package that resolved under two different names depending on
how it was on the path, reached through a `ModuleNotFoundError` fallback. Every
export request failed unless someone had separately run
`pip install -e apps/backend/seo_auditor`, an undeclared step documented
nowhere. `app/utils/report.py` owns them now and the fallback is gone.

These tests exercise the endpoint through the real app rather than importing the
writers directly, so they fail if the import path regresses — testing the import
in isolation would not catch a route that never reaches it.
"""

import csv
import io
import json
import sys

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app

SESSION_ID = "sess_export_test"

AUDIT_RESULT = {
    "executive_summary": {
        "audit_date": "2026-08-17T00:00:00Z",
        "start_url": "https://example.com/",
        "pages_crawled": 1,
        "health_score": {
            "score": 82.5,
            "grade": "B",
            "critical_issues": 1,
            "warning_issues": 2,
            "info_issues": 3,
        },
        "orphan_pages": 0,
        "broken_links": 0,
    },
    "pages": [
        {"url": "https://example.com/", "title": "Example", "seo_score": 82.5, "status_code": 200},
    ],
    "recommendations": [
        {"code": "NO_HTTPS", "severity": "critical", "affected_pages": 1, "example_urls": ["https://example.com/"]},
    ],
    "broken_links": [],
    "site_wide_analysis": {},
}


@pytest.fixture
def client():
    routes.active_sessions[SESSION_ID] = AUDIT_RESULT
    yield TestClient(app)
    routes.active_sessions.pop(SESSION_ID, None)


def test_export_json_returns_the_audit_result(client):
    resp = client.get(f"/api/export/json?session_id={SESSION_ID}")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "audit_report.json" in resp.headers["content-disposition"]
    parsed = json.loads(resp.content)
    assert parsed["executive_summary"]["health_score"]["grade"] == "B"


def test_export_csv_returns_page_rows(client):
    resp = client.get(f"/api/export/csv?session_id={SESSION_ID}")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8"))))
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com/"


def test_export_html_returns_a_document(client):
    resp = client.get(f"/api/export/html?session_id={SESSION_ID}")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert b"<html" in resp.content.lower()


def test_export_xlsx_returns_a_workbook(client):
    """openpyxl is imported lazily inside export_excel, so this also pins it as a
    real runtime dependency of this endpoint."""
    resp = client.get(f"/api/export/xlsx?session_id={SESSION_ID}")

    assert resp.status_code == 200
    # XLSX is a zip container: every one starts with the PK local-file header.
    assert resp.content[:2] == b"PK"


def test_export_pdf_returns_a_pdf(client):
    """reportlab is imported lazily inside export_pdf_summary — same reasoning."""
    resp = client.get(f"/api/export/pdf?session_id={SESSION_ID}")

    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"


def test_unknown_format_is_rejected(client):
    resp = client.get(f"/api/export/docx?session_id={SESSION_ID}")

    assert resp.status_code == 400


def test_unknown_session_is_a_404(client):
    resp = client.get("/api/export/json?session_id=sess_does_not_exist")

    assert resp.status_code == 404


# --- The test that actually guards the import path -------------------------
#
# The two-name fallback this file was written for is gone: app/ owns the export
# writers now, so there is only one name to resolve. The probe stays because the
# failure it catches is about *layout*, not about that fallback -- it runs the
# endpoint from apps/backend with no extra sys.path entries, exactly as
# `uvicorn app.main:app` does (scripts/dev.js), and so would still catch an
# export import that only resolves under pytest's path setup.

_SUBPROCESS_PROBE = """
import sys
# Drop anything that puts the CLI package root on the path, leaving apps/backend
# only -- exactly what `uvicorn app.main:app` sees when run from apps/backend.
sys.path = [p for p in sys.path if "seo_auditor" not in p.replace("\\\\", "/")]

from fastapi.testclient import TestClient
from app.api import routes
from app.main import app

routes.active_sessions["probe"] = {
    "executive_summary": {"health_score": {"score": 1, "grade": "A"}},
    "pages": [{"url": "https://example.com/"}],
    "recommendations": [],
    "broken_links": [],
}
resp = TestClient(app).get("/api/export/json?session_id=probe")
print("STATUS", resp.status_code)
"""


def test_export_import_resolves_without_the_cli_root_on_syspath():
    """Reproduces how the server actually runs. Before the fix this raised
    ModuleNotFoundError: No module named 'seo_auditor.report'."""
    import subprocess
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]

    proc = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_PROBE],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert "STATUS 200" in proc.stdout, (
        "export failed with the CLI root off sys.path — the layout the server "
        f"actually runs in.\nstdout: {proc.stdout}\nstderr: {proc.stderr[-2000:]}"
    )


# --- The writers now live in app/, not in the CLI package -------------------


def test_export_writers_are_importable_from_the_app_package():
    """The export writers lived in the CLI package, reached through a
    ModuleNotFoundError fallback because that package resolves under two names
    depending on how it is on the path. Owning them in app/ deletes the hack."""
    from app.utils.report import (
        export_csv, export_excel, export_html_report, export_json, export_pdf_summary,
    )

    assert callable(export_json)
    assert callable(export_csv)
    assert callable(export_excel)
    assert callable(export_pdf_summary)
    assert callable(export_html_report)


def test_export_csv_returns_bytes_when_no_path_given():
    """Pins the writers' contract as the endpoint uses it: path=None means
    "hand the bytes back" rather than "write to disk"."""
    from app.utils.report import export_csv

    data = export_csv(None, [{"url": "https://example.com/", "status_code": 200}])

    assert isinstance(data, bytes)
    assert b"https://example.com/" in data
