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
            "/courses/c1/grades/u4", headers=teacher, json={"score": 9, "version": 0}
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


def test_file_audit_failure_does_not_fail_committed_grade(client, tmp_path, caplog):
    teacher = auth(client, "an.gv@lms.test")
    client.application.config["AUDIT_LOG_PATH"] = str(tmp_path)
    result = client.put(
        "/courses/c1/grades/u4", headers=teacher, json={"score": 9.5, "version": 0}
    )
    assert result.status_code == 200
    assert result.json["version"] == 1
    store = client.application.extensions["lms_store"]
    assert store.get_enrollment("c1", "u4").score == 9.5
    rows, total = store.list_audit("UPDATE_GRADE", "u2", 1)
    assert total == 1
    assert rows[0]["details"] == {"oldScore": 7.5, "newScore": 9.5}
    assert "Unable to write audit file" in caplog.text


def test_database_audit_failure_rolls_back_grade_and_version(client, monkeypatch):
    teacher = auth(client, "an.gv@lms.test")
    store = client.application.extensions["lms_store"]
    original = store.record_audit

    def fail_grade_audit(record, **kwargs):
        if record["action"] == "UPDATE_GRADE":
            raise RuntimeError("Simulated audit database failure")
        return original(record, **kwargs)

    monkeypatch.setattr(store, "record_audit", fail_grade_audit)
    result = client.put(
        "/courses/c1/grades/u4", headers=teacher, json={"score": 9.5, "version": 0}
    )
    assert result.status_code == 500
    enrollment = store.get_enrollment("c1", "u4")
    assert enrollment.score == 7.5
    assert enrollment.version == 0
    assert store.list_audit("UPDATE_GRADE", "u2", 1)[1] == 0
