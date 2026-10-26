"""Tests for the Flask Mini LMS website (run from the lms-submit root).

All database writes go to a pytest-created temporary SQLite database.
The real instance/website.sqlite3 is never touched.
"""

import hashlib
from unittest.mock import patch
from urllib.parse import urlsplit

import bcrypt
import pytest

from web import create_app
from web.db import get_db, init_db


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "website-tests-only-do-not-use-in-production",
            "DATABASE": str(tmp_path / "test_website.sqlite3"),
            "DEMO_RESET_LINKS": True,
        }
    )
    with application.app_context():
        init_db()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_token(client, path):
    response = client.get(path)
    assert response.status_code == 200
    with client.session_transaction() as session:
        return session["csrf_token"]


def register(client, email="student@example.com", password="Test@123456", **extra):
    data = {
        "csrf_token": csrf_token(client, "/register"),
        "full_name": "Test Student",
        "email": email,
        "password": password,
    }
    data.update(extra)
    return client.post("/register", data=data)


def login(client, email="student@example.com", password="Test@123456"):
    return client.post(
        "/login",
        data={
            "csrf_token": csrf_token(client, "/login"),
            "email": email,
            "password": password,
        },
    )


def request_reset(client, app, email="student@example.com"):
    token = csrf_token(client, "/forgot-password")
    with patch.object(app.logger, "warning") as warning:
        response = client.post(
            "/forgot-password",
            data={"csrf_token": token, "email": email},
        )
    assert response.status_code == 302
    return warning


def test_public_pages_open(client):
    for path in ("/", "/login", "/register", "/forgot-password"):
        assert client.get(path).status_code == 200


def test_account_requires_login(client):
    response = client.get("/account")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_registration_saves_bcrypt_hash_and_student_role(app, client):
    response = register(client, role="ADMIN")
    assert response.status_code == 302

    with app.app_context():
        row = (
            get_db()
            .execute(
                "SELECT full_name, email, role, password_hash FROM users WHERE email = ?",
                ("student@example.com",),
            )
            .fetchone()
        )

    assert row is not None
    assert row["full_name"] == "Test Student"
    assert row["role"] == "STUDENT"  # Client cannot self-assign ADMIN.
    assert row["password_hash"] != "Test@123456"
    assert bcrypt.checkpw(b"Test@123456", row["password_hash"].encode())


def test_login_then_logout(client):
    register(client)
    assert login(client).status_code == 302

    account = client.get("/account")
    assert account.status_code == 200
    assert "Test Student" in account.get_data(as_text=True)

    logout_csrf = csrf_token(client, "/account")
    result = client.post("/logout", data={"csrf_token": logout_csrf})
    assert result.status_code == 302
    assert client.get("/account").status_code == 302


def test_wrong_password_does_not_authenticate(client):
    register(client)
    response = login(client, password="Wrong@123456")
    assert response.status_code == 200
    assert client.get("/account").status_code == 302


def test_duplicate_email_is_rejected(app, client):
    assert register(client).status_code == 302
    assert register(client, email="STUDENT@example.com").status_code == 200
    with app.app_context():
        count = get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert count == 1


@pytest.mark.parametrize(
    ("name", "email", "password"),
    [
        ("X", "student@example.com", "Test@123456"),
        ("Test Student", "not-an-email", "Test@123456"),
        ("Test Student", "student@example.com", "short"),
    ],
)
def test_invalid_registration_is_not_saved(app, client, name, email, password):
    response = register(client, email=email, password=password, full_name=name)
    assert response.status_code == 200
    with app.app_context():
        count = get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert count == 0


def test_missing_csrf_token_is_rejected(client):
    assert (
        client.post(
            "/register",
            data={
                "full_name": "Test Student",
                "email": "student@example.com",
                "password": "Test@123456",
            },
        ).status_code
        == 400
    )


def test_forgot_password_does_not_reveal_unknown_email(app, client):
    known = request_reset(client, app)
    unknown = request_reset(client, app, "unknown@example.com")
    assert not known.called  # No account has been registered yet.
    assert not unknown.called


def test_reset_password_is_one_time_and_updates_login(app, client):
    register(client)
    warning = request_reset(client, app)
    assert warning.called

    # The demo prints its link only to the local Flask logger.
    link = warning.call_args.args[1]
    path = urlsplit(link).path
    raw_token = path.rsplit("/", 1)[-1]
    assert path.startswith("/reset-password/")

    with app.app_context():
        record = (
            get_db().execute("SELECT token_hash FROM password_reset_tokens").fetchone()
        )
    assert record is not None
    assert record["token_hash"] != raw_token
    assert record["token_hash"] == hashlib.sha256(raw_token.encode()).hexdigest()

    assert client.get(path).status_code == 200
    result = client.post(
        path,
        data={
            "csrf_token": csrf_token(client, path),
            "password": "NewPassword@2026",
            "confirm": "NewPassword@2026",
        },
    )
    assert result.status_code == 302
    assert client.get(path).status_code == 302  # Link is single-use.

    assert login(client, password="Test@123456").status_code == 200
    assert login(client, password="NewPassword@2026").status_code == 302
    assert client.get("/account").status_code == 200


def test_expired_reset_link_is_rejected(app, client):
    register(client)
    warning = request_reset(client, app)
    path = urlsplit(warning.call_args.args[1]).path

    with app.app_context():
        db = get_db()
        db.execute("UPDATE password_reset_tokens SET expires_at = 0")
        db.commit()

    assert client.get(path).status_code == 302


def test_seed_import_adds_sample_accounts_courses_and_grades(app):
    # Uses the project's seed.json as input, but only writes to temp SQLite.
    runner = app.test_cli_runner()
    result = runner.invoke(args=["import-seed"])
    assert result.exit_code == 0, result.output

    with app.app_context():
        db = get_db()
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        courses = db.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        grades = db.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
        admin = db.execute(
            "SELECT role, password_hash FROM users WHERE email = ?",
            ("admin@lms.test",),
        ).fetchone()

    assert (users, courses, grades) == (6, 2, 4)
    assert admin is not None
    assert admin["role"] == "ADMIN"
    assert admin["password_hash"] != "Lms@2026"

    second = runner.invoke(args=["import-seed"])
    assert second.exit_code == 0, second.output
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 6
        assert db.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0] == 4
