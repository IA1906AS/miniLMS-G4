import math

from app.errors import (
    Forbidden,
    NotFound,
    ValidationError,
)

_default_store = None


def configure_store(store):
    global _default_store
    _default_store = store


def _resolve_store(store):
    if store is not None:
        return store

    if _default_store is None:
        raise RuntimeError("LMS store not configured")

    return _default_store


def _get_course(store, course_id):
    course = store["courses"].get(course_id)

    if course is None:
        raise NotFound()

    return course


def _get_actor(store, actor):
    user = store["users"].get(actor.get("id"))

    if user is None:
        raise Forbidden()

    if user["role"] != actor.get("role"):
        raise Forbidden()

    return user


# XEM DIEM
def get_grades(actor, course_id, *, store=None):
    store = _resolve_store(store)

    course = _get_course(store, course_id)
    user = _get_actor(store, actor)

    enrollments = [
        item for item in store["enrollments"] if item["courseId"] == course_id
    ]

    role = user["role"]

    if role == "ADMIN":
        allowed = enrollments

    elif role == "INSTRUCTOR":
        if course["instructorId"] != user["id"]:
            raise Forbidden()

        allowed = enrollments

    elif role == "STUDENT":
        allowed = [item for item in enrollments if item["studentId"] == user["id"]]

        if not allowed:
            raise Forbidden()

    else:
        raise Forbidden()

    return [
        {
            "studentId": item["studentId"],
            "score": item["score"],
        }
        for item in allowed
    ]


# CAP NHAT DIEM
def update_grade(actor, course_id, student_id, score, *, store=None):
    store = _resolve_store(store)

    course = _get_course(store, course_id)
    user = _get_actor(store, actor)

    # Chi giang vien day mon moi duoc sua diem
    if user["role"] != "INSTRUCTOR" or course["instructorId"] != user["id"]:
        raise Forbidden()

    # Service tu kiem tra du lieu
    if type(score) not in (int, float):
        raise ValidationError()

    if not math.isfinite(score):
        raise ValidationError()

    if not 0 <= score <= 10:
        raise ValidationError()

    # Kiem tra sinh vien co ghi danh khong
    for item in store["enrollments"]:
        if item["courseId"] == course_id and item["studentId"] == student_id:
            item["score"] = score

            return {
                "courseId": course_id,
                "studentId": student_id,
                "score": score,
            }

    raise NotFound()
