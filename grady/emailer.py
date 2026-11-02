"""Send an email through an SMTP server (e.g. Gmail) using credentials from .env."""

import os
import re
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

from grady.config import PROJECT_ROOT, get_secret

TIMEOUT_SECONDS = 30


def parse_subscribers(value: str, owner: str) -> list[str]:
    """Friends' addresses from the SUBSCRIBERS secret: separated by commas, spaces
    or new lines, any case. Duplicates and the owner's own address are dropped."""
    found = []
    for address in re.split(r"[\s,;]+", value.strip().lower()):
        if address and address != owner.lower() and address not in found:
            found.append(address)
    return found


def subscribers(owner: str) -> list[str]:
    """Optional: no SUBSCRIBERS secret means the email goes to EMAIL_TO only.

    Friends' addresses live only in this secret (GitHub Secrets / .env), never in
    the code or config.yaml, so the repository can be public without leaking them.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    return parse_subscribers(os.environ.get("SUBSCRIBERS", ""), owner)


def send_email(subject: str, html: str, text: str) -> None:
    owner = get_secret("EMAIL_TO")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = get_secret("SMTP_USER")
    message["To"] = owner
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
