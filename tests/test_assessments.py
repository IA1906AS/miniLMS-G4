import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest

from app import create_app
from tests.db_helpers import schema_for


@pytest.fixture(params=["postgresql"])
def assessment_app(request, tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "assessments-test-secret-at-least-32-characters",
            "BCRYPT_ROUNDS": 4,
            "DATABASE_SCHEMA": schema_for(str(tmp_path / "lms.postgresql")),
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "SUBMISSION_UPLOAD_DIR": str(tmp_path / "submissions"),
            "MATERIAL_UPLOAD_DIR": str(tmp_path / "materials"),
        }
    )


def auth(client, email):
    response = client.post("/auth/login", json={"email": email, "password": "Lms@2026"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json["accessToken"]}


def assignment(client, teacher, course="c1"):
    response = client.post(
        f"/courses/{course}/assignments",
        headers=teacher,
        json={
            "title": "Bài tập Web",
            "description": "Nộp báo cáo",
            "dueAt": datetime.fromtimestamp(time.time() + 3600, UTC).isoformat(),
        },
    )
    assert response.status_code == 201, response.json
    return response.json


def submit_file(client, student, assignment_id, course="c1", content=b"Bai lam"):
    return client.post(
        f"/courses/{course}/assignments/{assignment_id}/submissions",
        headers=student,
        data={"file": (io.BytesIO(content), "../../report.txt")},
    )


def quiz(client, teacher, *, limit=1):
    response = client.post(
        "/courses/c1/quizzes",
        headers=teacher,
        json={
            "title": "Kiểm tra Web",
            "durationSeconds": 60,
            "maxAttempts": limit,
            "questions": [
                {"prompt": "1 + 1?", "choices": ["1", "2", "3"], "correctIndex": 1},
                {"prompt": "2 + 2?", "choices": ["4", "5"], "correctIndex": 0},
            ],
        },
    )
    assert response.status_code == 201, response.json
    return response.json


def start(client, student, quiz_id):
    return client.post(f"/courses/c1/quizzes/{quiz_id}/attempts", headers=student)


def answer_key(attempt):
    return {attempt["questions"][0]["id"]: 1, attempt["questions"][1]["id"]: 0}


def test_assignment_submission_grading_and_private_results(assessment_app):
    client = assessment_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    peer = auth(client, "dung.sv@lms.test")
    other_teacher = auth(client, "binh.gv@lms.test")
    outsider = auth(client, "em.sv@lms.test")
    item = assignment(client, teacher)
    assert client.get("/courses/c1/assignments", headers=outsider).status_code == 403
    result = submit_file(client, student, item["id"])
    assert result.status_code == 201
    submission = result.json
    assert submission["fileName"] == "report.txt" and submission["score"] is None
    assert "storageName" not in submission
    download = submission["downloadUrl"]
    for headers in (student, teacher):
        response = client.get(download, headers=headers)
        assert response.status_code == 200 and response.data == b"Bai lam"
        assert "attachment" in response.headers["Content-Disposition"]
        assert "no-store" in response.headers["Cache-Control"]
    assert client.get(download, headers=peer).status_code == 403
    assert client.get(download, headers=other_teacher).status_code == 403
    assert (
        client.get(download.replace("/c1/", "/c2/"), headers=other_teacher).status_code
        == 404
    )
    path = f"/courses/c1/assignments/{item['id']}/submissions"
    assert client.get(path, headers=peer).json == []
    assert len(client.get(path, headers=teacher).json) == 1
    grade_path = f"/courses/c1/submissions/{submission['id']}/grade"
    assert (
        client.put(grade_path, headers=student, json={"score": 10}).status_code == 403
    )
    assert (
        client.put(grade_path, headers=other_teacher, json={"score": 10}).status_code
        == 403
    )
    result = client.put(
        grade_path, headers=teacher, json={"score": 8.5, "feedback": "Làm tốt"}
    )
    assert result.status_code == 200 and result.json["feedback"] == "Làm tốt"
    own = client.get("/courses/c1/results", headers=student).json["assignments"][0]
    assert own["submission"]["score"] == 8.5
    assert (
        client.get("/courses/c1/results", headers=peer).json["assignments"][0][
            "submission"
        ]
        is None
    )
    assert client.get("/courses/c1/results", headers=outsider).status_code == 403
    # A replacement retains one submission, removes the old file, and needs grading again.
    directory = Path(assessment_app.config["SUBMISSION_UPLOAD_DIR"])
    first = set(directory.iterdir())
    replacement = submit_file(client, student, item["id"], content=b"Ban moi")
    assert replacement.status_code == 201 and replacement.json["id"] == submission["id"]
    assert replacement.json["score"] is None and replacement.json["feedback"] == ""
    assert len(list(directory.iterdir())) == 1 and not first & set(directory.iterdir())
    assert client.get(download, headers=student).data == b"Ban moi"
    assert (
        client.delete("/courses/c1/enrollments/u4", headers=teacher).status_code == 200
    )
    assert client.get(download, headers=student).status_code == 403


def test_deadline_and_invalid_submission_cleanup(assessment_app, monkeypatch):
    client = assessment_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    item = assignment(client, teacher)
    deadline = datetime.fromisoformat(item["dueAt"]).timestamp()
    monkeypatch.setattr("app.api.assessments.time.time", lambda: deadline)
    result = submit_file(client, student, item["id"])
    assert result.status_code == 409 and result.json["error"] == "ASSIGNMENT_CLOSED"
    assert not list(Path(assessment_app.config["SUBMISSION_UPLOAD_DIR"]).iterdir())
    path = f"/courses/c1/assignments/{item['id']}/submissions"
    assert client.get(path, headers=student).json == []
    assert submit_file(client, student, "missing").status_code == 404


def test_creation_and_grading_validation(assessment_app):
    client = assessment_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    admin = auth(client, "admin@lms.test")
    body = {"title": "X", "description": "", "dueAt": "2099-01-01T00:00:00+00:00"}
    for headers in (student, admin):
        assert (
            client.post(
                "/courses/c1/assignments", headers=headers, json=body
            ).status_code
            == 403
        )
    assert (
        client.post("/courses/c2/assignments", headers=teacher, json=body).status_code
        == 403
    )
    for due in ("2020-01-01T00:00:00Z", "2099-01-01T00:00:00", "invalid", None):
        assert (
            client.post(
                "/courses/c1/assignments", headers=teacher, json={**body, "dueAt": due}
            ).status_code
            == 400
        )
    item = assignment(client, teacher)
    submission = submit_file(client, student, item["id"]).json
    path = f"/courses/c1/submissions/{submission['id']}/grade"
    for score in (True, -1, 11, "10", None, float("nan"), float("inf")):
        assert (
            client.put(path, headers=teacher, json={"score": score}).status_code == 400
        )
    assert (
        client.put(
            path, headers=teacher, json={"score": 10, "studentId": "u1"}
        ).status_code
        == 400
    )
    assert submit_file(client, student, item["id"], content=b"\xff").status_code == 400
    assert (
        submit_file(
            client, student, item["id"], content=b"a" * (10 * 1024 * 1024 + 1)
        ).status_code
        == 413
    )


def test_quiz_server_grading_no_answer_key_leaks_and_replay(assessment_app):
    client = assessment_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    peer = auth(client, "dung.sv@lms.test")
    item = quiz(client, teacher)
    detail_path = f"/courses/c1/quizzes/{item['id']}"
    student_detail = client.get(detail_path, headers=student)
    assert "questions" not in student_detail.json
    first = start(client, student, item["id"])
    assert first.status_code == 201
    attempt = first.json
    assert "correctIndex" not in json.dumps(attempt)
    resumed = start(client, student, item["id"])
    assert resumed.status_code == 200 and resumed.json["id"] == attempt["id"]
    path = f"/courses/c1/quiz-attempts/{attempt['id']}"
    assert client.get(path, headers=peer).status_code == 403
    assert (
        client.put(
            path + "/answers", headers=peer, json={"answers": answer_key(attempt)}
        ).status_code
        == 403
    )
    saved = client.put(
        path + "/answers",
        headers=student,
        json={"answers": {attempt["questions"][0]["id"]: 1}},
    )
    assert saved.status_code == 200 and saved.json["score"] is None
    assert start(client, student, item["id"]).json["answers"] == saved.json["answers"]
    result = client.post(path + "/submit", headers=student, json={"answers": {}})
    assert result.status_code == 200 and result.json["score"] == 5
    assert result.json["status"] == "SUBMITTED" and "correctIndex" not in json.dumps(
        result.json
    )
    # Replaying a completed attempt with the correct answers cannot change its grade.
    assert (
        client.post(
            path + "/submit", headers=student, json={"answers": answer_key(attempt)}
        ).json["score"]
        == 5
    )
    assert (
        client.put(
            path + "/answers", headers=student, json={"answers": answer_key(attempt)}
        ).status_code
        == 409
    )
    assert start(client, student, item["id"]).status_code == 409
    history = client.get(detail_path + "/attempts", headers=student)
    assert "correctIndex" not in json.dumps(history.json)
    assert client.get(detail_path + "/attempts", headers=peer).json == []
    results = client.get("/courses/c1/results", headers=student).json
    assert results["quizzes"][0]["bestScore"] == 5
    assert (
        client.get("/courses/c1/results", headers=peer).json["quizzes"][0]["bestScore"]
        is None
    )


def test_quiz_expiry_uses_saved_answers_and_blocks_late_answers(
    assessment_app, monkeypatch
):
    client = assessment_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    item = quiz(client, teacher, limit=2)
    attempt = start(client, student, item["id"]).json
    path = f"/courses/c1/quiz-attempts/{attempt['id']}"
    client.put(
        path + "/answers",
        headers=student,
        json={"answers": {attempt["questions"][0]["id"]: 1}},
    )
    deadline = datetime.fromisoformat(attempt["expiresAt"]).timestamp()
    monkeypatch.setattr("app.api.assessments.time.time", lambda: deadline + 1)
    result = client.post(
        path + "/submit", headers=student, json={"answers": answer_key(attempt)}
    )
    assert (
        result.status_code == 200
        and result.json["score"] == 5
        and result.json["status"] == "EXPIRED"
    )
    second = start(client, student, item["id"])
    assert second.status_code == 201 and second.json["id"] != attempt["id"]
    second_id = second.json["id"]
    second_deadline = datetime.fromisoformat(second.json["expiresAt"]).timestamp()
    monkeypatch.setattr("app.api.assessments.time.time", lambda: second_deadline + 1)
    closed = client.put(
        f"/courses/c1/quiz-attempts/{second_id}/answers",
        headers=student,
        json={"answers": answer_key(second.json)},
    )
    assert closed.status_code == 409
    # Expiry must commit even though answer saving returned 409.
    history = client.get(
        f"/courses/c1/quizzes/{item['id']}/attempts", headers=student
    ).json
    assert [row["score"] for row in history] == [5, 0]
    assert all(row["status"] == "EXPIRED" for row in history)
    assert start(client, student, item["id"]).status_code == 409


def test_quiz_validation_and_role_boundaries(assessment_app):
    client = assessment_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    other = auth(client, "binh.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    outsider = auth(client, "em.sv@lms.test")
    body = {
        "title": "Quiz",
        "durationSeconds": 60,
        "maxAttempts": 1,
        "questions": [{"prompt": "Q", "choices": ["A", "B"], "correctIndex": 0}],
    }
    for change in (
        {"durationSeconds": 0},
        {"durationSeconds": True},
        {"maxAttempts": 11},
        {"questions": []},
        {"questions": [{"prompt": "X", "choices": ["A"], "correctIndex": 0}]},
        {"questions": [{"prompt": "X", "choices": ["A", "B"], "correctIndex": 2}]},
    ):
        assert (
            client.post(
                "/courses/c1/quizzes", headers=teacher, json={**body, **change}
            ).status_code
            == 400
        )
    assert (
        client.post("/courses/c1/quizzes", headers=other, json=body).status_code == 403
    )
    assert (
        client.post("/courses/c1/quizzes", headers=student, json=body).status_code
        == 403
    )
    item = quiz(client, teacher)
    assert client.get("/courses/c1/quizzes", headers=outsider).status_code == 403
    assert start(client, teacher, item["id"]).status_code == 403
    assert start(client, outsider, item["id"]).status_code == 403
    attempt = start(client, student, item["id"]).json
    path = f"/courses/c1/quiz-attempts/{attempt['id']}"
    for answers in (
        {"missing": 0},
        {attempt["questions"][0]["id"]: True},
        {attempt["questions"][0]["id"]: 50},
        [],
        None,
    ):
        assert (
            client.put(
                path + "/answers", headers=student, json={"answers": answers}
            ).status_code
            == 400
        )
    assert (
        client.post(
            path + "/submit", headers=student, json={"answers": {}, "score": 10}
        ).status_code
        == 400
    )
    assert (
        client.post(path + "/submit", headers=teacher, json={"answers": {}}).status_code
        == 403
    )
    assert client.get(path.replace("/c1/", "/c2/"), headers=other).status_code == 404


def test_concurrent_quiz_start_and_submit_are_atomic(assessment_app):
    client = assessment_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    item = quiz(client, teacher)
    barrier = Barrier(2)

    def start_parallel(_):
        with assessment_app.test_client() as parallel:
            barrier.wait(timeout=10)
            return start(parallel, student, item["id"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(start_parallel, range(2)))
    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json["id"] == responses[1].json["id"]
    attempt = responses[0].json
    barrier = Barrier(2)

    def submit_parallel(index):
        with assessment_app.test_client() as parallel:
            barrier.wait(timeout=10)
            response = parallel.post(
                f"/courses/c1/quiz-attempts/{attempt['id']}/submit",
                headers=student,
                json={"answers": answer_key(attempt) if index else {}},
            )
            assert response.status_code == 200
            return response.json["score"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        scores = list(pool.map(submit_parallel, range(2)))
    assert scores[0] == scores[1] and scores[0] in (0, 10)


def test_postgres_persistence_and_course_deletion(assessment_app):
    client = assessment_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    admin = auth(client, "admin@lms.test")
    item = assignment(client, teacher)
    submission = submit_file(client, student, item["id"]).json
    q = quiz(client, teacher)
    attempt = start(client, student, q["id"]).json
    path = f"/courses/c1/quiz-attempts/{attempt['id']}"
    client.put(
        path + "/answers", headers=student, json={"answers": answer_key(attempt)}
    )
    client = create_app(dict(assessment_app.config)).test_client()
    assert start(client, student, q["id"]).json["id"] == attempt["id"]
    assert client.get(submission["downloadUrl"], headers=student).data == b"Bai lam"
    assert (
        client.post(path + "/submit", headers=student, json={"answers": {}}).json[
            "score"
        ]
        == 10
    )
    assert client.delete("/courses/c1", headers=admin).status_code == 200
    assert not list(Path(assessment_app.config["SUBMISSION_UPLOAD_DIR"]).iterdir())
    assert client.get(submission["downloadUrl"], headers=student).status_code == 404


def test_anonymous_endpoints_and_study_template(assessment_app):
    client = assessment_app.test_client()
    for method, path in (
        ("get", "/courses/c1/assignments"),
        ("post", "/courses/c1/assignments"),
        ("post", "/courses/c1/assignments/a/submissions"),
        ("get", "/courses/c1/assignments/a/submissions"),
        ("get", "/courses/c1/submissions/s/download"),
        ("put", "/courses/c1/submissions/s/grade"),
        ("get", "/courses/c1/quizzes"),
        ("post", "/courses/c1/quizzes"),
        ("post", "/courses/c1/quizzes/q/attempts"),
        ("put", "/courses/c1/quiz-attempts/a/answers"),
        ("post", "/courses/c1/quiz-attempts/a/submit"),
        ("get", "/courses/c1/results"),
    ):
        assert getattr(client, method)(path).status_code == 401
    page = client.get("/study?course=c1")
    assert page.status_code == 200 and b"/static/js/study.js" in page.data
    assert (
        b'id="quiz-answer-form"' in page.data and b'id="submission-upload"' in page.data
    )
