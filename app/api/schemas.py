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
