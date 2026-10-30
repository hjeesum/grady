"""Send an email through an SMTP server (e.g. Gmail) using credentials from .env."""

import smtplib
from email.message import EmailMessage

from grady.config import get_secret

TIMEOUT_SECONDS = 30


def send_email(subject: str, html: str, text: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = get_secret("SMTP_USER")
    message["To"] = get_secret("EMAIL_TO")
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
