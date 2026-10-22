import base64
import json
import time
from pathlib import Path

import jwt
import pytest

from app import create_app
from app.api.errors import Forbidden
from app.api.services import update_grade

SECRET = "test-secret-for-local-pytest-only-0123456789abcdef"
PASSWORD = "Lms@2026"


# ==========================================
# CAU HINH PYTEST
# ==========================================


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "TOKEN_TTL_SECONDS": 900,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


# ==========================================
# CAC HAM HO TRO
# ==========================================


def login(client, email, password=PASSWORD):
    return client.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )


def token_for(client, email):
    response = login(client, email)

    assert response.status_code == 200, response.get_json()

    return response.get_json()["accessToken"]


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def assert_error(response, status, code):
    assert response.status_code == status
    assert response.get_json() == {"error": code}


def b64_json(data):
    content = json.dumps(data, separators=(",", ":")).encode("utf-8")

    return base64.urlsafe_b64encode(content).rstrip(b"=").decode("ascii")


# ==========================================
# A1 - DANG NHAP SAI
# ==========================================


def test_a1_invalid_login(client):
    unknown = login(client, "khongco@lms.test", "wrong")

    wrong = login(client, "chi.sv@lms.test", "wrong")

    assert_error(unknown, 401, "INVALID_CREDENTIALS")

    assert_error(wrong, 401, "INVALID_CREDENTIALS")

    assert unknown.get_data() == wrong.get_data()


# ==========================================
# A2 - THIEU TOKEN
# ==========================================


def test_a2_no_token(client):
    response = client.get("/me")

    assert_error(response, 401, "UNAUTHENTICATED")


# ==========================================
# A3 - GIA MAO JWT
# ==========================================


def test_a3_fake_jwt(client):
    token = token_for(client, "chi.sv@lms.test")

    head, _body, signature = token.split(".")

    payload = jwt.decode(token, options={"verify_signature": False})

    payload["sub"] = "u1"

    forged = ".".join((head, b64_json(payload), signature))

    response = client.get("/me", headers=headers(forged))

    assert_error(response, 401, "UNAUTHENTICATED")


# ==========================================
# A4 - THUAT TOAN NONE
# ==========================================


def test_a4_none_algorithm(client):
    now = int(time.time())

    unsigned = ".".join(
        (
            b64_json({"alg": "none", "typ": "JWT"}),
            b64_json({"sub": "u1", "iat": now, "exp": now + 900}),
            "",
        )
    )

    response = client.get("/me", headers=headers(unsigned))

    assert_error(response, 401, "UNAUTHENTICATED")


# ==========================================
# A5 - JWT HET HAN
# ==========================================


def test_a5_expired_token(tmp_path):
    test_app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "TOKEN_TTL_SECONDS": 1,
            "AUDIT_LOG_PATH": str(tmp_path / "expiry.log"),
        }
    )

    c = test_app.test_client()

    token = token_for(c, "chi.sv@lms.test")

    time.sleep(2)

    response = c.get("/me", headers=headers(token))

    assert_error(response, 401, "UNAUTHENTICATED")


# ==========================================
# A6 - KHONG LO MAT KHAU
# ==========================================


def test_a6_no_password_leak(client):
    admin = headers(token_for(client, "admin@lms.test"))

    teacher = headers(token_for(client, "an.gv@lms.test"))

    responses = [
        login(client, "chi.sv@lms.test"),
        client.get("/me", headers=admin),
        client.get("/courses/c1/grades", headers=admin),
        client.put("/courses/c1/grades/u4", json={"score": 9}, headers=teacher),
    ]

    for response in responses:
        assert response.status_code == 200

        data = json.dumps(response.get_json()).lower()

        assert "password" not in data
        assert "password_hash" not in data
        assert "passwordhash" not in data


# ==========================================
# A7 - SINH VIEN XEM DIEM CUA MINH
# ==========================================


def test_a7_student_view_own_grade(client):
    h = headers(token_for(client, "chi.sv@lms.test"))

    response = client.get("/courses/c1/grades", headers=h)

    assert response.status_code == 200

    assert response.get_json() == [{"studentId": "u4", "score": 7.5}]


# ==========================================
# A8 - SINH VIEN KHONG GHI DANH
# ==========================================


def test_a8_student_not_enrolled(client):
    h = headers(token_for(client, "chi.sv@lms.test"))

    response = client.get("/courses/c2/grades", headers=h)

    assert_error(response, 403, "FORBIDDEN")


# ==========================================
# A9 - SINH VIEN KHONG DUOC SUA DIEM
# ==========================================


def test_a9_student_cannot_update(client):
    h = headers(token_for(client, "chi.sv@lms.test"))

    response = client.put("/courses/c1/grades/u4", json={"score": 10}, headers=h)

    assert_error(response, 403, "FORBIDDEN")


