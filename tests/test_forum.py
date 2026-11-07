import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "forum-tests-secret-at-least-32-characters",
            "BCRYPT_ROUNDS": 4,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "SMTP_ENABLED": False,
        }
    ).test_client()


def auth(client, email):
    result = client.post("/auth/login", json={"email": email, "password": "Lms@2026"})
    assert result.status_code == 200
    return {"Authorization": "Bearer " + result.json["accessToken"]}


def topic(client, headers):
    result = client.post(
        "/courses/c1/forum/topics",
        headers=headers,
        json={"title": "Câu hỏi", "body": "Nội dung\n<script>alert(1)</script>"},
    )
    assert result.status_code == 201
    return result.json["id"]


def test_membership_and_author_ownership(client):
    student = auth(client, "chi.sv@lms.test")
    teacher = auth(client, "an.gv@lms.test")
    outsider = auth(client, "em.sv@lms.test")
    admin = auth(client, "admin@lms.test")
    base = "/courses/c1/forum"
    assert client.get(base + "/topics").status_code == 401
    assert client.get(base + "/topics", headers=outsider).status_code == 403
    item = topic(client, student)
    assert client.get(base + "/topics", headers=teacher).json["total"] == 1
    assert client.get(base + "/topics/" + item, headers=student).json["canEdit"]
    for actor in (teacher, admin):
        assert client.delete(base + "/posts/" + item, headers=actor).status_code == 403
        assert (
            client.put(
                base + "/posts/" + item,
                headers=actor,
                json={"title": "changed", "body": "changed"},
            ).status_code
            == 403
        )
    assert (
        client.put(
            base + "/posts/" + item,
            headers=student,
            json={"title": "Đã sửa", "body": "Nội dung mới"},
        ).status_code
        == 200
    )
    assert (
        client.get(base + "/topics/" + item, headers=teacher).json["title"] == "Đã sửa"
    )
    client.delete("/courses/c1/enrollments/u4", headers=teacher)
    assert client.get(base + "/topics/" + item, headers=student).status_code == 403
    assert client.delete(base + "/posts/" + item, headers=student).status_code == 403


def test_comments_and_topic_deletion(client):
    student = auth(client, "chi.sv@lms.test")
    teacher = auth(client, "an.gv@lms.test")
    item = topic(client, student)
    base = "/courses/c1/forum"
    url = base + "/topics/" + item + "/comments"
    comment = client.post(url, headers=teacher, json={"body": "Giải đáp"})
    assert comment.status_code == 201
    comment_id = comment.json["id"]
    assert client.get(url, headers=student).json["total"] == 1
    assert (
        client.put(
            base + "/posts/" + comment_id,
            headers=teacher,
            json={"body": "Đã sửa trả lời"},
        ).status_code
        == 200
    )
    assert (
        client.delete(base + "/posts/" + comment_id, headers=student).status_code == 403
    )
    assert client.delete(base + "/posts/" + item, headers=student).status_code == 200
    assert client.get(url, headers=teacher).status_code == 404
    assert (
        client.put(
            base + "/posts/" + comment_id, headers=teacher, json={"body": "gone"}
        ).status_code
        == 404
    )


def test_post_cannot_be_addressed_through_other_course(client):
    teacher = auth(client, "an.gv@lms.test")
    item = topic(client, teacher)
    admin = auth(client, "admin@lms.test")
    assert (
        client.get("/courses/c2/forum/topics/" + item, headers=admin).status_code == 404
    )
    assert (
        client.get(
            "/courses/c2/forum/topics/" + item + "/comments", headers=admin
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": " ", "body": "text"},
        {"title": "x", "body": []},
        {"title": "x", "body": "a" * 10001},
        {"title": "x", "body": "text", "authorId": "u1"},
    ],
)
def test_forum_validation(client, body):
    headers = auth(client, "chi.sv@lms.test")
    assert (
        client.post("/courses/c1/forum/topics", headers=headers, json=body).status_code
        == 400
    )


def test_forum_persistence_and_course_cleanup(client):
    headers = auth(client, "an.gv@lms.test")
    item = topic(client, headers)
    restarted = create_app(dict(client.application.config)).test_client()
    assert (
        restarted.get("/courses/c1/forum/topics/" + item, headers=headers).status_code
        == 200
    )
    assert (
        client.get("/courses/c1/forum/topics?page=0", headers=headers).status_code
        == 400
    )
    assert (
        client.delete("/courses/c1", headers=auth(client, "admin@lms.test")).status_code
        == 200
    )
    assert client.application.extensions["lms_store"].forum_list("c1", None, 1)[1] == 0
