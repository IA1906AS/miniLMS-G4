from pathlib import Path

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "change-password-test-secret-at-least-32-characters",
            "BCRYPT_ROUNDS": 4,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "RESET_TOKEN_ECHO": True,
        }
    )
    return app.test_client()


def login(client, password="Lms@2026", email="chi.sv@lms.test"):
    return client.post("/auth/login", json={"email": email, "password": password})


def auth(client, email="chi.sv@lms.test"):
    return {"Authorization": "Bearer " + login(client, email=email).json["accessToken"]}


@pytest.mark.parametrize(
    "email", ["chi.sv@lms.test", "an.gv@lms.test", "admin@lms.test"]
)
def test_change_password_invalidates_sessions_and_reset_links(client, email):
    headers = auth(client, email)
    second = auth(client, email)
    reset = client.post("/auth/forgot-password", json={"email": email}).json[
        "resetToken"
    ]
    response = client.post(
        "/auth/change-password",
        headers=headers,
        json={
            "currentPassword": "Lms@2026",
            "newPassword": "NewPassword@2026",
        },
    )
    assert response.status_code == 200
    for session in (headers, second):
        assert client.get("/me", headers=session).status_code == 401
    assert login(client, email=email).status_code == 401
    assert login(client, "NewPassword@2026", email).status_code == 200
    assert (
        client.post(
            "/auth/reset-password",
            json={
                "token": reset,
                "password": "ResetPassword@2026",
            },
        ).status_code
        == 400
    )
    log = Path(client.application.config["AUDIT_LOG_PATH"]).read_text()
    assert '"action": "CHANGE_PASSWORD"' in log
    assert "NewPassword@2026" not in log
    assert "Lms@2026" not in log


def test_change_password_requires_auth_and_current_password(client):
    body = {"currentPassword": "wrong-password", "newPassword": "NewPassword@2026"}
    assert client.post("/auth/change-password", json=body).status_code == 401
    headers = auth(client)
    assert client.post("/auth/change-password", headers=headers, json=body).json == {
        "error": "INVALID_CREDENTIALS",
    }
    assert client.get("/me", headers=headers).status_code == 200
    assert login(client).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"currentPassword": "Lms@2026", "newPassword": "short"},
        {"currentPassword": "Lms@2026", "newPassword": "Lms@2026"},
        {"currentPassword": "Lms@2026", "newPassword": "á" * 37},
        {"currentPassword": "x" * 73, "newPassword": "NewPassword@2026"},
        {"currentPassword": 123, "newPassword": "NewPassword@2026"},
        {
            "currentPassword": "Lms@2026",
            "newPassword": "NewPassword@2026",
            "userId": "u1",
        },
    ],
)
def test_change_password_rejects_invalid_input(client, body):
    headers = auth(client)
    assert (
        client.post("/auth/change-password", headers=headers, json=body).status_code
        == 400
    )
    assert client.get("/me", headers=headers).status_code == 200


def test_change_password_rate_limit(client):
    headers = auth(client)
    for _ in range(5):
        assert (
            client.post(
                "/auth/change-password",
                headers=headers,
                json={
                    "currentPassword": "wrong-password",
                    "newPassword": "NewPassword@2026",
                },
            ).status_code
            == 401
        )
    response = client.post(
        "/auth/change-password",
        headers=headers,
        json={
            "currentPassword": "Lms@2026",
            "newPassword": "NewPassword@2026",
        },
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
