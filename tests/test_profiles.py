import io
from pathlib import Path

import pytest
from PIL import Image

from app import create_app
from tests.db_helpers import connect_schema, schema_for


@pytest.fixture(params=["postgresql"])
def profile_app(request, tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "profiles-test-secret-at-least-32-characters",
            "BCRYPT_ROUNDS": 4,
            "DATABASE_SCHEMA": schema_for(str(tmp_path / "lms.postgresql")),
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "AVATAR_UPLOAD_DIR": str(tmp_path / "avatars"),
        }
    )


def auth(client, email):
    response = client.post("/auth/login", json={"email": email, "password": "Lms@2026"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json["accessToken"]}


def picture(fmt="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (800, 400), "navy").save(output, format=fmt)
    output.seek(0)
    return output


@pytest.mark.parametrize(
    "email", ["chi.sv@lms.test", "an.gv@lms.test", "admin@lms.test"]
)
def test_edit_own_profile_and_reject_privilege_changes(profile_app, email):
    client = profile_app.test_client()
    headers = auth(client, email)
    response = client.put(
        "/me/profile",
        headers=headers,
        json={
            "fullName": "  Nguyễn An  ",
            "bio": "Xin chào\nLớp Web",
            "contact": "0901234567",
        },
    )
    assert response.status_code == 200
    assert response.json["fullName"] == "Nguyễn An"
    assert client.get("/me/profile", headers=headers).json["contact"] == "0901234567"
    for body in (
        {"role": "ADMIN"},
        {"id": "u1"},
        {"email": "other@test.com"},
        {"avatar_filename": "../secret"},
        {"bio": None},
        {"fullName": "x" * 121},
        {"bio": "x" * 2001},
        {"contact": "x" * 501},
        {},
        [],
    ):
        assert client.put("/me/profile", headers=headers, json=body).status_code == 400
    response = client.put("/me/profile", headers=headers, json={"bio": ""})
    assert response.json["bio"] == ""
    assert response.json["fullName"] == "Nguyễn An"


def test_membership_and_public_profile_privacy(profile_app):
    client = profile_app.test_client()
    student = auth(client, "chi.sv@lms.test")
    teacher = auth(client, "an.gv@lms.test")
    other = auth(client, "em.sv@lms.test")
    admin = auth(client, "admin@lms.test")
    client.put(
        "/me/profile",
        headers=student,
        json={"fullName": "Chi", "bio": "Sinh viên Web", "contact": "private-phone"},
    )
    assert [c["id"] for c in client.get("/me/courses", headers=student).json] == ["c1"]
    for headers in (student, teacher, admin):
        response = client.get("/courses/c1/members", headers=headers)
        assert response.status_code == 200
        assert {item["id"] for item in response.json} == {"u2", "u4", "u5"}
        public = client.get("/users/u4/profile", headers=headers)
        assert public.status_code == 200
        assert public.json["fullName"] == "Chi"
        assert set(public.json) == {"id", "fullName", "bio", "role", "avatarUrl"}
    for path in ("/courses/c1/members", "/users/u4/profile", "/users/u4/avatar"):
        assert client.get(path, headers=other).status_code == 403
    assert client.get("/courses/missing/members", headers=student).status_code == 404
    assert client.get("/users/missing/profile", headers=admin).status_code == 404
    # Removing an enrollment immediately removes access to former classmates.
    assert (
        client.delete("/courses/c1/enrollments/u4", headers=teacher).status_code == 200
    )
    assert client.get("/users/u5/profile", headers=student).status_code == 403
    assert client.get("/me/courses", headers=student).json == []


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_avatar_upload_reencode_replace_and_delete(profile_app, fmt):
    client = profile_app.test_client()
    student = auth(client, "chi.sv@lms.test")
    teacher = auth(client, "an.gv@lms.test")
    assert client.get("/users/u4/avatar", headers=student).status_code == 404
    response = client.post(
        "/me/avatar",
        headers=student,
        data={"avatar": (picture(fmt), "../../untrusted-name.jpg")},
    )
    assert response.status_code == 200
    assert response.json["avatarUrl"] == "/users/u4/avatar"
    response = client.get("/users/u4/avatar", headers=teacher)
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert "no-store" in response.headers["Cache-Control"]
    with Image.open(io.BytesIO(response.data)) as image:
        assert image.size == (512, 256)
    directory = profile_app.config["AVATAR_UPLOAD_DIR"]
    first = set(Path(directory).iterdir())
    assert (
        client.post(
            "/me/avatar", headers=student, data={"avatar": (picture(), "new.png")}
        ).status_code
        == 200
    )
    second = set(Path(directory).iterdir())
    assert len(second) == 1 and not first & second
    assert client.delete("/me/avatar", headers=student).json["avatarUrl"] is None
    assert not list(Path(directory).iterdir())
    assert client.get("/users/u4/avatar", headers=teacher).status_code == 404


def test_invalid_avatar_and_anonymous_requests(profile_app):
    client = profile_app.test_client()
    headers = auth(client, "chi.sv@lms.test")
    for content in (b"<svg onload='alert(1)'/>", b"not-an-image", b"\x89PNG\r\n\x1a\n"):
        response = client.post(
            "/me/avatar",
            headers=headers,
            data={"avatar": (io.BytesIO(content), "fake.png")},
        )
        assert response.status_code == 400
    assert client.post("/me/avatar", headers=headers, data={}).status_code == 400
    response = client.post(
        "/me/avatar",
        headers=headers,
        data={"avatar": (io.BytesIO(b"x" * (2 * 1024 * 1024 + 1)), "large.png")},
    )
    assert response.status_code == 413
    assert response.json == {"error": "FILE_TOO_LARGE"}
    for method, path in (
        ("get", "/me/profile"),
        ("put", "/me/profile"),
        ("post", "/me/avatar"),
        ("delete", "/me/avatar"),
        ("get", "/me/courses"),
        ("get", "/courses/c1/members"),
        ("get", "/users/u4/profile"),
        ("get", "/users/u4/avatar"),
    ):
        assert getattr(client, method)(path).status_code == 401


def test_large_image_dimensions_rejected(profile_app):
    client = profile_app.test_client()
    headers = auth(client, "chi.sv@lms.test")
    output = io.BytesIO()
    Image.new("1", (4001, 4000)).save(output, format="PNG")
    output.seek(0)
    assert (
        client.post(
            "/me/avatar",
            headers=headers,
            data={"avatar": (output, "large-dimensions.png")},
        ).status_code
        == 400
    )


def test_postgres_existing_schema_migrates_and_profile_survives_restart(tmp_path):
    database = schema_for(tmp_path / "old.postgresql")
    with connect_schema(database) as conn:
        conn.execute(
            "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, "
            "role TEXT NOT NULL, password_hash TEXT NOT NULL)"
        )
    config = {
        "TESTING": True,
        "JWT_SECRET": "profile-test-secret-at-least-32-characters",
        "BCRYPT_ROUNDS": 4,
        "DATABASE_SCHEMA": database,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
        "AVATAR_UPLOAD_DIR": str(tmp_path / "avatars"),
    }
    client = create_app(config).test_client()
    headers = auth(client, "chi.sv@lms.test")
    assert (
        client.put(
            "/me/profile",
            headers=headers,
            json={"fullName": "Chi", "bio": "Lớp Web", "contact": "private"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/me/avatar", headers=headers, data={"avatar": (picture(), "avatar.png")}
        ).status_code
        == 200
    )
    restarted = create_app(config).test_client()
    assert restarted.get("/me/profile", headers=headers).json["fullName"] == "Chi"
    assert restarted.get("/users/u4/avatar", headers=headers).status_code == 200
    page = restarted.get("/account")
    assert page.status_code == 200
    assert b'id="profile-form"' in page.data
    assert b"/static/js/profiles.js" in page.data
