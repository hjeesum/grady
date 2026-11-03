import smtplib

import pytest
import requests

from grady import emailer


class FakeSMTP:
    """Stands in for smtplib.SMTP: records what happens instead of sending anything."""
    instances = []

    def __init__(self, host, port, timeout):
        self.host, self.port = host, port
        self.calls = []
        self.sent = None
        FakeSMTP.instances.append(self)

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append("login")

    def send_message(self, message):
        self.calls.append("send")
        self.sent = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_smtp(monkeypatch):
    # monkeypatch undoes these changes after the test.
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    for name, value in {
        "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
        "SMTP_USER": "me@example.com", "SMTP_PASSWORD": "secret",
        "EMAIL_TO": "me@example.com",
        # Set, so real ones in .env aren't loaded.
        "SUBSCRIBERS": "", "SIGNUP_LIST_URL": "",
    }.items():
        monkeypatch.setenv(name, value)
    return FakeSMTP


def test_sends_html_with_plain_text_alternative(fake_smtp):
    emailer.send_email("Subject line", "<p>Hello</p>", "Hello")
    server = fake_smtp.instances[0]
    message = server.sent
    assert message["Subject"] == "Subject line"
    assert message["To"] == "me@example.com"
    assert message.get_body(("plain",)).get_content().strip() == "Hello"
    assert "<p>Hello</p>" in message.get_body(("html",)).get_content()


def test_encrypts_before_sending_the_password(fake_smtp):
    emailer.send_email("s", "<p>h</p>", "t")
    assert fake_smtp.instances[0].calls == ["starttls", "login", "send"]


def test_wrong_password_gives_a_helpful_error(fake_smtp, monkeypatch):
    def reject(self, user, password):
        raise smtplib.SMTPAuthenticationError(535, b"Bad credentials")
    monkeypatch.setattr(FakeSMTP, "login", reject)
    with pytest.raises(RuntimeError, match="App Password"):
        emailer.send_email("s", "<p>h</p>", "t")


def test_friends_get_a_blind_copy(fake_smtp, monkeypatch):
    monkeypatch.setenv("SUBSCRIBERS", "ana@example.com, ben@example.com")
    emailer.send_email("s", "<p>h</p>", "t")
    message = fake_smtp.instances[0].sent
    assert message["To"] == "me@example.com"  # friends never appear here
    assert message["Bcc"] == "ana@example.com, ben@example.com"


def test_no_subscribers_means_no_blind_copy(fake_smtp):
    emailer.send_email("s", "<p>h</p>", "t")
    assert fake_smtp.instances[0].sent["Bcc"] is None


def test_parse_subscribers():
    value = " Ana@Example.com,ben@example.com\n ana@example.com ; me@example.com \n"
    # Any separator and case; duplicates and the owner's own address dropped.
    assert emailer.parse_subscribers(value, "ME@example.com") == ["ana@example.com", "ben@example.com"]
    assert emailer.parse_subscribers("", "me@example.com") == []
    # Anything not shaped like an address is dropped, so it can't break the send.
    assert emailer.parse_subscribers("<html> ana@example.com hello@", "me@example.com") == ["ana@example.com"]


class FakeResponse:
    def __init__(self, text, status=200):
        self.text, self.status = text, status

    def raise_for_status(self):
        if self.status != 200:
            raise requests.HTTPError(f"{self.status}")


@pytest.fixture
def sign_up_list(monkeypatch):
    """Makes SIGNUP_LIST_URL answer with the given response (or raise the given error)."""
    def _answer(answer):
        monkeypatch.setenv("SIGNUP_LIST_URL", "https://script.example.com/exec?key=k")
        def fake_get(url, timeout):
            if isinstance(answer, Exception):
                raise answer
            return answer
        monkeypatch.setattr(requests, "get", fake_get)
    return _answer


def test_sign_up_list_adds_to_subscribers(monkeypatch, sign_up_list):
    monkeypatch.setenv("SUBSCRIBERS", "ana@example.com")
    sign_up_list(FakeResponse("Ben@example.com\nana@example.com\n"))
    assert emailer.subscribers("me@example.com") == ["ana@example.com", "ben@example.com"]


@pytest.mark.parametrize("answer", [
    requests.ConnectionError("down"),
    FakeResponse("", status=500),
    FakeResponse("ERROR: wrong key"),
    FakeResponse("<!DOCTYPE html><html>Sign in - Google Accounts</html>"),
])
def test_broken_sign_up_list_still_sends_to_the_others(monkeypatch, sign_up_list, answer, capsys):
    monkeypatch.setenv("SUBSCRIBERS", "ana@example.com")
    sign_up_list(answer)
    assert emailer.subscribers("me@example.com") == ["ana@example.com"]
    assert "WARNING" in capsys.readouterr().out
