import math

from app.api.errors import (
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
    course = (
        store["courses"].get(course_id)
        if isinstance(store, dict)
        else store.get_course(course_id)
    )

    if course is None:
        raise NotFound()

    return course


def _get_actor(store, actor):
    user = (
        store["users"].get(actor.get("id"))
        if isinstance(store, dict)
        else store.get_user(actor.get("id"))
    )

    if user is None:
        raise Forbidden()

    role = user["role"] if isinstance(user, dict) else user.role
    if role != actor.get("role"):
        raise Forbidden()

    return user


# XEM DIEM
def get_grades(actor, course_id, *, store=None):
    store = _resolve_store(store)

    course = _get_course(store, course_id)
    user = _get_actor(store, actor)

    if isinstance(store, dict):
        enrollments = [
            item for item in store["enrollments"] if item["courseId"] == course_id
        ]
    else:
        enrollments = store.list_enrollments(course_id)

    role = user["role"] if isinstance(user, dict) else user.role

    if role == "ADMIN":
        allowed = enrollments

    elif role == "INSTRUCTOR":
        instructor_id = (
            course["instructorId"] if isinstance(course, dict) else course.instructor_id
        )
        user_id = user["id"] if isinstance(user, dict) else user.id
        if instructor_id != user_id:
            raise Forbidden()

        allowed = enrollments

    elif role == "STUDENT":
        user_id = user["id"] if isinstance(user, dict) else user.id
        allowed = [
            item
            for item in enrollments
            if (item["studentId"] if isinstance(item, dict) else item.student_id)
            == user_id
        ]

        if not allowed:
            raise Forbidden()

    else:
        raise Forbidden()

    return [
        {
            "studentId": item["studentId"]
            if isinstance(item, dict)
            else item.student_id,
            "score": item["score"] if isinstance(item, dict) else item.score,
        }
        for item in allowed
    ]


# CAP NHAT DIEM
def update_grade(actor, course_id, student_id, score, *, store=None):
    store = _resolve_store(store)

    course = _get_course(store, course_id)
    user = _get_actor(store, actor)

    # Chi giang vien day mon moi duoc sua diem
    role = user["role"] if isinstance(user, dict) else user.role
    instructor_id = (
        course["instructorId"] if isinstance(course, dict) else course.instructor_id
    )
    user_id = user["id"] if isinstance(user, dict) else user.id
    if role != "INSTRUCTOR" or instructor_id != user_id:
        raise Forbidden()

    # Service tu kiem tra du lieu
    if type(score) not in (int, float):
        raise ValidationError()

    if not math.isfinite(score):
        raise ValidationError()

    if not 0 <= score <= 10:
        raise ValidationError()

    # Kiem tra sinh vien co ghi danh khong
    if isinstance(store, dict):
        for item in store["enrollments"]:
            if item["courseId"] == course_id and item["studentId"] == student_id:
                item["score"] = score
                break
        else:
            raise NotFound()
    else:
        enrollment = store.get_enrollment(course_id, student_id)
        if enrollment is None:
            raise NotFound()
        store.set_score(course_id, student_id, score)

    return {
        "courseId": course_id,
        "studentId": student_id,
        "score": score,
    }
