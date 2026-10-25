"""Alert rules, notifiers, de-duplication."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.alerts import delivery, notifiers, rules
from app.alerts.digest import format_digest
from app.db.engine import get_session_factory
from app.db.models import Alert, Keyword, Project, RankCheck, utcnow

KW = SimpleNamespace(id=1, phrase="espresso", country="US", device="desktop")


def _check(position, status=None, check_id=2):
    return SimpleNamespace(id=check_id, position=position, ranking_url="https://example.com/e",
                           status=status or ("ranked" if position else "not_ranked"))


@pytest.mark.parametrize("old, new, settings, kinds", [
    (4, 9, None, {"drop"}),
    (4, 6, None, set()),
    (4, 6, {"drop_threshold": 2}, {"drop"}),
    (8, 12, None, {"drop", "left_top10"}),
    (8, 12, {"top10_alerts": False}, {"drop"}),
    (5, None, None, {"lost", "left_top10"}),
    (9, 3, None, set()),
    (9, 3, {"gain_threshold": 5}, {"gain"}),
    (None, 3, None, set()),
])
def test_rules(old, new, settings, kinds):
    changes = rules.evaluate(_check(old, check_id=1), _check(new), KW, settings)
    assert {c.kind for c in changes} == kinds


def test_no_previous_or_skipped_current_means_no_alert():
    assert rules.evaluate(None, _check(9), KW, None) == []
    assert rules.evaluate(_check(4, check_id=1), _check(None, status="skipped"), KW, None) == []


def test_digest_lists_each_change():
    change = rules.evaluate(_check(4, check_id=1), _check(9), KW, None)[0]
    subject, text = format_digest("example.com", [change])
    assert "example.com" in subject
    assert "espresso" in text and "4 → 9" in text and "US/desktop" in text


def test_slack_posts_the_text(monkeypatch):
    post = MagicMock()
    monkeypatch.setattr(notifiers.requests, "post", post)
    notifiers.SlackNotifier("https://hooks.slack.test/x").send("Subj", "body")
    assert post.call_args.args[0] == "https://hooks.slack.test/x"
    assert "Subj" in post.call_args.kwargs["json"]["text"] and "body" in post.call_args.kwargs["json"]["text"]


def test_email_uses_starttls_and_login(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["host"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = user

        def send_message(self, msg):
            sent["to"], sent["subject"] = msg["To"], msg["Subject"]

    monkeypatch.setattr(notifiers.smtplib, "SMTP", FakeSMTP)
    notifiers.EmailNotifier("smtp.test", 587, "u", "p", "from@x.test", ["a@x.test", "b@x.test"]).send("S", "T")
    assert sent == {"host": ("smtp.test", 587), "tls": True, "login": "u",
                    "to": "a@x.test, b@x.test", "subject": "S"}


def test_configured_notifiers_only_includes_set_channels():
    none = SimpleNamespace(SLACK_WEBHOOK_URL="", SMTP_HOST="", SMTP_PORT=587, SMTP_USER="",
                           SMTP_PASSWORD="", ALERT_EMAIL_FROM="", ALERT_EMAIL_TO=[])
    both = SimpleNamespace(**{**none.__dict__, "SLACK_WEBHOOK_URL": "https://h", "SMTP_HOST": "s",
                              "ALERT_EMAIL_FROM": "f@x", "ALERT_EMAIL_TO": ["t@x"]})
    assert notifiers.configured_notifiers(none) == []
    assert {n.channel for n in notifiers.configured_notifiers(both)} == {"slack", "email"}


class Recorder:
    def __init__(self, channel, fail=False):
        self.channel, self.fail, self.sent = channel, fail, []

    def send(self, subject, text):
        if self.fail:
            raise RuntimeError("smtp down")
        self.sent.append((subject, text))


def _stored_change():
    factory = get_session_factory()
    with factory.begin() as s:
        p = Project(name="example.com", domain="example.com", audit_options_json={})
        s.add(p)
        s.flush()
        k = Keyword(project_id=p.id, phrase="espresso", country="US", device="desktop")
        s.add(k)
        s.flush()
        old = RankCheck(keyword_id=k.id, checked_at=utcnow(), provider="t", status="ranked", position=4)
        new = RankCheck(keyword_id=k.id, checked_at=utcnow(), provider="t", status="ranked", position=9)
        s.add_all([old, new])
        s.flush()
        change = rules.evaluate(old, new, k, None)[0]
        return factory, p.id, change


def test_the_same_change_is_sent_once_per_channel():
    factory, project_id, change = _stored_change()
    slack, email = Recorder("slack"), Recorder("email")

    delivery.deliver(factory, project_id, "example.com", [change], [slack, email], utcnow())
    delivery.deliver(factory, project_id, "example.com", [change], [slack, email], utcnow())

    assert len(slack.sent) == 1 and len(email.sent) == 1
    with factory() as s:
        assert s.query(Alert).count() == 2


def test_a_failing_channel_is_recorded_and_does_not_stop_the_others():
    factory, project_id, change = _stored_change()
    broken, slack = Recorder("email", fail=True), Recorder("slack")

    sent = delivery.deliver(factory, project_id, "example.com", [change], [broken, slack], utcnow())

    assert sent == {"email": 0, "slack": 1}
    with factory() as s:
        failed = s.query(Alert).filter_by(channel="email").one()
        assert "smtp down" in failed.payload_json["error"]
