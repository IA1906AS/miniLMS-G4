import smtplib
from unittest.mock import Mock

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "announcement-tests-secret-at-least-32-characters",
            "BCRYPT_ROUNDS": 4,
            "SMTP_ENABLED": False,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
        }
    ).test_client()


def auth(client, email):
    response = client.post("/auth/login", json={"email": email, "password": "Lms@2026"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json["accessToken"]}


def post(client, headers, **changes):
    return client.post(
        "/courses/c1/announcements",
        headers=headers,
        json={"title": "Lịch học", "body": "Lớp học lúc 8 giờ.\nPhòng A1.", **changes},
    )


def test_create_and_view_enforces_course_membership(client):
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    outsider = auth(client, "em.sv@lms.test")
    other_teacher = auth(client, "binh.gv@lms.test")
    admin = auth(client, "admin@lms.test")
    assert client.get("/courses/c1/announcements").status_code == 401
    for actor in (student, outsider, other_teacher, admin):
        assert post(client, actor).status_code == 403
    result = post(client, teacher)
    assert result.status_code == 201
    assert result.json["email"]["status"] == "disabled"
    for actor in (teacher, admin, student):
        response = client.get("/courses/c1/announcements", headers=actor)
        assert response.status_code == 200
        assert response.json["total"] == 1
        assert response.json["items"][0]["body"].endswith("Phòng A1.")
        assert response.headers["Cache-Control"] == "private, no-store"
    assert (
        "email"
        not in client.get("/courses/c1/announcements", headers=student).json["items"][0]
    )
    for actor in (outsider, other_teacher):
        assert client.get("/courses/c1/announcements", headers=actor).status_code == 403
    client.delete("/courses/c1/enrollments/u4", headers=teacher)
    assert client.get("/courses/c1/announcements", headers=student).status_code == 403


def test_email_is_private_and_failures_do_not_lose_announcement(client, monkeypatch):
    client.application.config.update(
        SMTP_ENABLED=True,
        SMTP_FROM="sender@example.test",
        PUBLIC_BASE_URL="https://lms.example.test",
    )
    sender = Mock(side_effect=[smtplib.SMTPException("private details"), None])
    monkeypatch.setattr("app.api.announcements.send_smtp_message", sender)
    teacher = auth(client, "an.gv@lms.test")
    result = post(client, teacher)
    assert result.status_code == 201
    assert result.json["email"] == {"status": "partial", "sent": 1, "failed": 1}
    assert sender.call_count == 2
    addresses = []
    for call in sender.call_args_list:
        message = call.args[0]
        addresses.append(str(message["To"]))
        assert message["Cc"] is None and message["Bcc"] is None
        assert "https://lms.example.test/catalog?course=c1" in message.get_content()
    assert set(addresses) == {"chi.sv@lms.test", "dung.sv@lms.test"}
    saved = client.get("/courses/c1/announcements", headers=teacher).json["items"][0]
    assert saved["email"]["status"] == "partial"


def test_email_opt_out_and_locked_students(client, monkeypatch):
    client.application.config.update(SMTP_ENABLED=True, SMTP_FROM="sender@example.test")
    sender = Mock()
    monkeypatch.setattr("app.api.announcements.send_smtp_message", sender)
    teacher = auth(client, "an.gv@lms.test")
    assert (
        post(client, teacher, sendEmail=False).json["email"]["status"]
        == "not_requested"
    )
    sender.assert_not_called()
    admin = auth(client, "admin@lms.test")
    client.put("/admin/api/users/u4", headers=admin, json={"isLocked": True})
    assert post(client, teacher).json["email"] == {
        "status": "sent",
        "sent": 1,
        "failed": 0,
    }
    assert str(sender.call_args.args[0]["To"]) == "dung.sv@lms.test"


@pytest.mark.parametrize(
    "changes",
    [
        {"title": " "},
        {"body": ""},
        {"title": "x\nBcc: other@example.test"},
        {"body": "x" * 10001},
        {"sendEmail": "true"},
        {"authorId": "u1"},
    ],
)
def test_invalid_input(client, changes):
    assert post(client, auth(client, "an.gv@lms.test"), **changes).status_code == 400


def test_announcement_survives_restart_and_is_removed_with_course(client):
    teacher = auth(client, "an.gv@lms.test")
    post(client, teacher)
    restarted = create_app(dict(client.application.config)).test_client()
    assert (
        restarted.get("/courses/c1/announcements", headers=teacher).json["total"] == 1
    )
    assert (
        client.get("/courses/c1/announcements?page=0", headers=teacher).status_code
        == 400
    )
    admin = auth(client, "admin@lms.test")
    assert client.delete("/courses/c1", headers=admin).status_code == 200
    store = client.application.extensions["lms_store"]
    assert store.list_announcements("c1", 1)[1] == 0


def test_local_announcement_mailbox(client, tmp_path, monkeypatch):
    client.application.config.update(
        DEBUG=True, LOCAL_EMAIL_ENABLED=True, SMTP_ENABLED=False
    )
    client.application.instance_path = str(tmp_path)
    sender = Mock()
    monkeypatch.setattr("app.api.announcements.send_smtp_message", sender)
    result = post(client, auth(client, "an.gv@lms.test"))
    assert result.status_code == 201
    assert result.json["email"] == {"status": "local", "sent": 2, "failed": 0}
    files = list((tmp_path / "mailbox").glob("announcement-*.txt"))
    assert len(files) == 2
    assert all(
        "catalog?course=c1" in file.read_text(encoding="utf-8") for file in files
    )
    sender.assert_not_called()