# ==========================================
# A10 - GIANG VIEN KHAC KHONG DUOC SUA
# ==========================================


def test_a10_wrong_teacher(client):
    h = headers(token_for(client, "binh.gv@lms.test"))

    response = client.put("/courses/c1/grades/u4", json={"score": 0}, headers=h)

    assert_error(response, 403, "FORBIDDEN")


# ==========================================
# A11 - ADMIN KHONG DUOC SUA DIEM
# ==========================================


def test_a11_admin_cannot_update(client):
    h = headers(token_for(client, "admin@lms.test"))

    response = client.put("/courses/c1/grades/u4", json={"score": 10}, headers=h)

    assert_error(response, 403, "FORBIDDEN")


# ==========================================
# A12 - KIEM TRA DU LIEU DIEM
# ==========================================


@pytest.mark.parametrize(
    "body",
    [
        {"score": 11},
        {"score": -1},
        {"score": "10"},
        {"score": True},
        {"score": 9, "courseId": "c2"},
    ],
)
def test_a12_invalid_score(client, body):
    h = headers(token_for(client, "an.gv@lms.test"))

    response = client.put("/courses/c1/grades/u4", json=body, headers=h)

    assert_error(response, 400, "VALIDATION_ERROR")


# ==========================================
# A13 - SINH VIEN KHONG GHI DANH KHI SUA
# ==========================================


def test_a13_student_not_enrolled(client):
    h = headers(token_for(client, "an.gv@lms.test"))

    response = client.put("/courses/c1/grades/u6", json={"score": 5}, headers=h)

    assert_error(response, 404, "NOT_FOUND")


# ==========================================
# A14 - CAP NHAT DIEM THANH CONG
# ==========================================


def test_a14_update_grade(client):
    teacher = headers(token_for(client, "an.gv@lms.test"))

    student = headers(token_for(client, "chi.sv@lms.test"))

    response = client.put("/courses/c1/grades/u4", json={"score": 9}, headers=teacher)

    assert response.status_code == 200

    assert response.get_json() == {"courseId": "c1", "studentId": "u4", "score": 9}

    result = client.get("/courses/c1/grades", headers=student)

    assert result.status_code == 200

    assert result.get_json() == [{"studentId": "u4", "score": 9}]


# ==========================================
# A15 - GO BO DECORATOR VAN PHAI AN TOAN
# ==========================================


def test_a15_defense_in_depth(app, client):
    route = app.view_functions["edit_grade"]

    assert hasattr(route, "__wrapped__")

    # Mo phong viec go decorator
    app.view_functions["edit_grade"] = route.__wrapped__

    accounts = [
        ("chi.sv@lms.test", "u4", "STUDENT"),
        ("binh.gv@lms.test", "u3", "INSTRUCTOR"),
        ("admin@lms.test", "u1", "ADMIN"),
    ]

    store = app.extensions["lms_store"]

    for email, user_id, role in accounts:
        h = headers(token_for(client, email))

        response = client.put("/courses/c1/grades/u4", json={"score": 10}, headers=h)

        assert_error(response, 403, "FORBIDDEN")

        actor = {"id": user_id, "email": email, "role": role}

        with pytest.raises(Forbidden):
            update_grade(actor, "c1", "u4", 10, store=store)


# ==========================================
# A16 - ROUTE MOI PHAI DUOC BAO VE
# ==========================================


def test_a16_new_route(tmp_path):
    test_app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "AUDIT_LOG_PATH": str(tmp_path / "route_audit.log"),
        }
    )

    @test_app.get("/debug")
    def debug():
        return {"message": "not public"}

    response = test_app.test_client().get("/debug")

    assert_error(response, 401, "UNAUTHENTICATED")


# ==========================================
# A17 - THIEU JWT_SECRET
# ==========================================


def test_a17_missing_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError):
        create_app()


# ==========================================
# A18 - CHONG BRUTE FORCE
# ==========================================


def test_a18_account_lockout(client):
    for attempt in range(1, 6):
        response = login(client, "dung.sv@lms.test", "wrong-password")

        if attempt < 5:
            assert_error(response, 401, "INVALID_CREDENTIALS")

        else:
            assert_error(response, 429, "ACCOUNT_LOCKED")

    # Mat khau dung van bi khoa
    response = login(client, "dung.sv@lms.test", PASSWORD)

    assert_error(response, 429, "ACCOUNT_LOCKED")


# ==========================================
# A19 - AUDIT LOG
# ==========================================


