import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from app import create_app
from app.api.errors import Forbidden
from app.api.services import add_enrollment, create_course, update_course
from tests.db_helpers import schema_for


@pytest.fixture(params=["postgresql"])
def learning_app(request, tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "learning-test-secret-at-least-32-characters",
            "BCRYPT_ROUNDS": 4,
            "DATABASE_SCHEMA": schema_for(str(tmp_path / "lms.postgresql")),
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "MATERIAL_UPLOAD_DIR": str(tmp_path / "materials"),
        }
    )


def auth(client, email):
    response = client.post("/auth/login", json={"email": email, "password": "Lms@2026"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json["accessToken"]}


def upload(
    client, headers, course="c1", content=b"Lecture notes", filename="lesson.txt"
):
    return client.post(
        f"/courses/{course}/materials",
        headers=headers,
        data={"title": "Bài giảng 1", "file": (io.BytesIO(content), filename)},
    )


def test_search_and_instructor_filter(learning_app):
    client = learning_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    client.post("/courses", headers=teacher, json={"title": "Python Cơ Bản"})
    student = auth(client, "chi.sv@lms.test")
    response = client.get(
        "/courses", headers=student, query_string={"q": "PYTHON", "instructorId": "u2"}
    )
    assert response.status_code == 200
    assert [item["title"] for item in response.json] == ["Python Cơ Bản"]
    for query in (
        {"q": "no-match"},
        {"q": "Python", "instructorId": "u3"},
        {"q": "%' OR 1=1 --"},
    ):
        assert client.get("/courses", headers=student, query_string=query).json == []
    assert all(
        item["instructorId"] == "u3"
        for item in client.get("/courses?instructorId=u3", headers=student).json
    )
    assert {row["id"] for row in client.get("/instructors", headers=student).json} == {
        "u2",
        "u3",
    }
    assert all(
        set(row) == {"id", "fullName"}
        for row in client.get("/instructors", headers=student).json
    )


def test_teacher_owns_created_course_and_cannot_transfer(learning_app):
    client = learning_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    other = auth(client, "binh.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    response = client.post("/courses", headers=teacher, json={"title": "Python"})
    assert response.status_code == 201
    course = response.json
    assert course["instructorId"] == "u2"
    path = "/courses/" + course["id"]
    assert (
        client.put(path, headers=teacher, json={"title": "Python nâng cao"}).status_code
        == 200
    )
    assert (
        client.put(path, headers=other, json={"title": "Take over"}).status_code == 403
    )
    assert (
        client.put(path, headers=student, json={"title": "Take over"}).status_code
        == 403
    )
    assert (
        client.put(path, headers=teacher, json={"instructorId": "u3"}).status_code
        == 403
    )
    assert (
        client.post(
            "/courses", headers=teacher, json={"title": "X", "instructorId": "u3"}
        ).status_code
        == 403
    )
    assert (
        client.post("/courses", headers=teacher, json={"title": "x" * 201}).status_code
        == 400
    )
    assert client.delete(path, headers=teacher).status_code == 403
    detail = client.get(path, headers=teacher).json
    assert detail["canManage"] and detail["canAccessMaterials"]
    assert detail["courseCode"] == course["id"]


def test_course_service_permissions_without_route(learning_app):
    store = learning_app.extensions["lms_store"]
    teacher = {"id": "u2", "role": "INSTRUCTOR"}
    student = {"id": "u4", "role": "STUDENT"}
    with pytest.raises(Forbidden):
        create_course(teacher, "X", "u3", store=store)
    with pytest.raises(Forbidden):
        update_course(teacher, "c2", title="X", store=store)
    with pytest.raises(Forbidden):
        update_course(teacher, "c1", instructor_id="u3", store=store)
    with pytest.raises(Forbidden):
        add_enrollment(student, "c2", "u6", store=store, self_enroll=True)
    with pytest.raises(Forbidden):
        add_enrollment(student, "c2", "u4", store=store)


def test_join_duplicate_and_membership_access(learning_app):
    client = learning_app.test_client()
    student = auth(client, "em.sv@lms.test")
    teacher = auth(client, "an.gv@lms.test")
    assert not client.get("/courses/c1", headers=student).json["canAccessMaterials"]
    assert (
        client.post(
            "/courses/join", headers=student, json={"courseCode": " c1 "}
        ).status_code
        == 201
    )
    assert client.get("/courses/c1", headers=student).json["enrolled"]
    assert client.get("/courses/c1/members", headers=student).status_code == 200
    response = client.post("/courses/join", headers=student, json={"courseCode": "c1"})
    assert response.status_code == 409 and response.json["error"] == "ALREADY_ENROLLED"
    assert (
        client.post(
            "/courses/join", headers=student, json={"courseCode": "missing"}
        ).status_code
        == 404
    )
    for body in ({"courseCode": "c1", "studentId": "u4"}, {"courseCode": None}, {}, []):
        assert (
            client.post("/courses/join", headers=student, json=body).status_code == 400
        )
    assert (
        client.post(
            "/courses/join", headers=teacher, json={"courseCode": "c2"}
        ).status_code
        == 403
    )
    assert (
        client.delete("/courses/c1/enrollments/u6", headers=teacher).status_code == 200
    )
    assert client.get("/courses/c1/materials", headers=student).status_code == 403


def test_concurrent_join_only_enrolls_once(learning_app):
    client = learning_app.test_client()
    headers = auth(client, "em.sv@lms.test")
    barrier = Barrier(2)

    def join(_):
        with learning_app.test_client() as parallel:
            barrier.wait(timeout=10)
            return parallel.post(
                "/courses/join", headers=headers, json={"courseCode": "c1"}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(join, range(2))) == [201, 409]


def test_material_permissions_download_and_revocation(learning_app):
    client = learning_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    other = auth(client, "binh.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    outsider = auth(client, "em.sv@lms.test")
    response = upload(client, teacher, filename="../../lesson.txt")
    assert response.status_code == 201
    material = response.json
    assert material["fileName"] == "lesson.txt"
    assert "storage_name" not in material
    download = material["downloadUrl"]
    for headers in (teacher, student):
        assert len(client.get("/courses/c1/materials", headers=headers).json) == 1
        result = client.get(download, headers=headers)
        assert result.status_code == 200 and result.data == b"Lecture notes"
        assert result.mimetype == "application/octet-stream"
        assert "attachment" in result.headers["Content-Disposition"]
        assert "no-store" in result.headers["Cache-Control"]
    for headers in (outsider, other):
        assert client.get("/courses/c1/materials", headers=headers).status_code == 403
        assert client.get(download, headers=headers).status_code == 403
    for headers in (student, outsider, other):
        assert upload(client, headers).status_code == 403
        assert (
            client.delete(
                "/courses/c1/materials/" + material["id"], headers=headers
            ).status_code
            == 403
        )
    assert (
        client.get(download.replace("/c1/", "/c2/"), headers=other).status_code == 404
    )
    assert (
        client.delete("/courses/c1/enrollments/u4", headers=teacher).status_code == 200
    )
    assert client.get(download, headers=student).status_code == 403
    assert (
        client.delete(
            "/courses/c1/materials/" + material["id"], headers=teacher
        ).status_code
        == 200
    )
    assert client.get(download, headers=teacher).status_code == 404
    assert not list(Path(learning_app.config["MATERIAL_UPLOAD_DIR"]).iterdir())


def test_material_validation_and_size_limits(learning_app):
    client = learning_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    for filename, content in (
        ("x.html", b"<script>x</script>"),
        ("x.pdf", b"fake"),
        ("x.txt", b"\xff"),
        ("x.txt", b"a\x00b"),
        ("x.docx", b"not-a-zip"),
        ("x.txt", b""),
    ):
        assert (
            upload(client, teacher, filename=filename, content=content).status_code
            == 400
        )
    assert (
        client.post("/courses/c1/materials", headers=teacher, data={}).status_code
        == 400
    )
    response = upload(client, teacher, content=b"a" * (10 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json["error"] == "FILE_TOO_LARGE"
    assert upload(client, teacher, content=b"a" * (11 * 1024 * 1024)).status_code == 413
    assert (
        upload(
            client, teacher, filename="slides.pdf", content=b"%PDF-1.4\nexample"
        ).status_code
        == 201
    )


@pytest.mark.parametrize(
    ("suffix", "entry"),
    [
        ("docx", "word/document.xml"),
        ("pptx", "ppt/presentation.xml"),
        ("xlsx", "xl/workbook.xml"),
    ],
)
def test_office_materials_and_reject_macros(learning_app, suffix, entry):
    client = learning_app.test_client()
    teacher = auth(client, "an.gv@lms.test")

    def office(macro=False):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr(entry, "<document/>")
            if macro:
                archive.writestr("word/vbaProject.bin", b"macro")
        return output.getvalue()

    assert (
        upload(
            client, teacher, filename="lesson." + suffix, content=office()
        ).status_code
        == 201
    )
    assert (
        upload(
            client, teacher, filename="lesson." + suffix, content=office(True)
        ).status_code
        == 400
    )


def test_delete_course_cleans_materials_and_files(learning_app):
    client = learning_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    admin = auth(client, "admin@lms.test")
    document = upload(client, teacher).json
    assert client.delete("/courses/c1", headers=admin).status_code == 200
    assert client.get(document["downloadUrl"], headers=teacher).status_code == 404
    assert not list(Path(learning_app.config["MATERIAL_UPLOAD_DIR"]).iterdir())
    assert client.get("/courses/c1/materials", headers=admin).status_code == 404


def test_anonymous_requests_and_catalog_page(learning_app):
    client = learning_app.test_client()
    for method, path in (
        ("get", "/instructors"),
        ("get", "/courses/c1"),
        ("post", "/courses/join"),
        ("get", "/courses/c1/materials"),
        ("post", "/courses/c1/materials"),
        ("get", "/courses/c1/materials/id/download"),
        ("delete", "/courses/c1/materials/id"),
    ):
        assert getattr(client, method)(path).status_code == 401
    page = client.get("/catalog")
    assert page.status_code == 200
    assert b'id="course-search"' in page.data and b"/static/js/courses.js" in page.data


def test_postgres_materials_and_enrollment_survive_restart(learning_app):
    client = learning_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "em.sv@lms.test")
    course = client.post(
        "/courses", headers=teacher, json={"title": "Persistent course"}
    ).json
    material = upload(client, teacher, course=course["id"]).json
    assert (
        client.post(
            "/courses/join", headers=student, json={"courseCode": course["id"]}
        ).status_code
        == 201
    )
    restarted = create_app(dict(learning_app.config)).test_client()
    assert restarted.get("/courses/" + course["id"], headers=student).json["enrolled"]
    assert (
        restarted.get(material["downloadUrl"], headers=student).data == b"Lecture notes"
    )
