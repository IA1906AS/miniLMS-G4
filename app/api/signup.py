"""Student registration API for miniLMS.

Security features:
- Registration request validation.
- Shared PostgreSQL IP-based rate limiting.
- Duplicate email detection.
- bcrypt password hashing.
- STUDENT-only account creation.
- JWT token version initialization.
- PostgreSQL storage support.
"""

from __future__ import annotations

import psycopg
from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    make_response,
    request,
)

from app.api.auth import hash_password
from app.api.errors import ValidationError
from app.api.rate_limit import check_rate_limit, client_ip
from app.api.schemas import validate_register_body

bp = Blueprint("signup", __name__)

REGISTER_IP_LIMIT = 5
REGISTER_IP_WINDOW_SECONDS = 15 * 60


def rate_limit_response(retry_after: int) -> Response:
    """Return HTTP 429 with Retry-After header."""

    response = make_response(
        jsonify({"error": "RATE_LIMITED"}),
        429,
    )
    response.headers["Retry-After"] = str(retry_after)
    return response


@bp.post("/auth/register")
def register() -> tuple[Response, int] | Response:
    """Register a STUDENT account."""

    # STEP 1: Shared IP rate limit
    allowed, retry_after = check_rate_limit(
        key=f"register:ip:{client_ip()}",
        limit=REGISTER_IP_LIMIT,
        window_seconds=REGISTER_IP_WINDOW_SECONDS,
    )

    if not allowed:
        return rate_limit_response(retry_after)

    # STEP 2: Validate input
    email, password = validate_register_body(request.get_json(silent=True))

    store = current_app.extensions["lms_store"]

    # STEP 4: Hash password
    password_hash = hash_password(
        password,
        rounds=int(current_app.config["BCRYPT_ROUNDS"]),
    )

    # STEP 5: Create user safely
    try:
        user = store.add_user(
            email=email,
            password_hash=password_hash,
            role="STUDENT",
        )
    except psycopg.IntegrityError as exc:
        raise ValidationError("email đã được đăng ký") from exc

    user_id = user.id

    # STEP 6: Return response
    return jsonify(
        {
            "id": user_id,
            "email": email,
            "role": "STUDENT",
        }
    ), 201
