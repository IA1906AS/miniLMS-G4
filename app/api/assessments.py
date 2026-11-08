"""Assignments, private submissions and server-authoritative quiz attempts."""

import copy
import io
import math
import secrets
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from app.api.assessment_store import assessment_records
from app.api.audit import write_audit
from app.api.errors import APIError, Forbidden, NotFound, ValidationError
from app.api.guards import require_role
from app.api.idempotency import (
    find_response,
    save_response,
    submission_hash,
    submission_key,
)
from app.api.learning import MAX_DOCUMENT_BYTES, _authorize, _validate_document

bp = Blueprint("assessments", __name__)


class AssessmentConflict(APIError):
    status_code = 409

    def __init__(self, code):
        self.error_code = code
        super().__init__(code)


def _store():
    return current_app.extensions["lms_store"]


def _records(course_id):
    return assessment_records(_store(), course_id)


def _audit(action):
    write_audit(g.actor["id"], action, request.path, "SUCCESS")


def _json():
    request.max_content_length = 1024 * 1024
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError()
    return data


def _text(value, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValidationError()
    value = value.strip()
    if required and not value:
        raise ValidationError()
    return value


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def _new(course_id, **fields):
    return {"id": secrets.token_hex(16), "courseId": course_id, **fields}


@bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _assignment_public(item):
    return {
        key: item[key]
        for key in ("id", "courseId", "title", "description", "dueAt", "createdAt")
    }


@bp.post("/courses/<course_id>/assignments")
@require_role("INSTRUCTOR")
def create_assignment(course_id):
    _authorize(course_id, manage=True)
    data = _json()
    if set(data) - {"title", "description", "dueAt"}:
        raise ValidationError()
    title = _text(data.get("title"), 200, required=True)
    description = _text(data.get("description", ""), 10000)
    raw_due = _text(data.get("dueAt"), 80, required=True)
    try:
        due = datetime.fromisoformat(raw_due)
        if due.tzinfo is None:
            raise ValueError("Timezone required")
        deadline = due.timestamp()
    except (ValueError, OverflowError) as exc:
        raise ValidationError() from exc
    if deadline <= time.time():
        raise ValidationError()
    item = _new(
        course_id,
        title=title,
        description=description,
        dueAt=_iso(deadline),
        deadline=deadline,
        createdAt=_iso(time.time()),
    )
    with _records(course_id) as records:
        records.save("assignments", item)
    _audit("CREATE_ASSIGNMENT")
    return jsonify(_assignment_public(item)), 201


@bp.get("/courses/<course_id>/assignments")
def assignments(course_id):
    _authorize(course_id)
    with _records(course_id) as records:
        result = [_assignment_public(item) for item in records.list("assignments")]
    return jsonify(result)


def _submission_public(item):
    return {
        **{
            key: item[key]
            for key in (
                "id",
                "courseId",
                "studentId",
                "fileName",
                "size",
                "submittedAt",
                "score",
                "feedback",
            )
        },
        "assignmentId": item["parentId"],
        "downloadUrl": f"/courses/{item['courseId']}/submissions/{item['id']}/download",
    }


def _submission_access(item):
    if g.actor["role"] == "STUDENT" and item["studentId"] != g.actor["id"]:
        raise Forbidden()


def _file_path(storage_name):
    if len(storage_name) != 32 or any(
        c not in "0123456789abcdef" for c in storage_name
    ):
        raise NotFound()
    return Path(current_app.config["SUBMISSION_UPLOAD_DIR"]) / storage_name


def submission_files(store, course_id):
    with assessment_records(store, course_id) as records:
        return [item["storageName"] for item in records.list("submissions")]


def remove_submission_files(names):
    for name in names:
        _file_path(name).unlink(missing_ok=True)


@bp.post("/courses/<course_id>/assignments/<assignment_id>/submissions")
@require_role("STUDENT")
def submit_assignment(course_id, assignment_id):
    _authorize(course_id)

    # Mã đại diện cho thao tác nộp bài.
    key = submission_key()

    # Giữ nguyên các kiểm tra file.
    request.max_content_length = MAX_DOCUMENT_BYTES + 64 * 1024
    if set(request.files) != {"file"} or len(request.files.getlist("file")) != 1:
        raise ValidationError()

    upload = request.files["file"]
    filename = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not filename or len(filename) > 200 or any(ord(char) < 32 for char in filename):
        raise ValidationError()

    content = upload.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise RequestEntityTooLarge()
    if not content:
        raise ValidationError()

    if Path(filename).suffix.lower() == ".zip":
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise ValidationError()
    else:
        _validate_document(filename, content)

    # Hash để phát hiện cùng key nhưng khác dữ liệu.
    request_hash = submission_hash(course_id, assignment_id, filename, content)
    scope = (g.actor["id"], course_id, assignment_id, key)

    path = None
    previous = None

    try:
        with _records(course_id) as records:
            assignment = records.get("assignments", assignment_id)

            # Nếu đã xử lý thao tác này thì trả kết quả cũ.
            saved = find_response(records.connection, scope, request_hash)
            if saved is not None:
                response = jsonify(saved["response_body"])
                response.status_code = saved["response_status"]
                response.headers["Idempotency-Replayed"] = "true"
                return response

            # Chỉ thao tác mới mới cần kiểm tra hạn và ghi bài.
            if time.time() >= assignment["deadline"]:
                raise AssessmentConflict("ASSIGNMENT_CLOSED")

            existing = records.list(
                "submissions",
                parent_id=assignment_id,
                student_id=g.actor["id"],
            )
            if existing:
                previous = existing[0]["storageName"]

            storage_name = secrets.token_hex(16)
            path = _file_path(storage_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as file:
                file.write(content)

            item = _new(
                course_id,
                parentId=assignment_id,
                studentId=g.actor["id"],
                fileName=filename,
                storageName=storage_name,
                size=len(content),
                submittedAt=_iso(time.time()),
                score=None,
                feedback="",
            )
            if existing:
                item["id"] = existing[0]["id"]

            # Bài nộp và kết quả idempotency dùng cùng transaction.
            records.save("submissions", item)
            result = _submission_public(item)
            save_response(records.connection, scope, request_hash, result)

    except Exception:
        # Nếu xử lý thất bại, dọn file vừa tạo.
        if path is not None:
            path.unlink(missing_ok=True)
        raise

    # Chỉ xóa file cũ sau khi transaction thành công.
    if previous:
        remove_submission_files([previous])

    _audit("SUBMIT_ASSIGNMENT")
    return jsonify(result), 201


@bp.get("/courses/<course_id>/assignments/<assignment_id>/submissions")
def list_submissions(course_id, assignment_id):
    _authorize(course_id)
    with _records(course_id) as records:
        records.get("assignments", assignment_id)
        items = records.list(
            "submissions",
            parent_id=assignment_id,
            student_id=g.actor["id"] if g.actor["role"] == "STUDENT" else None,
        )
        result = [_submission_public(item) for item in items]
    return jsonify(result)


@bp.get("/courses/<course_id>/submissions/<submission_id>/download")
def download_submission(course_id, submission_id):
    _authorize(course_id)
    with _records(course_id) as records:
        item = records.get("submissions", submission_id)
        _submission_access(item)
    try:
        content = _file_path(item["storageName"]).read_bytes()
    except FileNotFoundError as exc:
        raise NotFound() from exc
    return send_file(
        io.BytesIO(content),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=item["fileName"],
        conditional=False,
    )


@bp.put("/courses/<course_id>/submissions/<submission_id>/grade")
@require_role("INSTRUCTOR")
def grade_submission(course_id, submission_id):
    _authorize(course_id, manage=True)
    data = _json()
    if set(data) - {"score", "feedback"}:
        raise ValidationError()
    score = data.get("score")
    if (
        type(score) not in (int, float)
        or not math.isfinite(score)
        or not 0 <= score <= 10
    ):
        raise ValidationError()
    feedback = _text(data.get("feedback", ""), 4000)
    with _records(course_id) as records:
        item = records.get("submissions", submission_id)
        old_score = item["score"]
        item.update(
            score=score,
            feedback=feedback,
            gradedAt=_iso(time.time()),
            gradedBy=g.actor["id"],
        )
        records.save("submissions", item)
    write_audit(
        g.actor["id"],
        "GRADE_SUBMISSION",
        request.path,
        "SUCCESS",
        old_score=old_score,
        new_score=score,
    )
    return jsonify(_submission_public(item))


def _quiz_public(quiz, *, questions=False, answer_key=False):
    result = {
        key: quiz[key]
        for key in ("id", "courseId", "title", "durationSeconds", "maxAttempts")
    }
    result["questionCount"] = len(quiz["questions"])
    if questions:
        result["questions"] = [
            {
                key: value
                for key, value in question.items()
                if answer_key or key != "correctIndex"
            }
            for question in quiz["questions"]
        ]
    return result


@bp.post("/courses/<course_id>/quizzes")
@require_role("INSTRUCTOR")
def create_quiz(course_id):
    _authorize(course_id, manage=True)
    data = _json()
    if set(data) != {"title", "durationSeconds", "maxAttempts", "questions"}:
        raise ValidationError()
    title = _text(data["title"], 200, required=True)
    duration, limit, questions = (
        data["durationSeconds"],
        data["maxAttempts"],
        data["questions"],
    )
    if (
        type(duration) is not int
        or not 30 <= duration <= 10800
        or type(limit) is not int
        or not 1 <= limit <= 10
        or not isinstance(questions, list)
        or not 1 <= len(questions) <= 100
    ):
        raise ValidationError()
    normalized = []
    for question in questions:
        if not isinstance(question, dict) or set(question) != {
            "prompt",
            "choices",
            "correctIndex",
        }:
            raise ValidationError()
        choices, correct = question["choices"], question["correctIndex"]
        if (
            not isinstance(choices, list)
            or not 2 <= len(choices) <= 6
            or type(correct) is not int
            or not 0 <= correct < len(choices)
        ):
            raise ValidationError()
        normalized.append(
            {
                "id": secrets.token_hex(8),
                "prompt": _text(question["prompt"], 2000, required=True),
                "choices": [_text(value, 500, required=True) for value in choices],
                "correctIndex": correct,
            }
        )
    quiz = _new(
        course_id,
        title=title,
        durationSeconds=duration,
        maxAttempts=limit,
        questions=normalized,
    )
    with _records(course_id) as records:
        records.save("quizzes", quiz)
    _audit("CREATE_QUIZ")
    return jsonify(_quiz_public(quiz, questions=True, answer_key=True)), 201


@bp.get("/courses/<course_id>/quizzes")
def quizzes(course_id):
    _authorize(course_id)
    with _records(course_id) as records:
        result = [_quiz_public(quiz) for quiz in records.list("quizzes")]
    return jsonify(result)


@bp.get("/courses/<course_id>/quizzes/<quiz_id>")
def quiz_detail(course_id, quiz_id):
    _authorize(course_id)
    with _records(course_id) as records:
        quiz = records.get("quizzes", quiz_id)
        teacher = g.actor["role"] != "STUDENT"
        result = _quiz_public(quiz, questions=teacher, answer_key=teacher)
    return jsonify(result)


def _finish(records, attempt, *, expired=False):
    correct = sum(
        attempt["answers"].get(question["id"]) == question["correctIndex"]
        for question in attempt["questions"]
    )
    attempt.update(
        status="EXPIRED" if expired else "SUBMITTED",
        score=round(10 * correct / len(attempt["questions"]), 2),
        finishedAt=_iso(min(time.time(), attempt["deadline"])),
    )
    records.save("quiz_attempts", attempt)


def _expire(records, attempt):
    if attempt["status"] == "IN_PROGRESS" and time.time() >= attempt["deadline"]:
        _finish(records, attempt, expired=True)


def _attempt_public(attempt):
    return {
        **{
            key: attempt[key]
            for key in (
                "id",
                "courseId",
                "studentId",
                "startedAt",
                "expiresAt",
                "status",
                "score",
                "answers",
            )
        },
        "quizId": attempt["parentId"],
        "serverNow": time.time(),
        "questions": [
            {key: value for key, value in question.items() if key != "correctIndex"}
            for question in attempt["questions"]
        ],
    }


@bp.post("/courses/<course_id>/quizzes/<quiz_id>/attempts")
@require_role("STUDENT")
def start_attempt(course_id, quiz_id):
    _authorize(course_id)
    with _records(course_id) as records:
        quiz = records.get("quizzes", quiz_id)
        attempts = records.list(
            "quiz_attempts", parent_id=quiz_id, student_id=g.actor["id"]
        )
        for attempt in attempts:
            _expire(records, attempt)
            if attempt["status"] == "IN_PROGRESS":
                return jsonify(_attempt_public(attempt)), 200
        if len(attempts) >= quiz["maxAttempts"]:
            return jsonify({"error": "ATTEMPT_LIMIT_REACHED"}), 409
        now = time.time()
        attempt = _new(
            course_id,
            parentId=quiz_id,
            studentId=g.actor["id"],
            startedAt=_iso(now),
            expiresAt=_iso(now + quiz["durationSeconds"]),
            deadline=now + quiz["durationSeconds"],
            status="IN_PROGRESS",
            score=None,
            answers={},
            questions=copy.deepcopy(quiz["questions"]),
        )
        records.save("quiz_attempts", attempt)
    _audit("START_QUIZ_ATTEMPT")
    return jsonify(_attempt_public(attempt)), 201


def _own_attempt(records, attempt_id):
    attempt = records.get("quiz_attempts", attempt_id)
    if g.actor["role"] == "STUDENT" and attempt["studentId"] != g.actor["id"]:
        raise Forbidden()
    _expire(records, attempt)
    return attempt


def _answers(data, attempt):
    if set(data) != {"answers"} or not isinstance(data["answers"], dict):
        raise ValidationError()
    questions = {question["id"]: question for question in attempt["questions"]}
    for question_id, answer in data["answers"].items():
        if (
            question_id not in questions
            or type(answer) is not int
            or not 0 <= answer < len(questions[question_id]["choices"])
        ):
            raise ValidationError()
    return data["answers"]


@bp.get("/courses/<course_id>/quizzes/<quiz_id>/attempts")
def attempts(course_id, quiz_id):
    _authorize(course_id)
    with _records(course_id) as records:
        records.get("quizzes", quiz_id)
        items = records.list(
            "quiz_attempts",
            parent_id=quiz_id,
            student_id=g.actor["id"] if g.actor["role"] == "STUDENT" else None,
        )
        for attempt in items:
            _expire(records, attempt)
        result = [_attempt_public(attempt) for attempt in items]
    return jsonify(result)


@bp.get("/courses/<course_id>/quiz-attempts/<attempt_id>")
def attempt_detail(course_id, attempt_id):
    _authorize(course_id)
    with _records(course_id) as records:
        attempt = _own_attempt(records, attempt_id)
        result = _attempt_public(attempt)
    return jsonify(result)


@bp.put("/courses/<course_id>/quiz-attempts/<attempt_id>/answers")
@require_role("STUDENT")
def save_answers(course_id, attempt_id):
    _authorize(course_id)
    data = _json()
    with _records(course_id) as records:
        attempt = _own_attempt(records, attempt_id)
        if attempt["status"] != "IN_PROGRESS":
            return jsonify({"error": "ATTEMPT_CLOSED"}), 409
        attempt["answers"].update(_answers(data, attempt))
        records.save("quiz_attempts", attempt)
        result = _attempt_public(attempt)
    return jsonify(result)


@bp.post("/courses/<course_id>/quiz-attempts/<attempt_id>/submit")
@require_role("STUDENT")
def submit_attempt(course_id, attempt_id):
    _authorize(course_id)
    data = _json()
    with _records(course_id) as records:
        attempt = _own_attempt(records, attempt_id)
        if attempt["status"] == "IN_PROGRESS":
            attempt["answers"].update(_answers(data, attempt))
            _finish(records, attempt)
        result = _attempt_public(attempt)
    _audit("SUBMIT_QUIZ_ATTEMPT")
    return jsonify(result)


@bp.get("/courses/<course_id>/results")
@require_role("STUDENT")
def my_results(course_id):
    _authorize(course_id)
    with _records(course_id) as records:
        submissions = {
            item["parentId"]: item
            for item in records.list("submissions", student_id=g.actor["id"])
        }
        assignment_results = [
            {
                "id": item["id"],
                "title": item["title"],
                "submission": _submission_public(submissions[item["id"]])
                if item["id"] in submissions
                else None,
            }
            for item in records.list("assignments")
        ]
        quiz_results = []
        for quiz in records.list("quizzes"):
            items = records.list(
                "quiz_attempts", parent_id=quiz["id"], student_id=g.actor["id"]
            )
            for attempt in items:
                _expire(records, attempt)
            scores = [
                attempt["score"] for attempt in items if attempt["score"] is not None
            ]
            quiz_results.append(
                {
                    "id": quiz["id"],
                    "title": quiz["title"],
                    "bestScore": max(scores) if scores else None,
                    "attemptsUsed": len(items),
                    "maxAttempts": quiz["maxAttempts"],
                }
            )
    return jsonify({"assignments": assignment_results, "quizzes": quiz_results})
