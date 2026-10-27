"""Student registration API for miniLMS.

Security features:
- Registration request validation.
- Shared SQLite IP-based rate limiting.
- Duplicate email detection.
- bcrypt password hashing.
- STUDENT-only account creation.
- JWT token version initialization.
- Memory and SQLite storage support.
"""

from __future__ import annotations

import sqlite3

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
    if isinstance(store, dict):
        with store["registration_lock"]:
            # Check and create within the same lock.
            if email in store["users_by_email"]:
                raise ValidationError("email đã được đăng ký")

            next_id = (
                max(
                    (
                        int(user_id[1:])
                        for user_id in store["users"]
                        if user_id.startswith("u") and user_id[1:].isdigit()
                    ),
                    default=0,
                )
                + 1
            )

            user_id = f"u{next_id}"

            store["users"][user_id] = {
                "id": user_id,
                "email": email,
                "role": "STUDENT",
                "password_hash": password_hash,
                "token_version": 0,
            }

            store["users_by_email"][email] = user_id

    else:
        try:
            user = store.add_user(
                email=email,
                password_hash=password_hash,
                role="STUDENT",
            )
        except sqlite3.IntegrityError as exc:
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
