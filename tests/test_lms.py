import base64
import hashlib
import json
import sqlite3
import time
from pathlib import Path

import jwt
import pytest

from app import create_app
from app.api.errors import Forbidden
from app.api.services import update_grade

SECRET = "test-secret-for-local-pytest-only-0123456789abcdef"
PASSWORD = "Lms@2026"


@pytest.fixture(autouse=True)
def isolate_rate_limit_database(tmp_path, monkeypatch):
    """Give each test its own rate-limit SQLite database."""
    monkeypatch.setenv(
        "RATE_LIMIT_DB_PATH",
        str(tmp_path / "rate_limits.sqlite3"),
    )


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
    """Repeated wrong passwords must not hard-lock an account."""

    for _ in range(5):
        response = login(
            client,
            "dung.sv@lms.test",
            "wrong-password",
        )
        assert_error(response, 401, "INVALID_CREDENTIALS")


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


# ==========================================
# JWT TOKEN VERSIONING - MEMORY AND SQLITE
# ==========================================


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_password_reset_revokes_old_jwt(tmp_path, backend):
    config = {
        "TESTING": True,
        "JWT_SECRET": SECRET,
        "AUDIT_LOG_PATH": str(tmp_path / f"revocation_{backend}.log"),
        "ENABLE_EXTENSIONS": True,
        "RESET_TOKEN_ECHO": True,
        "BCRYPT_ROUNDS": 4,
        "LMS_STORE": backend,
        "SQLITE_PATH": str(tmp_path / f"revocation_{backend}.sqlite3"),
    }

    test_app = create_app(config)
    client = test_app.test_client()

    email = "revocation@lms.test"
    original_password = "OriginalPass123"
    new_password = "ChangedPass123"

    registration = client.post(
        "/auth/register",
        json={"email": email, "password": original_password},
    )
    assert registration.status_code == 201

    initial_login = login(client, email, original_password)
    assert initial_login.status_code == 200

    old_token = initial_login.get_json()["accessToken"]
    old_claims = jwt.decode(
        old_token,
        SECRET,
        algorithms=["HS256"],
    )

    assert old_claims["ver"] == 0
    assert client.get("/me", headers=headers(old_token)).status_code == 200

    forgot = client.post(
        "/auth/forgot-password",
        json={"email": email},
    )
    assert forgot.status_code == 202

    reset_token = forgot.get_json()["resetToken"]

    reset = client.post(
        "/auth/reset-password",
        json={
            "token": reset_token,
            "password": new_password,
        },
    )
    assert reset.status_code == 200

    # JWT cu phai bi vo hieu hoa.
    assert_error(
        client.get("/me", headers=headers(old_token)),
        401,
        "UNAUTHENTICATED",
    )

    # Mat khau cu khong con hop le.
    assert_error(
        login(client, email, original_password),
        401,
        "INVALID_CREDENTIALS",
    )

    # Dang nhap bang mat khau moi.
    new_login = login(client, email, new_password)
    assert new_login.status_code == 200

    new_token = new_login.get_json()["accessToken"]
    new_claims = jwt.decode(
        new_token,
        SECRET,
        algorithms=["HS256"],
    )

    assert new_claims["ver"] == old_claims["ver"] + 1

    assert client.get("/me", headers=headers(new_token)).status_code == 200

    # Reset token chi duoc su dung mot lan.
    reused = client.post(
        "/auth/reset-password",
        json={
            "token": reset_token,
            "password": "AnotherPass123",
        },
    )
    assert reused.status_code == 400


# ==========================================
# RATE LIMITING - PASSWORD RESET
# ==========================================


