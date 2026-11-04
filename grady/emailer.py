"""Send an email through an SMTP server (e.g. Gmail) using credentials from .env."""

import os
import re
import smtplib
from email.message import EmailMessage

import requests
from dotenv import load_dotenv

from grady.config import PROJECT_ROOT, get_secret

TIMEOUT_SECONDS = 30


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
    from_form = parse_subscribers(signed_up(url), owner) if url else []
    found = list(dict.fromkeys(by_hand + from_form))
    # Counts only, never addresses: the repository is public, and so are its Actions logs.
    print(f"Subscribers: {len(found)} ({len(from_form)} from the sign-up form, "
          f"{len(by_hand)} from SUBSCRIBERS, duplicates counted once)")
    return found


def send_email(subject: str, html: str, text: str, friends: list[str] | None = None) -> None:
    """Send to EMAIL_TO, with friends as a blind copy (default: read them now)."""
    owner = get_secret("EMAIL_TO")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = get_secret("SMTP_USER")
    message["To"] = owner
    if friends is None:
        friends = subscribers(owner)
    if friends:
        # Blind copy: each friend gets the email but can't see the others'
        # addresses. send_message() removes the Bcc line before sending.
        message["Bcc"] = ", ".join(friends)
    # The plain-text version is the main body and the HTML is an "alternative":
    # email programs show the HTML if they can, and the text otherwise.
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    host = get_secret("SMTP_HOST")
    port = int(get_secret("SMTP_PORT"))
    try:
        if port == 465:
            # Port 465: the connection is encrypted from the start.
            server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT_SECONDS)
        else:
            # Port 587: connect, then upgrade to encryption with STARTTLS
            # BEFORE sending the password.
            server = smtplib.SMTP(host, port, timeout=TIMEOUT_SECONDS)
            server.starttls()
        with server:
            server.login(get_secret("SMTP_USER"), get_secret("SMTP_PASSWORD"))
            server.send_message(message)
    except smtplib.SMTPAuthenticationError:
        # "from None" hides the original error, whose details aren't useful here.
        raise RuntimeError(
            "The email server rejected the login. For Gmail, SMTP_PASSWORD must be "
            "a 16-character App Password, not your normal Google password."
        ) from None
