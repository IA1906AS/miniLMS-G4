import math

import psycopg

from app.api.audit import make_audit_record, write_audit_file
from app.api.errors import (
    AlreadyEnrolled,
    Forbidden,
    GradeConflict,
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
    course = store.get_course(course_id)

    if course is None:
        raise NotFound()

    return course


def _get_actor(store, actor):
    user = store.get_user(actor.get("id"))

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
            "version": item["version"] if isinstance(item, dict) else item.version,
        }
        for item in allowed
    ]


# CAP NHAT DIEM
def update_grade(actor, course_id, student_id, score, *, version=None, store=None):
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
    enrollment = store.get_enrollment(course_id, student_id)
    if enrollment is None:
        raise NotFound()
    if type(version) is not int or not 0 <= version < 2147483647:
        raise ValidationError()
    audit_record = make_audit_record(
        user_id,
        "UPDATE_GRADE",
        f"/courses/{course_id}/grades/{student_id}",
        "SUCCESS",
        new_score=score,
    )
    new_version = store.set_score(
        course_id, student_id, score, version, audit_record=audit_record
    )
    if new_version is None:
        raise GradeConflict()
    write_audit_file(audit_record)

    return {
        "courseId": course_id,
        "studentId": student_id,
        "score": score,
        "version": new_version,
    }


# ============================================================
# HELPERS
# ============================================================


def _role(user):
    return user["role"] if isinstance(user, dict) else user.role


def _user_id(user):
    return user["id"] if isinstance(user, dict) else user.id


def _require_admin(user):
    if _role(user) != "ADMIN":
        raise Forbidden()


def _get_user(store, user_id):
    user = store.get_user(user_id)

    if user is None:
        raise ValidationError()

    return user


def _course_to_dict(course):
    if isinstance(course, dict):
        return {
            "id": course["id"],
            "title": course["title"],
            "instructorId": course["instructorId"],
        }

    return {
        "id": course.id,
        "title": course.title,
        "instructorId": course.instructor_id,
    }


def _enrollment_to_dict(item):
    if isinstance(item, dict):
        return {
            "studentId": item["studentId"],
            "score": item["score"],
            "version": item["version"],
        }

    return {
        "studentId": item.student_id,
        "score": item.score,
        "version": item.version,
    }


def _require_course_manager(user, course):
    role = _role(user)

    if role == "ADMIN":
        return

    if role == "INSTRUCTOR":
        instructor_id = (
            course["instructorId"] if isinstance(course, dict) else course.instructor_id
        )
        if instructor_id == _user_id(user):
            return

    raise Forbidden()


# ============================================================
# COURSE MANAGEMENT
# ============================================================


# LIET KE KHOA HOC
def list_courses(*, store=None, query="", instructor_id=""):
    store = _resolve_store(store)

    courses = store.list_courses()

    result = [_course_to_dict(course) for course in courses]
    return [
        course
        for course in result
        if query.casefold() in course["title"].casefold()
        and (not instructor_id or course["instructorId"] == instructor_id)
    ]


# TAO KHOA HOC (ADMIN / GIANG VIEN)
def create_course(actor, title, instructor_id, *, store=None):
    store = _resolve_store(store)
    user = _get_actor(store, actor)
    if _role(user) == "INSTRUCTOR":
        if instructor_id != _user_id(user):
            raise Forbidden()
    else:
        _require_admin(user)

    instructor = _get_user(store, instructor_id)
    if _role(instructor) != "INSTRUCTOR":
        raise ValidationError()

    course = store.create_course(title, instructor_id)

    return _course_to_dict(course)


# CAP NHAT KHOA HOC (ADMIN / GIANG VIEN PHU TRACH)
def update_course(actor, course_id, *, title=None, instructor_id=None, store=None):
    store = _resolve_store(store)
    user = _get_actor(store, actor)
    course = _get_course(store, course_id)
    _require_course_manager(user, course)
    if _role(user) == "INSTRUCTOR" and instructor_id not in (None, _user_id(user)):
        raise Forbidden()

    if instructor_id is not None:
        instructor = _get_user(store, instructor_id)
        if _role(instructor) != "INSTRUCTOR":
            raise ValidationError()

    result = store.update_course(
        course_id,
        title=title,
        instructor_id=instructor_id,
    )

    return _course_to_dict(result)


# XOA KHOA HOC (ADMIN)
def delete_course(actor, course_id, *, store=None):
    store = _resolve_store(store)
    user = _get_actor(store, actor)
    _require_admin(user)

    _get_course(store, course_id)

    store.delete_course(course_id)


# ============================================================
# ENROLLMENT MANAGEMENT
# ============================================================


# XEM DANH SACH GHI DANH (ADMIN / GIANG VIEN DAY MON)
def list_course_enrollments(actor, course_id, *, store=None):
    store = _resolve_store(store)
    user = _get_actor(store, actor)
    course = _get_course(store, course_id)

    _require_course_manager(user, course)

    enrollments = store.list_enrollments(course_id)

    return [_enrollment_to_dict(item) for item in enrollments]


# THEM GHI DANH (ADMIN / GIANG VIEN DAY MON)
def add_enrollment(actor, course_id, student_id, *, store=None, self_enroll=False):
    store = _resolve_store(store)
    user = _get_actor(store, actor)
    course = _get_course(store, course_id)

    if self_enroll:
        if _role(user) != "STUDENT" or student_id != _user_id(user):
            raise Forbidden()
    else:
        _require_course_manager(user, course)

    student = _get_user(store, student_id)
    if _role(student) != "STUDENT":
        raise ValidationError()

    if store.get_enrollment(course_id, student_id) is not None:
        if self_enroll:
            raise AlreadyEnrolled()
        raise ValidationError()

    try:
        enrollment = store.add_enrollment(course_id, student_id, score=0.0)
    except psycopg.IntegrityError as exc:
        if self_enroll:
            raise AlreadyEnrolled() from exc
        raise ValidationError() from exc

    return _enrollment_to_dict(enrollment)


# XOA GHI DANH (ADMIN / GIANG VIEN DAY MON)
def remove_enrollment(actor, course_id, student_id, *, store=None):
    store = _resolve_store(store)
    user = _get_actor(store, actor)
    course = _get_course(store, course_id)

    _require_course_manager(user, course)

    if store.get_enrollment(course_id, student_id) is None:
        raise NotFound()
    store.remove_enrollment(course_id, student_id)