def rate_limit_client(tmp_path, backend, suffix):
    """Create an isolated Flask app for rate-limit tests."""
    config = {
        "TESTING": True,
        "JWT_SECRET": SECRET,
        "AUDIT_LOG_PATH": str(tmp_path / f"rate_{backend}_{suffix}.log"),
        "ENABLE_EXTENSIONS": True,
        "RESET_TOKEN_ECHO": True,
        "BCRYPT_ROUNDS": 4,
        "LMS_STORE": backend,
        "SQLITE_PATH": str(tmp_path / f"rate_{backend}_{suffix}.sqlite3"),
    }
    return create_app(config).test_client()


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_forgot_password_email_rate_limit(tmp_path, backend):
    c = rate_limit_client(tmp_path, backend, "email")
    email = "chi.sv@lms.test"

    for _ in range(3):
        response = c.post("/auth/forgot-password", json={"email": email})
        assert response.status_code == 202

    response = c.post("/auth/forgot-password", json={"email": email})
    assert_error(response, 429, "RATE_LIMITED")
    assert response.headers.get("Retry-After") == "900"

    # A different email is still allowed from this IP.
    response = c.post("/auth/forgot-password", json={"email": "another@lms.test"})
    assert response.status_code == 202
    assert response.get_json() == {"status": "sent"}


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_forgot_password_ip_rate_limit(tmp_path, backend):
    c = rate_limit_client(tmp_path, backend, "ip")

    for i in range(10):
        response = c.post(
            "/auth/forgot-password", json={"email": f"unknown{i}@lms.test"}
        )
        assert response.status_code == 202
        assert response.get_json() == {"status": "sent"}

    response = c.post("/auth/forgot-password", json={"email": "unknown10@lms.test"})
    assert_error(response, 429, "RATE_LIMITED")


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_reset_password_ip_rate_limit(tmp_path, backend):
    c = rate_limit_client(tmp_path, backend, "reset")

    for _ in range(5):
        response = c.post(
            "/auth/reset-password",
            json={"token": "invalid-reset-token", "password": "NewPass123"},
        )
        assert_error(response, 400, "VALIDATION_ERROR")

    response = c.post(
        "/auth/reset-password",
        json={"token": "invalid-reset-token", "password": "NewPass123"},
    )
    assert_error(response, 429, "RATE_LIMITED")
    assert response.headers.get("Retry-After") == "900"


