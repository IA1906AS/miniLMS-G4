import math

from app.errors import ValidationError


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
