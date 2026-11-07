import smtplib
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest

from app import create_app
from app.api.local_mail import send_reset_email


@pytest.fixture
def mail_app(tmp_path, monkeypatch):
    smtp = MagicMock()
    monkeypatch.setattr("app.api.mail.smtplib.SMTP", smtp)
    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "reset-email-tests-secret-at-least-32-characters",
            "BCRYPT_ROUNDS": 4,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "SMTP_ENABLED": True,
            "SMTP_HOST": "smtp.example.test",
            "SMTP_FROM": "noreply@example.test",
            "SMTP_USERNAME": "smtp-user",
            "SMTP_PASSWORD": "smtp-password",
            "PUBLIC_BASE_URL": "https://lms.example.test",
            "RESET_TOKEN_TTL_SECONDS": 120,
        }
    )
    return app, smtp


def request_link(app, smtp):
    client = app.test_client()
    response = client.post(
        "/auth/forgot-password",
        json={"email": "chi.sv@lms.test"},
        headers={"Host": "attacker.example"},
    )
    assert response.status_code == 202
    assert response.json == {"status": "sent"}
    message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
    body = message.get_content()
    link = next(line for line in body.splitlines() if line.startswith("https://"))
    assert urlsplit(link).netloc == "lms.example.test"
    assert "120 giây" in body
    token = parse_qs(urlsplit(link).fragment)["token"][0]
    return client, token, message


def test_smtp_link_can_reset_password_once(mail_app):
    app, smtp = mail_app
    client, token, message = request_link(app, smtp)
    smtp.assert_called_once_with("smtp.example.test", 587, timeout=10)
    connection = smtp.return_value.__enter__.return_value
    connection.starttls.assert_called_once()
    connection.login.assert_called_once_with("smtp-user", "smtp-password")
    assert message["To"] == "chi.sv@lms.test"
    assert message["From"] == "noreply@example.test"
    assert client.get("/resetpassword").status_code == 200
    body = {"token": token, "password": "NewPassword@2026"}
    assert client.post("/auth/reset-password", json=body).status_code == 200
    assert client.post("/auth/reset-password", json=body).status_code == 400
    assert (
        client.post(
            "/auth/login",
            json={
                "email": "chi.sv@lms.test",
                "password": "NewPassword@2026",
            },
        ).status_code
        == 200
    )


def test_emailed_link_expires(mail_app, monkeypatch):
    app, smtp = mail_app
    client, token, _ = request_link(app, smtp)
    import time

    future = time.time() + 121
    monkeypatch.setattr("app.database.db.time.time", lambda: future)
    assert (
        client.post(
            "/auth/reset-password",
            json={
                "token": token,
                "password": "NewPassword@2026",
            },
        ).status_code
        == 400
    )


def test_unknown_email_and_smtp_failure_have_generic_response(mail_app, caplog):
    app, smtp = mail_app
    client = app.test_client()
    assert client.post(
        "/auth/forgot-password",
        json={
            "email": "unknown@example.test",
        },
    ).json == {"status": "sent"}
    smtp.assert_not_called()
    smtp.side_effect = smtplib.SMTPException("private-email-and-token")
    response = client.post("/auth/forgot-password", json={"email": "chi.sv@lms.test"})
    assert response.status_code == 202
    assert response.json == {"status": "sent"}
    assert "delivery failed" in caplog.text
    assert "private-email-and-token" not in caplog.text


def test_smtp_ssl_delivery(mail_app, monkeypatch):
    app, plain_smtp = mail_app
    secure_smtp = MagicMock()
    monkeypatch.setattr("app.api.mail.smtplib.SMTP_SSL", secure_smtp)
    app.config.update(SMTP_USE_SSL=True, SMTP_USE_TLS=False, SMTP_PORT=465)
    request_link(app, secure_smtp)
    plain_smtp.assert_not_called()
    connection = secure_smtp.return_value.__enter__.return_value
    connection.starttls.assert_not_called()
    connection.send_message.assert_called_once()


def test_local_mail_contains_link_and_configured_expiry(mail_app, tmp_path):
    app, _ = mail_app
    app.debug = True
    app.instance_path = str(tmp_path)
    with app.app_context():
        send_reset_email("chi.sv@lms.test", "test-token")
    message = next((tmp_path / "mailbox").glob("*.txt")).read_text(encoding="utf-8")
    assert "https://lms.example.test/resetpassword#token=test-token" in message
    assert "120 giây" in message