# ==========================================
# APP ISOLATION AND RATE-LIMIT MEMORY CLEANUP
# ==========================================


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_rate_limit_shared_between_apps(tmp_path, backend):
    first = rate_limit_client(
        tmp_path,
        backend,
        "shared_first",
    )
    second = rate_limit_client(
        tmp_path,
        backend,
        "shared_second",
    )

    email = "shared@lms.test"

    for _ in range(3):
        response = first.post(
            "/auth/forgot-password",
            json={"email": email},
        )
        assert response.status_code == 202

    # The second Flask app must observe the same limit.
    response = second.post(
        "/auth/forgot-password",
        json={"email": email},
    )

    assert_error(response, 429, "RATE_LIMITED")
    assert int(response.headers["Retry-After"]) > 0


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_rate_limit_expired_keys_are_cleaned_up(tmp_path, backend, monkeypatch):
    import sqlite3

    import app.api.rate_limit as rate_limit_module

    clock = [1000.0]
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: clock[0])

    c = rate_limit_client(tmp_path, backend, "cleanup")

    for i in range(20):
        response = c.post(
            "/auth/forgot-password",
            json={"email": f"cleanup{i}@lms.test"},
            environ_overrides={"REMOTE_ADDR": f"192.0.2.{i + 1}"},
        )
        assert response.status_code == 202

    db_path = c.application.config["RATE_LIMIT_DB_PATH"]

    with sqlite3.connect(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM rate_limits").fetchone()[0]

    assert before > 0

    # Advance beyond the 15-minute window.
    clock[0] += 901

    response = c.post(
        "/auth/forgot-password",
        json={"email": "after-cleanup@lms.test"},
    )
    assert response.status_code == 202

    with sqlite3.connect(db_path) as conn:
        expired = conn.execute(
            "SELECT COUNT(*) FROM rate_limits WHERE expires_at <= ?",
            (clock[0],),
        ).fetchone()[0]

    assert expired == 0


# ==========================================
# HASHED RESET TOKEN - MEMORY AND SQLITE
# ==========================================


def hashed_token_client(tmp_path, backend, suffix):
    config = {
        "TESTING": True,
        "JWT_SECRET": SECRET,
        "AUDIT_LOG_PATH": str(tmp_path / f"hashed_{backend}_{suffix}.log"),
        "ENABLE_EXTENSIONS": True,
        "RESET_TOKEN_ECHO": True,  # Test-only: expose token to test client.
        "RESET_TOKEN_TTL_SECONDS": 900,
        "BCRYPT_ROUNDS": 4,
        "LMS_STORE": backend,
        "SQLITE_PATH": str(tmp_path / f"hashed_{backend}_{suffix}.sqlite3"),
    }
    test_app = create_app(config)
    return test_app, test_app.test_client()


def issue_reset_token(client):
    response = client.post("/auth/forgot-password", json={"email": "chi.sv@lms.test"})
    assert response.status_code == 202
    return response.get_json()["resetToken"]


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_reset_token_only_hash_is_stored(tmp_path, backend):
    test_app, client = hashed_token_client(tmp_path, backend, "storage")
    token = issue_reset_token(client)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()

    if backend == "memory":
        records = test_app.extensions["lms_reset_tokens"]
        assert token not in records
        assert digest in records
        assert len(records) == 1
    else:
        with sqlite3.connect(test_app.config["SQLITE_PATH"]) as conn:
            stored = [row[0] for row in conn.execute("SELECT token FROM reset_tokens")]
        assert token not in stored
        assert stored == [digest]

    assert token != digest
    assert len(digest) == 64


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_hashed_reset_token_is_one_time(tmp_path, backend):
    _, client = hashed_token_client(tmp_path, backend, "one_time")
    token = issue_reset_token(client)
    payload = {"token": token, "password": "ChangedPass123"}

    first = client.post("/auth/reset-password", json=payload)
    assert first.status_code == 200
    assert login(client, "chi.sv@lms.test", "ChangedPass123").status_code == 200

    second = client.post("/auth/reset-password", json=payload)
    assert_error(second, 400, "VALIDATION_ERROR")


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_hashed_reset_token_expiry(tmp_path, backend, monkeypatch):
    import app.api.reset as reset_module

    _, client = hashed_token_client(tmp_path, backend, "expired")
    token = issue_reset_token(client)
    # Advance wall-clock time without waiting 15 minutes.
    now = time.time()
    monkeypatch.setattr(reset_module.time, "time", lambda: now + 901)

    expired = client.post(
        "/auth/reset-password",
        json={"token": token, "password": "ChangedPass123"},
    )
    assert_error(expired, 400, "VALIDATION_ERROR")
    assert login(client, "chi.sv@lms.test", PASSWORD).status_code == 200


# ==========================================
# SERVER-SIDE JWT LOGOUT
# ==========================================


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_logout_revokes_only_current_jwt(tmp_path, backend):
    config = {
        "TESTING": True,
        "JWT_SECRET": SECRET,
        "AUDIT_LOG_PATH": str(tmp_path / f"logout_{backend}.log"),
        "LMS_STORE": backend,
        "SQLITE_PATH": str(tmp_path / f"logout_{backend}.sqlite3"),
        "BCRYPT_ROUNDS": 4,
    }
    test_app = create_app(config)
    c = test_app.test_client()
    first = token_for(c, "chi.sv@lms.test")
    second = token_for(c, "chi.sv@lms.test")
    assert first != second
    assert c.get("/me", headers=headers(first)).status_code == 200
    assert c.post("/auth/logout", headers=headers(first)).get_json() == {
        "status": "logged_out"
    }
    assert_error(c.get("/me", headers=headers(first)), 401, "UNAUTHENTICATED")
    assert_error(c.post("/auth/logout", headers=headers(first)), 401, "UNAUTHENTICATED")
    assert c.get("/me", headers=headers(second)).status_code == 200


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_logout_requires_authentication(tmp_path, backend):
    c = rate_limit_client(tmp_path, backend, "logout_no_auth")
    assert_error(c.post("/auth/logout"), 401, "UNAUTHENTICATED")


def test_sqlite_logout_survives_app_restart(tmp_path):
    config = {
        "TESTING": True,
        "JWT_SECRET": SECRET,
        "AUDIT_LOG_PATH": str(tmp_path / "logout_restart.log"),
        "LMS_STORE": "sqlite",
        "SQLITE_PATH": str(tmp_path / "logout_restart.sqlite3"),
        "BCRYPT_ROUNDS": 4,
    }
    first_app = create_app(config)
    c = first_app.test_client()
    token = token_for(c, "chi.sv@lms.test")
    assert c.post("/auth/logout", headers=headers(token)).status_code == 200
    second_app = create_app(config)
    assert_error(
        second_app.test_client().get("/me", headers=headers(token)),
        401,
        "UNAUTHENTICATED",
    )


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_rate_limit_window_expires(tmp_path, backend, monkeypatch):
    import app.api.rate_limit as rate_limit_module

    clock = [1000.0]
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: clock[0])

    c = rate_limit_client(tmp_path, backend, "expiry")
    email = "expiring@lms.test"

    for _ in range(3):
        response = c.post(
            "/auth/forgot-password",
            json={"email": email},
        )
        assert response.status_code == 202

    assert_error(
        c.post("/auth/forgot-password", json={"email": email}),
        429,
        "RATE_LIMITED",
    )

    clock[0] += 901

    response = c.post(
        "/auth/forgot-password",
        json={"email": email},
    )
    assert response.status_code == 202


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_account_lockout_dos_prevention(tmp_path, backend):
    """A valid user can log in after repeated incorrect attempts."""

    c = rate_limit_client(
        tmp_path,
        backend,
        "account_lockout_dos",
    )

    email = "sec03-test@lms.test"
    password = "SecurePassword123!"

    # Create a test account.
    register_response = c.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
        },
    )

    assert register_response.status_code in (200, 201)

    # Simulate five failed login attempts.
    for _ in range(5):
        response = c.post(
            "/auth/login",
            json={
                "email": email,
                "password": "wrong-password",
            },
        )

        assert_error(
            response,
            401,
            "INVALID_CREDENTIALS",
        )

    # Correct credentials must still work.
    response = c.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 200
    assert "accessToken" in response.get_json()


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec04_duplicate_registration(tmp_path, backend):
    """Prevent duplicate account registration."""

    c = rate_limit_client(tmp_path, backend, "sec04_duplicate")

    payload = {
        "email": "sec04-duplicate@lms.test",
        "password": "SecurePassword123!",
    }

    first = c.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = c.post("/auth/register", json=payload)
    assert_error(second, 400, "VALIDATION_ERROR")


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec04_concurrent_registration(tmp_path, backend):
    """Concurrent registrations must not create duplicate accounts."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "ENABLE_EXTENSIONS": True,
            "BCRYPT_ROUNDS": 4,
            "LMS_STORE": backend,
            "SQLITE_PATH": str(tmp_path / f"sec04_concurrent_{backend}.sqlite3"),
            "AUDIT_LOG_PATH": str(tmp_path / f"sec04_concurrent_{backend}.log"),
        }
    )

    # Two different IPs avoid exhausting the shared registration limit.
    barrier = Barrier(2)

    def register_user(index):
        with app.test_client() as client:
            barrier.wait(timeout=10)
            response = client.post(
                "/auth/register",
                json={
                    "email": "sec04-race@lms.test",
                    "password": "SecurePassword123!",
                },
                environ_overrides={"REMOTE_ADDR": f"192.0.2.{index + 1}"},
            )
            return response.status_code, response.get_json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register_user, range(2)))

    statuses = sorted(status for status, _ in results)

    assert statuses == [201, 400], results

    store = app.extensions["lms_store"]

    if isinstance(store, dict):
        users = [
            user
            for user in store["users"].values()
            if user["email"] == "sec04-race@lms.test"
        ]
        assert len(users) == 1
    else:
        assert store.find_user_by_email("sec04-race@lms.test") is not None


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec04_registration_rate_limit(tmp_path, backend):
    """Sixth registration request from the same IP must be blocked."""

    c = rate_limit_client(tmp_path, backend, "sec04_rate_limit")

    for index in range(5):
        response = c.post(
            "/auth/register",
            json={
                "email": f"sec04-limit-{index}@lms.test",
                "password": "SecurePassword123!",
            },
        )
        assert response.status_code == 201

    response = c.post(
        "/auth/register",
        json={
            "email": "sec04-limit-6@lms.test",
            "password": "SecurePassword123!",
        },
    )

    assert_error(response, 429, "RATE_LIMITED")
    assert int(response.headers["Retry-After"]) > 0


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec04_prevent_admin_registration(tmp_path, backend):
    """Users must not assign themselves an ADMIN role."""

    c = rate_limit_client(tmp_path, backend, "sec04_admin")

    response = c.post(
        "/auth/register",
        json={
            "email": "sec04-admin@lms.test",
            "password": "SecurePassword123!",
            "role": "ADMIN",
        },
    )

    assert_error(response, 400, "VALIDATION_ERROR")


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec04_concurrent_unique_accounts(tmp_path, backend):
    """Concurrent registrations must create unique user IDs."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "ENABLE_EXTENSIONS": True,
            "BCRYPT_ROUNDS": 4,
            "LMS_STORE": backend,
            "SQLITE_PATH": str(tmp_path / f"sec04_unique_{backend}.sqlite3"),
            "AUDIT_LOG_PATH": str(tmp_path / f"sec04_unique_{backend}.log"),
        }
    )

    count = 5
    barrier = Barrier(count)

    def register_user(index):
        with app.test_client() as client:
            barrier.wait(timeout=15)
            response = client.post(
                "/auth/register",
                json={
                    "email": f"sec04-unique-{index}@lms.test",
                    "password": "SecurePassword123!",
                },
                environ_overrides={
                    "REMOTE_ADDR": f"192.0.2.{index + 1}",
                },
            )
            return response.status_code, response.get_json()

    with ThreadPoolExecutor(max_workers=count) as executor:
        results = list(executor.map(register_user, range(count)))

    assert all(status == 201 for status, _ in results), results

    user_ids = [body["id"] for _, body in results]

    assert len(user_ids) == count
    assert len(set(user_ids)) == count


