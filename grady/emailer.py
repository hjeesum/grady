"""Send an email through an SMTP server (e.g. Gmail) using credentials from .env."""

import hashlib
import hmac
import os
import re
import smtplib
import time
from collections.abc import Callable
from email.message import EmailMessage
from urllib.parse import parse_qs, urlencode, urlsplit

import requests
from dotenv import load_dotenv

from grady.config import PROJECT_ROOT, get_secret

TIMEOUT_SECONDS = 30
# One email per person, about one a second: a sudden burst of hundreds looks
# like spam to Gmail. 200 subscribers take a little over 3 minutes.
SEND_INTERVAL_SECONDS = 1


# Loose on purpose: just enough to throw away anything that isn't an address
# (e.g. a web page returned by mistake), which would make the whole send fail.
EMAIL_ADDRESS = re.compile(r"[^@\s<>\"']+@[^@\s<>\"']+\.[a-z]{2,}")


def parse_subscribers(value: str, owner: str) -> list[str]:
    """Friends' addresses: separated by commas, spaces or new lines, any case.
    Duplicates, the owner's own address and anything not shaped like an address
    are dropped."""
    found = []
    for address in re.split(r"[\s,;]+", value.strip().lower()):
        if EMAIL_ADDRESS.fullmatch(address) and address != owner.lower() and address not in found:
            found.append(address)
    return found


def signed_up(url: str) -> str:
    """Addresses from the sign-up form, one per line (see scripts/signup_sheet.gs).

    Returns "" if the list can't be read: a broken form must never stop the email
    going to everyone else, so this only prints a warning.
    """
    try:
        # Google answers with a redirect to the real content; requests follows it.
        response = requests.get(url, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"WARNING: couldn't read the sign-up list ({type(error).__name__}); sending without it.")
        return ""
    if response.text.startswith("ERROR") or "<html" in response.text[:500].lower():
        # A wrong key, or a Google sign-in page if the web app isn't open to "Anyone".
        print(f"WARNING: the sign-up list answered {response.text[:40]!r}; sending without it.")
        return ""
    return response.text


def subscribers(owner: str) -> list[str]:
    """Optional: with neither SUBSCRIBERS nor SIGNUP_LIST_URL, the email goes to EMAIL_TO only.

    Friends' addresses live only in secrets (GitHub Secrets / .env) and the private
    sign-up Sheet, never in the code or config.yaml, so the repository can be public
    without leaking them. SIGNUP_LIST_URL includes the key, so it's a secret too.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    by_hand = parse_subscribers(os.environ.get("SUBSCRIBERS", ""), owner)
    url = os.environ.get("SIGNUP_LIST_URL", "")
    lines = signed_up(url).splitlines() if url else []
    # "-address" lines are people who used the unsubscribe link: they're dropped
    # even if they're in SUBSCRIBERS.
    left = set(parse_subscribers(" ".join(line[1:] for line in lines if line.startswith("-")), owner))
    from_form = parse_subscribers(" ".join(line for line in lines if not line.startswith("-")), owner)
    found = [address for address in dict.fromkeys(by_hand + from_form) if address not in left]
    # Counts only, never addresses: the repository is public, and so are its Actions logs.
    print(f"Subscribers: {len(found)} ({len(from_form)} from the sign-up form, "
          f"{len(by_hand)} from SUBSCRIBERS, {len(left)} unsubscribed, duplicates counted once)")
    return found


def unsubscribe_link(address: str) -> str | None:
    """The address's own unsubscribe link (see scripts/signup_sheet.gs), or None
    without a sign-up list.

    The token is an HMAC: a code made from the address and the secret key. The
    script makes the same code to check it, so changing the address in a link
    (to unsubscribe someone else) gives a wrong code. The link never contains the
    key itself, which would let anyone read the whole list.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    parts = urlsplit(os.environ.get("SIGNUP_LIST_URL", ""))
    key = parse_qs(parts.query).get("key", [""])[0]
    if not key:
        return None
    token = hmac.new(key.encode(), address.encode(), hashlib.sha256).hexdigest()
    query = urlencode({"action": "unsubscribe", "email": address, "token": token})
    return f"{parts.scheme}://{parts.netloc}{parts.path}?{query}"


def build_message(subject: str, to: str, html: str, text: str, unsubscribe_url: str | None) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = get_secret("SMTP_USER")
    message["To"] = to
    if unsubscribe_url:
        # Email programs that understand this header show their own "Unsubscribe" button.
        message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    # The plain-text version is the main body and the HTML is an "alternative":
    # email programs show the HTML if they can, and the text otherwise.
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def connect() -> smtplib.SMTP:
    host = get_secret("SMTP_HOST")
    port = int(get_secret("SMTP_PORT"))
    if port == 465:
        # Port 465: the connection is encrypted from the start.
        server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT_SECONDS)
    else:
        # Port 587: connect, then upgrade to encryption with STARTTLS
        # BEFORE sending the password.
        server = smtplib.SMTP(host, port, timeout=TIMEOUT_SECONDS)
        server.starttls()
    try:
        server.login(get_secret("SMTP_USER"), get_secret("SMTP_PASSWORD"))
    except smtplib.SMTPAuthenticationError:
        # "from None" hides the original error, whose details aren't useful here.
        raise RuntimeError(
            "The email server rejected the login. For Gmail, SMTP_PASSWORD must be "
            "a 16-character App Password, not your normal Google password."
        ) from None
    return server


def send_email(subject: str, html: Callable[[str | None], str], text: Callable[[str | None], str],
               friends: list[str] | None = None) -> int:
    """Send one email to EMAIL_TO, then one to each friend (default: read them now).

    html and text make the email for one unsubscribe link (None for EMAIL_TO).
    Each friend gets their own copy, addressed to them, with their own link.
    Raises if EMAIL_TO's copy fails (nothing was sent, so nothing should be marked
    as emailed). A friend's copy failing doesn't stop the others; returns how many failed.
    """
    owner = get_secret("EMAIL_TO")
    if friends is None:
        friends = subscribers(owner)
    server = connect()
    try:
        server.send_message(build_message(subject, owner, html(None), text(None), None))
        failed = 0
        for address in friends:
            link = unsubscribe_link(address)
            message = build_message(subject, address, html(link), text(link), link)
            time.sleep(SEND_INTERVAL_SECONDS)
            try:
                server.send_message(message)
            except smtplib.SMTPServerDisconnected:
                # Servers may close a long session: connect again and retry this one.
                server = connect()
                try:
                    server.send_message(message)
                except smtplib.SMTPException:
                    failed += 1
            except smtplib.SMTPRecipientsRefused:
                failed += 1  # a mistyped or closed address
            except smtplib.SMTPDataError as error:
                # Gmail's daily limit: "550 5.4.5 Daily user sending limit exceeded".
                # Every later send would fail too, so stop here.
                failed += len(friends) - friends.index(address)
                print(f"WARNING: the email server stopped sending ({error.smtp_code}).")
                break
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            pass
    return failed
