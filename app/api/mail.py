"""Password reset messages and SMTP delivery."""

import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlencode, urlsplit

from flask import current_app


def validate_mail_config(config):
    base = config["PUBLIC_BASE_URL"]
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("PUBLIC_BASE_URL must be an http(s) origin without a path")
    if int(config["RESET_TOKEN_TTL_SECONDS"]) <= 0:
        raise ValueError("RESET_TOKEN_TTL_SECONDS must be positive")
    if config["SMTP_ENABLED"]:
        if not config["SMTP_HOST"] or not config["SMTP_FROM"]:
            raise ValueError("SMTP_HOST and SMTP_FROM are required for SMTP")
        if config["SMTP_USE_SSL"] and config["SMTP_USE_TLS"]:
            raise ValueError("Choose SMTP_USE_SSL or SMTP_USE_TLS, not both")


def reset_message(email: str, token: str) -> EmailMessage:
    cfg = current_app.config
    # A fragment is not sent to the web server or included in HTTP access logs.
    link = (
        cfg["PUBLIC_BASE_URL"].rstrip("/")
        + "/resetpassword#"
        + urlencode({"token": token})
    )
    message = EmailMessage()
    message["Subject"] = "miniLMS - Đặt lại mật khẩu"
    message["From"] = cfg["SMTP_FROM"] or "miniLMS <noreply@localhost>"
    message["To"] = email
    message.set_content(
        "Bạn đã yêu cầu đặt lại mật khẩu miniLMS.\n\n"
        f"Mở liên kết sau để nhập mật khẩu mới:\n{link}\n\n"
        f"Liên kết có hiệu lực trong {cfg['RESET_TOKEN_TTL_SECONDS']} giây "
        "kể từ khi yêu cầu và chỉ dùng được một lần.\n"
        "Nếu bạn không yêu cầu, hãy bỏ qua email này.\n"
    )
    return message


def send_smtp_reset_email(email: str, token: str) -> None:
    cfg = current_app.config
    message = reset_message(email, token)
    context = ssl.create_default_context()
    options = {"timeout": cfg["SMTP_TIMEOUT_SECONDS"]}
    connection: smtplib.SMTP
    if cfg["SMTP_USE_SSL"]:
        connection = smtplib.SMTP_SSL(
            cfg["SMTP_HOST"], cfg["SMTP_PORT"], context=context, **options
        )
    else:
        connection = smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], **options)
    with connection as smtp:
        if cfg["SMTP_USE_TLS"]:
            smtp.starttls(context=context)
        if cfg["SMTP_USERNAME"]:
            smtp.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"])
        smtp.send_message(message)
