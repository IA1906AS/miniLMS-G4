"""Local email simulation for miniLMS development."""

from pathlib import Path

from flask import current_app


def send_reset_email(email: str, token: str) -> None:
    """Save a simulated reset email to a local text file."""

    if not current_app.debug:
        raise RuntimeError("Local email simulation is only available in debug mode.")

    mailbox = Path(current_app.instance_path) / "mailbox"
    mailbox.mkdir(parents=True, exist_ok=True)

    # Avoid using email addresses or tokens in filenames.
    import secrets

    filename = mailbox / f"reset-{secrets.token_hex(12)}.txt"

    message = (
        "miniLMS - Password Reset\n"
        "========================\n\n"
        f"To: {email}\n"
        "Subject: Dat lai mat khau miniLMS\n\n"
        "Ban da yeu cau dat lai mat khau.\n\n"
        f"Reset token: {token}\n\n"
        "Mo trang:\n"
        "http://127.0.0.1:5000/resetpassword\n\n"
        "Dan token vao o 'Token dat lai mat khau', "
        "sau do nhap mat khau moi.\n\n"
        "Token co hieu luc trong 15 phut.\n"
        "Neu ban khong yeu cau, hay bo qua email nay.\n"
    )

    # Exclusive creation avoids overwriting an existing email.
    with filename.open("x", encoding="utf-8") as file:
        file.write(message)
