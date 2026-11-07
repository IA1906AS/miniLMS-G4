"""Local email simulation for miniLMS development."""

from pathlib import Path

from flask import current_app

from app.api.mail import reset_message


def send_reset_email(email: str, token: str) -> None:
    """Save a simulated reset email to a local text file."""

    if not current_app.debug:
        raise RuntimeError("Local email simulation is only available in debug mode.")

    mailbox = Path(current_app.instance_path) / "mailbox"
    mailbox.mkdir(parents=True, exist_ok=True)

    # Avoid using email addresses or tokens in filenames.
    import secrets

    filename = mailbox / f"reset-{secrets.token_hex(12)}.txt"

    message = reset_message(email, token)

    # Exclusive creation avoids overwriting an existing email.
    with filename.open("x", encoding="utf-8") as file:
        file.write(f"To: {email}\nSubject: {message['Subject']}\n\n")
        file.write(message.get_content())
