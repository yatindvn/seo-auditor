import logging

from app.api.routes import log_crawl_failure


def test_log_crawl_failure_emits_structured_log_record(caplog):
    with caplog.at_level(logging.ERROR):
        log_crawl_failure("sess_123", ValueError("boom"))

    assert any("sess_123" in record.message for record in caplog.records)


def test_log_crawl_failure_does_not_write_error_log_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    log_crawl_failure("sess_123", ValueError("boom"))

    assert not (tmp_path / "error_log.txt").exists()
