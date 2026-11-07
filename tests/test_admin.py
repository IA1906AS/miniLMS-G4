from pathlib import Path

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "admin-tests-secret-with-at-least-32-characters",
            "BCRYPT_ROUNDS": 4,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
        }
    ).test_client()


def login(client, email):
    return client.post("/auth/login", json={"email": email, "password": "Lms@2026"})


def auth(client, email="admin@lms.test"):
    return {"Authorization": "Bearer " + login(client, email).json["accessToken"]}


def test_admin_search_is_private_and_excludes_secrets(client):
    assert client.get("/admin/api/users").status_code == 401
    student = auth(client, "chi.sv@lms.test")
    assert client.get("/admin/api/users", headers=student).status_code == 403
    admin = auth(client)
    result = client.get("/admin/api/users?q=CHI.SV", headers=admin)
    assert result.status_code == 200
    assert result.json["total"] == 1
    assert set(result.json["items"][0]) == {
        "id",
        "email",
        "fullName",
        "role",
        "isLocked",
    }
    assert result.headers["Cache-Control"] == "private, no-store"
    assert client.get("/admin/api/users?page=0", headers=admin).status_code == 400


def test_lock_and_unlock_revoke_old_sessions(client):
    admin = auth(client)
    student = auth(client, "chi.sv@lms.test")
    update = "/admin/api/users/u4"
    assert client.put(update, headers=admin, json={"isLocked": True}).status_code == 200
    assert client.get("/me", headers=student).status_code == 401
    assert login(client, "chi.sv@lms.test").status_code == 401
    assert (
        client.put(update, headers=admin, json={"isLocked": False}).status_code == 200
    )
    assert login(client, "chi.sv@lms.test").status_code == 200
    assert client.get("/me", headers=student).status_code == 401
    log = Path(client.application.config["AUDIT_LOG_PATH"]).read_text()
    assert "ADMIN_UPDATE_USER" in log


def test_role_change_revokes_session_and_grants_new_role(client):
    admin = auth(client)
    old = auth(client, "chi.sv@lms.test")
    assert (
        client.put(
            "/admin/api/users/u4", headers=admin, json={"role": "ADMIN"}
        ).status_code
        == 200
    )
    assert client.get("/me", headers=old).status_code == 401
    assert (
        client.get(
            "/admin/api/users", headers=auth(client, "chi.sv@lms.test")
        ).status_code
        == 200
    )


@pytest.mark.parametrize("body", [{"isLocked": True}, {"role": "STUDENT"}])
def test_admin_cannot_disable_own_account(client, body):
    headers = auth(client)
    result = client.put("/admin/api/users/u1", headers=headers, json=body)
    assert result.status_code == 409
    assert result.json["error"] == "SELF_ADMIN_CHANGE"
    assert client.get("/admin/api/users", headers=headers).status_code == 200


def test_instructor_must_transfer_courses_before_role_change(client):
    result = client.put(
        "/admin/api/users/u2", headers=auth(client), json={"role": "STUDENT"}
    )
    assert result.status_code == 409
    assert result.json["error"] == "INSTRUCTOR_HAS_COURSES"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"isLocked": "false"},
        {"role": []},
        {"role": "OWNER"},
        {"email": "other@example.test"},
    ],
)
def test_admin_rejects_invalid_updates(client, body):
    assert (
        client.put("/admin/api/users/u4", headers=auth(client), json=body).status_code
        == 400
    )


def test_non_admin_cannot_update_users(client):
    headers = auth(client, "an.gv@lms.test")
    assert (
        client.put(
            "/admin/api/users/u4", headers=headers, json={"role": "ADMIN"}
        ).status_code
        == 403
    )