# ============================================================
# SEC-05: ATOMIC PASSWORD RESET
# ============================================================


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec05_reset_success(tmp_path, backend):
    """Successful reset must update password and consume token."""
    import hashlib

    import bcrypt

    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "BCRYPT_ROUNDS": 4,
            "LMS_STORE": backend,
            "SQLITE_PATH": str(tmp_path / f"sec05_success_{backend}.sqlite3"),
            "AUDIT_LOG_PATH": str(tmp_path / f"sec05_success_{backend}.log"),
            "RATE_LIMIT_DB_PATH": str(
                tmp_path / f"sec05_success_{backend}_rate.sqlite3"
            ),
        }
    )

    store = app.extensions["lms_store"]

    if isinstance(store, dict):
        user = next(iter(store["users"].values()))
        user_id = user["id"]
        old_hash = user["password_hash"]
        old_version = user["token_version"]
    else:
        with store._connect() as conn:
            row = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
        user_id = row["id"]
        old_hash = row["password_hash"]
        old_version = row["token_version"]

    token = "sec05-success-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    if isinstance(store, dict):
        import time

        app.extensions["lms_reset_tokens"][token_hash] = (user_id, time.time() + 900)
    else:
        store.add_reset_token(token_hash, user_id, 900)

    with app.test_client() as client:
        response = client.post(
            "/auth/reset-password",
            json={"token": token, "password": "NewSecurePassword123!"},
        )

    assert response.status_code == 200, response.get_json()

    if isinstance(store, dict):
        updated = store["users"][user_id]
        assert updated["token_version"] == old_version + 1
        assert updated["password_hash"] != old_hash
        assert token_hash not in app.extensions["lms_reset_tokens"]
    else:
        updated = store.get_user(user_id)
        assert updated.token_version == old_version + 1
        assert updated.password_hash != old_hash

        with store._connect() as conn:
            remaining = conn.execute(
                "SELECT 1 FROM reset_tokens WHERE token = ?",
                (token_hash,),
            ).fetchone()

        assert remaining is None

    # This section runs for BOTH Memory and SQLite.
    stored_hash = (
        updated["password_hash"] if isinstance(updated, dict) else updated.password_hash
    )

    assert bcrypt.checkpw(
        b"NewSecurePassword123!",
        stored_hash.encode("utf-8"),
    )


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec05_hash_failure_keeps_token(tmp_path, backend, monkeypatch):
    """Hashing failure must not consume the reset token."""
    import hashlib
    import time

    import app.api.reset as reset_module

    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "BCRYPT_ROUNDS": 4,
            "LMS_STORE": backend,
            "SQLITE_PATH": str(tmp_path / f"sec05_hash_{backend}.sqlite3"),
            "RATE_LIMIT_DB_PATH": str(tmp_path / f"sec05_hash_{backend}_rate.sqlite3"),
        }
    )
    store = app.extensions["lms_store"]

    if isinstance(store, dict):
        user = next(iter(store["users"].values()))
        user_id = user["id"]
        old_hash = user["password_hash"]
    else:
        with store._connect() as conn:
            row = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
        user_id = row["id"]
        old_hash = row["password_hash"]

    token = "sec05-hash-failure-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    if isinstance(store, dict):
        app.extensions["lms_reset_tokens"][token_hash] = (
            user_id,
            time.time() + 900,
        )
    else:
        store.add_reset_token(token_hash, user_id, 900)

    def fail_hash(*args, **kwargs):
        raise RuntimeError("Simulated bcrypt failure")

    monkeypatch.setattr(reset_module, "hash_password", fail_hash)

    # Flask converts the simulated exception into HTTP 500.
    with app.test_client() as client:
        response = client.post(
            "/auth/reset-password",
            json={
                "token": token,
                "password": "NewSecurePassword123!",
            },
        )

    assert response.status_code == 500

    # Verify token and password remain unchanged.
    if isinstance(store, dict):
        assert token_hash in app.extensions["lms_reset_tokens"]
        assert store["users"][user_id]["password_hash"] == old_hash
    else:
        with store._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM reset_tokens WHERE token = ?",
                (token_hash,),
            ).fetchone()

        assert row is not None
        assert store.get_user(user_id).password_hash == old_hash


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec05_token_cannot_be_reused(tmp_path, backend):
    """A successfully consumed token cannot reset password twice."""
    import hashlib
    import time

    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "BCRYPT_ROUNDS": 4,
            "LMS_STORE": backend,
            "SQLITE_PATH": str(tmp_path / f"sec05_reuse_{backend}.sqlite3"),
            "RATE_LIMIT_DB_PATH": str(tmp_path / f"sec05_reuse_{backend}_rate.sqlite3"),
        }
    )
    store = app.extensions["lms_store"]

    if isinstance(store, dict):
        user_id = next(iter(store["users"]))
    else:
        with store._connect() as conn:
            user_id = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]

    token = "sec05-reuse-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    if isinstance(store, dict):
        app.extensions["lms_reset_tokens"][token_hash] = (user_id, time.time() + 900)
    else:
        store.add_reset_token(token_hash, user_id, 900)

    with app.test_client() as client:
        first = client.post(
            "/auth/reset-password",
            json={"token": token, "password": "FirstSecurePassword123!"},
        )
        second = client.post(
            "/auth/reset-password",
            json={"token": token, "password": "SecondSecurePassword123!"},
        )

    assert first.status_code == 200
    assert_error(second, 400, "VALIDATION_ERROR")


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec05_concurrent_reset(tmp_path, backend):
    """Only one concurrent request may consume a reset token."""
    import hashlib
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "BCRYPT_ROUNDS": 4,
            "LMS_STORE": backend,
            "SQLITE_PATH": str(tmp_path / f"sec05_race_{backend}.sqlite3"),
            "RATE_LIMIT_DB_PATH": str(tmp_path / f"sec05_race_{backend}_rate.sqlite3"),
        }
    )
    store = app.extensions["lms_store"]

    if isinstance(store, dict):
        user_id = next(iter(store["users"]))
    else:
        with store._connect() as conn:
            user_id = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]

    token = "sec05-concurrent-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    if isinstance(store, dict):
        app.extensions["lms_reset_tokens"][token_hash] = (user_id, time.time() + 900)
    else:
        store.add_reset_token(token_hash, user_id, 900)

    barrier = Barrier(2)

    def reset_worker(index):
        with app.test_client() as client:
            barrier.wait(timeout=10)
            response = client.post(
                "/auth/reset-password",
                json={"token": token, "password": "NewSecurePassword123!"},
                environ_overrides={"REMOTE_ADDR": f"192.0.2.{index + 1}"},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(reset_worker, range(2)))

    assert statuses == [200, 400], statuses


