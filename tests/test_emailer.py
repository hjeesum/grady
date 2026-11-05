import hashlib
import hmac
import smtplib

import pytest
import requests

from grady import emailer


class FakeSMTP:
    """Stands in for smtplib.SMTP: records what happens instead of sending anything."""
    instances = []
    refuse = set()  # addresses this fake server refuses
    limit = None  # after this many emails, answer like Gmail's daily limit

    def __init__(self, host, port, timeout):
        self.host, self.port = host, port
        self.calls = []
        self.messages = []
        FakeSMTP.instances.append(self)

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append("login")

    def send_message(self, message):
        if message["To"] in FakeSMTP.refuse:
            raise smtplib.SMTPRecipientsRefused({message["To"]: (550, b"No such user")})
        if FakeSMTP.limit is not None and len(self.messages) >= FakeSMTP.limit:
            raise smtplib.SMTPDataError(550, b"5.4.5 Daily user sending limit exceeded")
        self.calls.append("send")
        self.messages.append(message)

    def quit(self):
        self.calls.append("quit")


KEY = "secret-key-123"
LIST_URL = f"https://script.example.com/exec?key={KEY}"


@pytest.fixture
def fake_smtp(monkeypatch):
    # monkeypatch undoes these changes after the test.
    FakeSMTP.instances, FakeSMTP.refuse, FakeSMTP.limit = [], set(), None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(emailer.time, "sleep", lambda seconds: None)
    for name, value in {
        "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
        "SMTP_USER": "me@example.com", "SMTP_PASSWORD": "secret",
        "EMAIL_TO": "me@example.com",
        # Set, so real ones in .env aren't loaded.
        "SUBSCRIBERS": "", "SIGNUP_LIST_URL": "",
    }.items():
        monkeypatch.setenv(name, value)
    return FakeSMTP


def html(link):
    return f"<p>Hello</p><a href='{link}'>Unsubscribe</a>" if link else "<p>Hello</p>"


def text(link):
    return f"Hello {link}" if link else "Hello"


def test_sends_html_with_plain_text_alternative(fake_smtp):
    emailer.send_email("Subject line", html, text, friends=[])
    message = fake_smtp.instances[0].messages[0]
    assert message["Subject"] == "Subject line"
    assert message["To"] == "me@example.com"
    assert message.get_body(("plain",)).get_content().strip() == "Hello"
    assert "<p>Hello</p>" in message.get_body(("html",)).get_content()


def test_encrypts_before_sending_the_password(fake_smtp):
    emailer.send_email("s", html, text, friends=[])
    assert fake_smtp.instances[0].calls == ["starttls", "login", "send", "quit"]


def test_wrong_password_gives_a_helpful_error(fake_smtp, monkeypatch):
    def reject(self, user, password):
        raise smtplib.SMTPAuthenticationError(535, b"Bad credentials")
    monkeypatch.setattr(FakeSMTP, "login", reject)
    with pytest.raises(RuntimeError, match="App Password"):
        emailer.send_email("s", html, text, friends=[])


def test_each_friend_gets_their_own_email_and_link(fake_smtp, monkeypatch):
    monkeypatch.setenv("SIGNUP_LIST_URL", LIST_URL)
    failed = emailer.send_email("s", html, text, friends=["ana@example.com", "ben@example.com"])
    mine, ana, ben = fake_smtp.instances[0].messages
    assert failed == 0
    assert [m["To"] for m in (mine, ana, ben)] == ["me@example.com", "ana@example.com", "ben@example.com"]
    assert all(m["Bcc"] is None for m in (mine, ana, ben))  # nobody sees anyone else
    assert mine["List-Unsubscribe"] is None and "Unsubscribe" not in mine.get_body(("html",)).get_content()
    link = emailer.unsubscribe_link("ana@example.com")
    assert link in ana.get_body(("html",)).get_content() and link in ana.get_body(("plain",)).get_content()
    assert ana["List-Unsubscribe"] == f"<{link}>"
    assert link not in ben.get_body(("html",)).get_content()


def test_unsubscribe_link_cant_be_reused_for_someone_else(monkeypatch):
    monkeypatch.setenv("SIGNUP_LIST_URL", LIST_URL)
    link = emailer.unsubscribe_link("ana@example.com")
    assert link.startswith("https://script.example.com/exec?action=unsubscribe&email=ana%40example.com&token=")
    assert KEY not in link  # the key would let anyone read the whole list
    # The token is an HMAC of the address: another address gets a different one,
    # so editing the email in a link makes it invalid.
    token = hmac.new(KEY.encode(), b"ana@example.com", hashlib.sha256).hexdigest()
    assert link.endswith(token)
    assert emailer.unsubscribe_link("ben@example.com").split("token=")[1] != token


def test_no_sign_up_list_means_no_link(monkeypatch):
    monkeypatch.setenv("SIGNUP_LIST_URL", "")
    assert emailer.unsubscribe_link("ana@example.com") is None


def test_one_refused_address_does_not_stop_the_others(fake_smtp):
    fake_smtp.refuse = {"typo@example.com"}
    failed = emailer.send_email("s", html, text, friends=["typo@example.com", "ben@example.com"])
    assert failed == 1
    assert [m["To"] for m in fake_smtp.instances[0].messages] == ["me@example.com", "ben@example.com"]


def test_daily_sending_limit_stops_and_counts_the_rest(fake_smtp, capsys):
    fake_smtp.limit = 2  # my copy and ana's go, then the server says no
    failed = emailer.send_email("s", html, text, friends=["ana@example.com", "ben@example.com", "cy@example.com"])
    assert failed == 2
    assert "WARNING" in capsys.readouterr().out


def test_my_own_copy_failing_raises(fake_smtp):
    # Nothing was sent, so the run must not mark the jobs as emailed.
    fake_smtp.limit = 0
    with pytest.raises(smtplib.SMTPDataError):
        emailer.send_email("s", html, text, friends=["ana@example.com"])


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


def test_subscriber_count_is_logged_without_addresses(monkeypatch, sign_up_list, capsys):
    monkeypatch.setenv("SUBSCRIBERS", "ana@example.com")
    sign_up_list(FakeResponse("ben@example.com\nana@example.com"))
    emailer.subscribers("me@example.com")
    out = capsys.readouterr().out
    assert "Subscribers: 2 (2 from the sign-up form, 1 from SUBSCRIBERS" in out
    assert "@" not in out  # the Actions log is public


def test_unsubscribed_people_are_dropped_even_from_subscribers_secret(monkeypatch, sign_up_list, capsys):
    monkeypatch.setenv("SUBSCRIBERS", "ana@example.com, cy@example.com")
    sign_up_list(FakeResponse("ben@example.com\n-ana@example.com"))
    assert emailer.subscribers("me@example.com") == ["cy@example.com", "ben@example.com"]
    assert "1 unsubscribed" in capsys.readouterr().out