def test_a19_audit_log(app, client):
    binh = headers(token_for(client, "binh.gv@lms.test"))

    an = headers(token_for(client, "an.gv@lms.test"))

    denied = client.put("/courses/c1/grades/u4", json={"score": 0}, headers=binh)

    assert_error(denied, 403, "FORBIDDEN")

    success = client.put("/courses/c1/grades/u4", json={"score": 9}, headers=an)

    assert success.status_code == 200

    path = Path(app.config["AUDIT_LOG_PATH"])

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert len(lines) == 2

    denied_log, success_log = lines

    assert denied_log["actorId"] == "u3"
    assert denied_log["result"] == "DENIED"

    assert success_log["actorId"] == "u2"
    assert success_log["result"] == "SUCCESS"

    assert success_log["oldScore"] == 7.5
    assert success_log["newScore"] == 9

    for item in lines:
        for key in ("ts", "actorId", "action", "resource", "result"):
            assert key in item

    raw = path.read_text(encoding="utf-8").lower()

    assert "password" not in raw
    assert "token" not in raw


# ==========================================
# BONUS 1 - LOI 404 VA 405 TRA JSON
# ==========================================


def test_json_error_responses(client):
    h = headers(token_for(client, "chi.sv@lms.test"))

    response = client.get("/missing-route", headers=h)

    assert_error(response, 404, "NOT_FOUND")

    response = client.post("/me", headers=h)

    assert response.status_code == 405
    assert isinstance(response.get_json(), dict)
    assert set(response.get_json()) == {"error"}


# ==========================================
# BONUS 2 - STATE CUA HAI APP DOC LAP
# ==========================================


def test_independent_app_state(tmp_path):
    config = {
        "TESTING": True,
        "JWT_SECRET": SECRET,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    }

    app1 = create_app(config)
    app2 = create_app(config)

    store1 = app1.extensions["lms_store"]
    store2 = app2.extensions["lms_store"]

    assert store1 is not store2

    store1["enrollments"][0]["score"] = 2

    assert store2["enrollments"][0]["score"] == 7.5

    store1["failed_logins"]["fake@example.com"] = {"count": 5}

    assert store2["failed_logins"] == {}


# ==========================================
# BONUS 3 - THU TU KIEM TRA LOI
# ==========================================


def test_error_checking_order(client):
    teacher = headers(token_for(client, "an.gv@lms.test"))

    student = headers(token_for(client, "chi.sv@lms.test"))

    # 401 truoc 404
    assert_error(
        client.put("/courses/unknown/grades/u4", json={"score": 11}),
        401,
        "UNAUTHENTICATED",
    )

    # 404 mon hoc truoc 403
    assert_error(
        client.put("/courses/unknown/grades/u4", json={"score": 11}, headers=student),
        404,
        "NOT_FOUND",
    )

    # 403 truoc 400
    assert_error(
        client.put("/courses/c1/grades/u4", json={"score": 11}, headers=student),
        403,
        "FORBIDDEN",
    )

    # 400 truoc 404 ghi danh
    assert_error(
        client.put("/courses/c1/grades/u6", json={"score": 11}, headers=teacher),
        400,
        "VALIDATION_ERROR",
    )

    assert_error(
        client.put("/courses/c1/grades/u6", json={"score": 5}, headers=teacher),
        404,
        "NOT_FOUND",
    )


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_optional_extensions_work_with_store_backends(tmp_path, backend):
    config = {
        "TESTING": True,
        "JWT_SECRET": SECRET,
        "AUDIT_LOG_PATH": str(tmp_path / f"{backend}.log"),
        "ENABLE_EXTENSIONS": True,
        "RESET_TOKEN_ECHO": True,
        "BCRYPT_ROUNDS": 4,
        "LMS_STORE": backend,
        "SQLITE_PATH": str(tmp_path / f"{backend}.sqlite3"),
    }
    test_app = create_app(config)
    client = test_app.test_client()

    assert client.get("/").status_code == 200
    assert client.get("/account").status_code == 200

    teacher_token = token_for(client, "an.gv@lms.test")
    grade = client.put(
        "/courses/c1/grades/u4",
        json={"score": 9},
        headers=headers(teacher_token),
    )
    assert grade.status_code == 200

    registration = client.post(
        "/auth/register",
        json={"email": "new@lms.test", "password": "ValidPass123"},
    )
    assert registration.status_code == 201

    forgot = client.post(
        "/auth/forgot-password",
        json={"email": "new@lms.test"},
    )
    assert forgot.status_code == 202
    reset_token = forgot.get_json()["resetToken"]

    reset = client.post(
        "/auth/reset-password",
        json={"token": reset_token, "password": "ChangedPass123"},
    )
    assert reset.status_code == 200

    new_login = login(client, "new@lms.test", "ChangedPass123")
    assert new_login.status_code == 200
