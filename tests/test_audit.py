import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "audit-tests-secret-with-at-least-32-characters",
            "BCRYPT_ROUNDS": 4,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "SMTP_ENABLED": False,
        }
    ).test_client()


def login(client, email="admin@lms.test", password="Lms@2026"):
    return client.post("/auth/login", json={"email": email, "password": password})


def auth(client, email="admin@lms.test"):
    return {"Authorization": "Bearer " + login(client, email).json["accessToken"]}


def test_audit_admin_only_and_login_events(client):
    assert client.get("/admin/api/audit").status_code == 401
    student = auth(client, "chi.sv@lms.test")
    assert client.get("/admin/api/audit", headers=student).status_code == 403
    login(client, "chi.sv@lms.test", "bad-password")
    admin = auth(client)
    result = client.get("/admin/api/audit?action=LOGIN&actorId=u4", headers=admin)
    assert result.status_code == 200
    assert result.json["total"] == 2
    assert {item["result"] for item in result.json["items"]} == {"SUCCESS", "FAILURE"}
    assert "bad-password" not in result.get_data(as_text=True)
    assert "Lms@2026" not in result.get_data(as_text=True)
    assert result.headers["Cache-Control"] == "private, no-store"
    assert client.get("/admin/api/audit?page=0", headers=admin).status_code == 400


def test_audit_persists_grade_change_and_restart(client):
    teacher = auth(client, "an.gv@lms.test")
    assert (
        client.put(
            "/courses/c1/grades/u4", headers=teacher, json={"score": 9}
        ).status_code
        == 200
    )
    admin = auth(client)
    restarted = create_app(dict(client.application.config)).test_client()
    result = restarted.get("/admin/api/audit?action=UPDATE_GRADE", headers=admin)
    assert result.json["total"] == 1
    assert result.json["items"][0]["details"] == {"oldScore": 7.5, "newScore": 9}


def test_non_grade_denial_is_not_recorded_as_grade_change(client):
    student = auth(client, "chi.sv@lms.test")
    assert (
        client.put(
            "/admin/api/users/u1", headers=student, json={"role": "STUDENT"}
        ).status_code
        == 403
    )
    admin = auth(client)
    assert (
        client.get("/admin/api/audit?action=UPDATE_GRADE", headers=admin).json["total"]
        == 0
    )
    denied = client.get("/admin/api/audit?action=PUT_ACCESS_DENIED", headers=admin)
    assert denied.json["total"] == 1
