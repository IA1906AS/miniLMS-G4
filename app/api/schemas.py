import math

from app.api.errors import ValidationError


def validate_score_body(data):

    if not isinstance(data, dict):
        raise ValidationError()

    # Chi chap nhan duy nhat field score
    if set(data.keys()) != {"score"}:
        raise ValidationError()

    score = data["score"]

    if type(score) not in (int, float):
        raise ValidationError()

    if not math.isfinite(score):
        raise ValidationError()

    if not 0 <= score <= 10:
        raise ValidationError()

    return score


def validate_register_body(data):
    if not isinstance(data, dict) or set(data) != {"email", "password"}:
        raise ValidationError()

    email = data["email"]
    password = data["password"]

    if not isinstance(email, str) or not isinstance(password, str):
        raise ValidationError()

    email = email.strip().lower()
    if not email or "@" not in email or any(char.isspace() for char in email):
        raise ValidationError()

    password_bytes = password.encode("utf-8")
    if len(password_bytes) < 8 or len(password_bytes) > 72:
        raise ValidationError()

    return email, password


def validate_reset_request(data):
    if not isinstance(data, dict) or set(data) != {"email"}:
        raise ValidationError()

    email = data["email"]
    if not isinstance(email, str):
        raise ValidationError()

    email = email.strip().lower()
    if not email or "@" not in email or any(char.isspace() for char in email):
        raise ValidationError()

    return email


def validate_reset_confirm(data):
    if not isinstance(data, dict) or set(data) != {"token", "password"}:
        raise ValidationError()

    token = data["token"]
    password = data["password"]
    if not isinstance(token, str) or not token:
        raise ValidationError()
    if not isinstance(password, str):
        raise ValidationError()

    password_bytes = password.encode("utf-8")
    if len(password_bytes) < 8 or len(password_bytes) > 72:
        raise ValidationError()

    return token, password


def validate_course_body(data):
    if not isinstance(data, dict) or set(data) != {"title", "instructorId"}:
        raise ValidationError()

    title = data["title"]
    instructor_id = data["instructorId"]

    if not isinstance(title, str) or not title.strip():
        raise ValidationError()

    if not isinstance(instructor_id, str) or not instructor_id.strip():
        raise ValidationError()

    return title.strip(), instructor_id.strip()


def validate_course_update(data):
    if not isinstance(data, dict):
        raise ValidationError()

    if not data or set(data) - {"title", "instructorId"}:
        raise ValidationError()

    title = data.get("title")
    instructor_id = data.get("instructorId")

    if "title" in data and (not isinstance(title, str) or not title.strip()):
        raise ValidationError()

    if "instructorId" in data and (
        not isinstance(instructor_id, str) or not instructor_id.strip()
    ):
        raise ValidationError()

    return (
        title.strip() if isinstance(title, str) else None,
        instructor_id.strip() if isinstance(instructor_id, str) else None,
    )


def validate_enrollment_body(data):
    if not isinstance(data, dict) or set(data) != {"studentId"}:
        raise ValidationError()

    student_id = data["studentId"]
    if not isinstance(student_id, str) or not student_id.strip():
        raise ValidationError()

    return student_id.strip()
