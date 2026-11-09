import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "dashboard-tests-secret-at-least-32-characters",
            "BCRYPT_ROUNDS": 4,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "SUBMISSION_UPLOAD_DIR": str(tmp_path / "submissions"),
            "SMTP_ENABLED": False,
        }
    ).test_client()


def auth(client, email):
    result = client.post("/auth/login", json={"email": email, "password": "Lms@2026"})
    assert result.status_code == 200
    return {"Authorization": "Bearer " + result.json["accessToken"]}


@pytest.mark.parametrize(
    "email,role,ids",
    [
        ("admin@lms.test", "ADMIN", {"c1", "c2"}),
        ("an.gv@lms.test", "INSTRUCTOR", {"c1"}),
        ("chi.sv@lms.test", "STUDENT", {"c1"}),
    ],
)
def test_role_dashboard_scope(client, email, role, ids):
    assert client.get("/api/dashboard").status_code == 401
    result = client.get("/api/dashboard", headers=auth(client, email))
    assert result.status_code == 200
    assert result.json["user"]["role"] == role
    assert {item["id"] for item in result.json["courses"]} == ids
    assert result.json["counts"]["courses"] == len(ids)
    assert result.headers["Cache-Control"] == "private, no-store"
    if role == "ADMIN":
        assert result.json["counts"]["users"] == 6
        assert result.json["counts"]["instructors"] == 2
    else:
        assert result.json["activity"] == []
        assert "users" not in result.json["counts"]


def test_dashboard_pending_and_grading_counts(client):
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    due = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    result = client.post(
        "/courses/c1/assignments",
        headers=teacher,
        json={"title": "Bài thực hành", "description": "Nộp bài", "dueAt": due},
    )
    assignment = result.json["id"]
    student_data = client.get("/api/dashboard", headers=student).json
    assert student_data["counts"]["pending"] == 1
    assert student_data["deadlines"][0]["id"] == assignment
    assert (
        client.post(
            f"/courses/c1/assignments/{assignment}/submissions",
            headers={**student, "Idempotency-Key": str(uuid.uuid4())},
            data={"file": (io.BytesIO(b"Homework"), "work.txt")},
        ).status_code
        == 201
    )
    student_data = client.get("/api/dashboard", headers=student).json
    assert student_data["counts"]["pending"] == 0
    assert student_data["counts"]["submissions"] == 1
    assert client.get("/api/dashboard", headers=teacher).json["counts"]["grading"] == 1


def test_dashboard_empty_and_removed_enrollment(client):
    student = auth(client, "chi.sv@lms.test")
    teacher = auth(client, "an.gv@lms.test")
    client.delete("/courses/c1/enrollments/u4", headers=teacher)
    result = client.get("/api/dashboard", headers=student).json
    assert result["courses"] == []
    assert result["deadlines"] == []
    assert result["announcements"] == []
    assert result["counts"]["courses"] == 0
