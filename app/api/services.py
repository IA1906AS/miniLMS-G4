import math
import sqlite3

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
    user = (
        store["users"].get(user_id)
        if isinstance(store, dict)
        else store.get_user(user_id)
    )

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
        }

    return {
        "studentId": item.student_id,
        "score": item.score,
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
def list_courses(*, store=None):
    store = _resolve_store(store)

    if isinstance(store, dict):
        courses = list(store["courses"].values())
    else:
        courses = store.list_courses()

    return [_course_to_dict(course) for course in courses]


# TAO KHOA HOC (ADMIN)
def create_course(actor, title, instructor_id, *, store=None):
    store = _resolve_store(store)
    user = _get_actor(store, actor)
    _require_admin(user)

    instructor = _get_user(store, instructor_id)
    if _role(instructor) != "INSTRUCTOR":
        raise ValidationError()

    if isinstance(store, dict):
        with store["course_lock"]:
            next_id = (
                max(
                    (
                        int(course_id[1:])
                        for course_id in store["courses"]
                        if course_id.startswith("c") and course_id[1:].isdigit()
                    ),
                    default=0,
                )
                + 1
            )
            course_id = f"c{next_id}"
            course = {"id": course_id, "title": title, "instructorId": instructor_id}
            store["courses"][course_id] = course
    else:
        course = store.create_course(title, instructor_id)

    return _course_to_dict(course)


# CAP NHAT KHOA HOC (ADMIN)
def update_course(actor, course_id, *, title=None, instructor_id=None, store=None):
    store = _resolve_store(store)
    user = _get_actor(store, actor)
    _require_admin(user)

    course = _get_course(store, course_id)

    if instructor_id is not None:
        instructor = _get_user(store, instructor_id)
        if _role(instructor) != "INSTRUCTOR":
            raise ValidationError()

    if isinstance(store, dict):
        with store["course_lock"]:
            if title is not None:
                course["title"] = title
            if instructor_id is not None:
                course["instructorId"] = instructor_id
        result = course
    else:
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

    if isinstance(store, dict):
        with store["course_lock"]:
            store["courses"].pop(course_id, None)
            store["enrollments"][:] = [
                item for item in store["enrollments"] if item["courseId"] != course_id
            ]
    else:
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

    if isinstance(store, dict):
        enrollments = [
            item for item in store["enrollments"] if item["courseId"] == course_id
        ]
    else:
        enrollments = store.list_enrollments(course_id)

    return [_enrollment_to_dict(item) for item in enrollments]


# THEM GHI DANH (ADMIN / GIANG VIEN DAY MON)
def add_enrollment(actor, course_id, student_id, *, store=None):
    store = _resolve_store(store)
    user = _get_actor(store, actor)
    course = _get_course(store, course_id)

    _require_course_manager(user, course)

    student = _get_user(store, student_id)
    if _role(student) != "STUDENT":
        raise ValidationError()

    if isinstance(store, dict):
        with store["course_lock"]:
            if any(
                item["courseId"] == course_id and item["studentId"] == student_id
                for item in store["enrollments"]
            ):
                raise ValidationError()

            enrollment = {"courseId": course_id, "studentId": student_id, "score": 0.0}
            store["enrollments"].append(enrollment)
    else:
        if store.get_enrollment(course_id, student_id) is not None:
            raise ValidationError()

        try:
            enrollment = store.add_enrollment(course_id, student_id, score=0.0)
        except sqlite3.IntegrityError as exc:
            raise ValidationError() from exc

    return _enrollment_to_dict(enrollment)


# XOA GHI DANH (ADMIN / GIANG VIEN DAY MON)
def remove_enrollment(actor, course_id, student_id, *, store=None):
    store = _resolve_store(store)
    user = _get_actor(store, actor)
    course = _get_course(store, course_id)

    _require_course_manager(user, course)

    if isinstance(store, dict):
        with store["course_lock"]:
            before = len(store["enrollments"])
            store["enrollments"][:] = [
                item
                for item in store["enrollments"]
                if not (
                    item["courseId"] == course_id and item["studentId"] == student_id
                )
            ]
            if len(store["enrollments"]) == before:
                raise NotFound()
    else:
        if store.get_enrollment(course_id, student_id) is None:
            raise NotFound()
        store.remove_enrollment(course_id, student_id)