def test_sec05_sqlite_rollback_on_token_delete_failure(tmp_path):
    """SQLite must roll back password update if token deletion fails."""
    import hashlib
    import sqlite3

    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "BCRYPT_ROUNDS": 4,
            "LMS_STORE": "sqlite",
            "SQLITE_PATH": str(tmp_path / "sec05_rollback.sqlite3"),
            "RATE_LIMIT_DB_PATH": str(tmp_path / "sec05_rollback_rate.sqlite3"),
            "AUDIT_LOG_PATH": str(tmp_path / "sec05_rollback.log"),
        }
    )

    store = app.extensions["lms_store"]

    # 1. Select a user and save original credentials.
    with store._connect() as conn:
        user = conn.execute(
            "SELECT id, password_hash, token_version FROM users LIMIT 1"
        ).fetchone()

    assert user is not None

    user_id = user["id"]
    old_hash = user["password_hash"]
    old_version = user["token_version"]

    # 2. Create a valid password reset token.
    token = "sec05-rollback-test-token"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    store.add_reset_token(token_hash, user_id, 900)

    # 3. Simulate a SQLite failure during token deletion.
    with sqlite3.connect(app.config["SQLITE_PATH"]) as conn:
        conn.execute(
            """
            CREATE TRIGGER sec05_fail_token_delete
            BEFORE DELETE ON reset_tokens
            BEGIN
                SELECT RAISE(ABORT, 'Simulated token deletion failure');
            END;
            """
        )

    # 4. Attempt password reset.
    with app.test_client() as client:
        response = client.post(
            "/auth/reset-password",
            json={
                "token": token,
                "password": "NewSecurePassword123!",
            },
            environ_overrides={"REMOTE_ADDR": "192.0.2.55"},
        )

    assert response.status_code == 500

    # 5. Verify that the entire transaction was rolled back.
    with store._connect() as conn:
        updated_user = conn.execute(
            """
            SELECT password_hash, token_version
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

        remaining_token = conn.execute(
            "SELECT token FROM reset_tokens WHERE token = ?",
            (token_hash,),
        ).fetchone()

    assert updated_user is not None

    # Password must remain unchanged.
    assert updated_user["password_hash"] == old_hash

    # JWT token version must remain unchanged.
    assert updated_user["token_version"] == old_version

    # Reset token must still exist.
    assert remaining_token is not None

    # 6. Remove simulated database failure.
    with sqlite3.connect(app.config["SQLITE_PATH"]) as conn:
        conn.execute("DROP TRIGGER sec05_fail_token_delete")

    # 7. Retry with the same token after database recovery.
    with app.test_client() as client:
        retry = client.post(
            "/auth/reset-password",
            json={
                "token": token,
                "password": "NewSecurePassword123!",
            },
            environ_overrides={"REMOTE_ADDR": "192.0.2.56"},
        )

    assert retry.status_code == 200, retry.get_json()

    # 8. Verify successful update and token consumption.
    with store._connect() as conn:
        final_user = conn.execute(
            """
            SELECT password_hash, token_version
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

        final_token = conn.execute(
            "SELECT token FROM reset_tokens WHERE token = ?",
            (token_hash,),
        ).fetchone()

    assert final_user["password_hash"] != old_hash
    assert final_user["token_version"] == old_version + 1
    assert final_token is None


# ============================================================
# SEC-06: FORGOT-PASSWORD ACCOUNT ENUMERATION
# ============================================================


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec06_generic_forgot_response(tmp_path, backend):
    """Existing and unknown emails must receive the same response."""
    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "BCRYPT_ROUNDS": 4,
            "LMS_STORE": backend,
            "RESET_TOKEN_ECHO": False,
            "SQLITE_PATH": str(tmp_path / f"sec06_generic_{backend}.sqlite3"),
            "RATE_LIMIT_DB_PATH": str(
                tmp_path / f"sec06_generic_{backend}_rate.sqlite3"
            ),
        }
    )

    store = app.extensions["lms_store"]

    if isinstance(store, dict):
        existing_email = next(iter(store["users"].values()))["email"]
    else:
        with store._connect() as conn:
            existing_email = conn.execute("SELECT email FROM users LIMIT 1").fetchone()[
                "email"
            ]

    with app.test_client() as client:
        existing = client.post(
            "/auth/forgot-password",
            json={"email": existing_email},
        )

        unknown = client.post(
            "/auth/forgot-password",
            json={"email": "sec06-unknown@example.com"},
        )

    assert existing.status_code == 202
    assert unknown.status_code == 202
    assert existing.get_json() == unknown.get_json()
    assert existing.get_json() == {"status": "sent"}


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec06_equal_email_rate_limits(tmp_path, backend):
    """Existing and unknown emails must share the same rate-limit policy."""
    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "BCRYPT_ROUNDS": 4,
            "LMS_STORE": backend,
            "RESET_TOKEN_ECHO": False,
            "SQLITE_PATH": str(tmp_path / f"sec06_limit_{backend}.sqlite3"),
            "RATE_LIMIT_DB_PATH": str(tmp_path / f"sec06_limit_{backend}_rate.sqlite3"),
        }
    )

    store = app.extensions["lms_store"]

    if isinstance(store, dict):
        existing_email = next(iter(store["users"].values()))["email"]
    else:
        with store._connect() as conn:
            existing_email = conn.execute("SELECT email FROM users LIMIT 1").fetchone()[
                "email"
            ]

    emails = [
        existing_email,
        "sec06-unknown@example.com",
    ]

    with app.test_client() as client:
        for index, email in enumerate(emails):
            statuses = []

            for _ in range(4):
                response = client.post(
                    "/auth/forgot-password",
                    json={"email": email},
                    environ_overrides={"REMOTE_ADDR": f"192.0.2.{index + 10}"},
                )

                statuses.append(response.status_code)

            assert statuses == [202, 202, 202, 429]
            assert response.get_json() == {"error": "RATE_LIMITED"}
            assert int(response.headers["Retry-After"]) > 0


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_sec06_no_token_echo_in_production(tmp_path, backend):
    """Production responses must never expose reset tokens."""
    app = create_app(
        {
            "TESTING": False,
            "JWT_SECRET": SECRET,
            "BCRYPT_ROUNDS": 4,
            "LMS_STORE": backend,
            "RESET_TOKEN_ECHO": True,
            "SQLITE_PATH": str(tmp_path / f"sec06_production_{backend}.sqlite3"),
            "RATE_LIMIT_DB_PATH": str(
                tmp_path / f"sec06_production_{backend}_rate.sqlite3"
            ),
        }
    )

    store = app.extensions["lms_store"]

    if isinstance(store, dict):
        existing_email = next(iter(store["users"].values()))["email"]
    else:
        with store._connect() as conn:
            existing_email = conn.execute("SELECT email FROM users LIMIT 1").fetchone()[
                "email"
            ]

    with app.test_client() as client:
        response = client.post(
            "/auth/forgot-password",
            json={"email": existing_email},
        )

    assert response.status_code == 202
    assert response.get_json() == {"status": "sent"}
    assert "resetToken" not in response.get_json()
