"""The vendored axe-core: present, the version we say, licensed."""

from app.accessibility import axe


def test_the_vendored_file_is_the_version_we_record():
    assert axe.AXE_VERSION == "4.14.0"
    assert f'axe.version="{axe.AXE_VERSION}"' in axe.axe_source()


def test_the_licences_ship_with_it():
    assert "Mozilla Public License" in (axe.VENDOR / "LICENSE").read_text(encoding="utf-8")
    assert (axe.VENDOR / "LICENSE-3RD-PARTY.txt").exists()


def test_source_is_read_once():
    assert axe.axe_source() is axe.axe_source()


def test_wcag_22_a_and_aa_tags():
    assert axe.AXE_TAGS == ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
    assert "axe.run(document" in axe.AXE_RUN and "violations" in axe.AXE_RUN


def test_available_reports_a_missing_file(monkeypatch, tmp_path):
    assert axe.axe_available() == (True, "")
    monkeypatch.setattr(axe, "VENDOR", tmp_path)
    ok, reason = axe.axe_available()
    assert ok is False and reason == "axe-core not found (app/accessibility/vendor/axe.min.js)"
