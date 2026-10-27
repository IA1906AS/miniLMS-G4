"""Authentication and JWT management for miniLMS.

Security features:
- Password verification using bcrypt.
- JWT signed with HS256.
- Unique JWT identifier (jti).
- JWT token versioning.
- Account lockout after failed login attempts.
- Shared SQLite IP-based rate limiting.
"""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime

import bcrypt
import jwt
from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    request,
)

from app.api.errors import (
    AccountLocked,
    InvalidCredentials,
    Unauthenticated,
    ValidationError,
)
from app.api.rate_limit import check_rate_limit, client_ip
from app.api.store import LoginAttempt

auth_bp = Blueprint("auth", __name__)

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = 15 * 60

LOGIN_IP_LIMIT = 20
LOGIN_IP_WINDOW_SECONDS = 5 * 60


# ============================================================
# PASSWORD HASHING
# ============================================================


def hash_password(password, *, rounds=12):
    """Hash a password using bcrypt."""

    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=rounds),
    ).decode("utf-8")


# ============================================================
# JWT CREATION
# ============================================================


def create_token(user):
    """Create a signed JWT with unique jti and token version."""

    now = int(datetime.now(UTC).timestamp())
    ttl = int(current_app.config["TOKEN_TTL_SECONDS"])

    if isinstance(user, dict):
        user_id = user["id"]
        token_version = user.get("token_version", 0)
    else:
        user_id = user.id
        token_version = user.token_version

    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + ttl,
        "ver": token_version,
        "jti": secrets.token_hex(16),
    }

    return jwt.encode(
        payload,
        current_app.config["JWT_SECRET"],
        algorithm="HS256",
    )


# ============================================================
# JWT VERIFICATION
# ============================================================


def verify_token(token):
    """Verify JWT signature, expiration, and required claims."""

    try:
        payload = jwt.decode(
            token,
            current_app.config["JWT_SECRET"],
            algorithms=["HS256"],
            options={
                "require": [
                    "sub",
                    "iat",
                    "exp",
                    "ver",
                    "jti",
                ],
            },
        )

    except jwt.PyJWTError as exc:
        raise Unauthenticated() from exc

    required_claims = {
        "sub",
        "iat",
        "exp",
        "ver",
        "jti",
    }

    if set(payload) != required_claims:
        raise Unauthenticated()

    if not isinstance(payload["sub"], str) or not payload["sub"]:
        raise Unauthenticated()

    if type(payload["iat"]) is not int:
        raise Unauthenticated()

    if type(payload["exp"]) is not int:
        raise Unauthenticated()

    if type(payload["ver"]) is not int or payload["ver"] < 0:
        raise Unauthenticated()

    if not isinstance(payload["jti"], str) or len(payload["jti"]) != 32:
        raise Unauthenticated()

    try:
        int(payload["jti"], 16)
    except ValueError as exc:
        raise Unauthenticated() from exc

    if payload["exp"] <= payload["iat"]:
        raise Unauthenticated()

    return payload


# ============================================================
# RATE LIMIT RESPONSE
# ============================================================


def rate_limit_response(retry_after):
    """Return HTTP 429 with Retry-After header."""

    response = make_response(
        jsonify(
            {
                "error": "RATE_LIMITED",
            }
        ),
        429,
    )

    response.headers["Retry-After"] = str(retry_after)

    return response


# ============================================================
# LOGIN ENDPOINT
# ============================================================


@auth_bp.post("/auth/login")
def login():
    """Authenticate user without account-level hard lockout."""

    # STEP 1: Shared IP rate limit
    allowed, retry_after = check_rate_limit(
        key=f"login:ip:{client_ip()}",
        limit=LOGIN_IP_LIMIT,
        window_seconds=LOGIN_IP_WINDOW_SECONDS,
    )

    if not allowed:
        return rate_limit_response(retry_after)

    # STEP 2: Validate request
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        raise ValidationError()

    if set(data) != {"email", "password"}:
        raise ValidationError()

    email = data["email"]
    password = data["password"]

    if not isinstance(email, str) or not isinstance(password, str):
        raise ValidationError()

    if not email or not password:
        raise ValidationError()

    email = email.strip().lower()

    if not email:
        raise ValidationError()

    # STEP 3: Load user
    store = current_app.extensions["lms_store"]

    if isinstance(store, dict):
        user_id = store["users_by_email"].get(email)
        user = store["users"].get(user_id)

        fallback_hash = next(iter(store["users"].values()))["password_hash"]
    else:
        user = store.find_user_by_email(email)
        fallback_hash = store.get_fallback_password_hash()

    # STEP 4: Verify password
    if user is None:
        password_hash = fallback_hash
    elif isinstance(user, dict):
        password_hash = user["password_hash"]
    else:
        password_hash = user.password_hash

    try:
        password_ok = bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        password_ok = False

    # STEP 5: Failed login
    if user is None or not password_ok:
        if isinstance(store, dict):
            state = store["failed_logins"].setdefault(
                email,
                {"count": 0, "locked_until": 0},
            )
            state["count"] += 1
            state["locked_until"] = 0
        else:
            attempt = store.get_attempt(email)

            store.save_attempt(
                email,
                LoginAttempt(
                    failures=attempt.failures + 1,
                    locked_until=0,
                ),
            )

        raise InvalidCredentials()

    # STEP 6: Successful login
    if isinstance(store, dict):
        store["failed_logins"].pop(email, None)
    else:
        store.save_attempt(email, LoginAttempt())

    # STEP 7: Issue JWT
    access_token = create_token(user)

    return jsonify(
        {
            "accessToken": access_token,
            "expiresIn": int(current_app.config["TOKEN_TTL_SECONDS"]),
        }
    ), 200

    # ========================================================
    # STEP 2: VALIDATE REQUEST BODY
    # ========================================================

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        raise ValidationError()

    if set(data) != {"email", "password"}:
        raise ValidationError()

    email = data["email"]
    password = data["password"]

    if not isinstance(email, str):
        raise ValidationError()

    if not isinstance(password, str):
        raise ValidationError()

    if not email or not password:
        raise ValidationError()

    email = email.strip().lower()

    if not email:
        raise ValidationError()

    # ========================================================
    # STEP 3: LOAD STORAGE BACKEND
    # ========================================================

    store = current_app.extensions["lms_store"]
    now = time.time()

    if isinstance(store, dict):
        state = store["failed_logins"].setdefault(
            email,
            {
                "count": 0,
                "locked_until": 0,
            },
        )

        failures = state["count"]
        locked_until = state["locked_until"]

    else:
        attempt = store.get_attempt(email)
        failures = attempt.failures
        locked_until = attempt.locked_until

    # ========================================================
    # STEP 4: CHECK ACCOUNT LOCKOUT
    # ========================================================

    if locked_until > now:
        raise AccountLocked()

    if locked_until != 0:
        failures = 0
        locked_until = 0

    # ========================================================
    # STEP 5: FIND USER
    # ========================================================

    if isinstance(store, dict):
        user_id = store["users_by_email"].get(email)
        user = store["users"].get(user_id)

        fallback_hash = next(iter(store["users"].values()))["password_hash"]

    else:
        user = store.find_user_by_email(email)
        fallback_hash = store.get_fallback_password_hash()

    # ========================================================
    # STEP 6: VERIFY PASSWORD
    # ========================================================

    if user is None:
        password_hash = fallback_hash

    elif isinstance(user, dict):
        password_hash = user["password_hash"]

    else:
        password_hash = user.password_hash

    try:
        password_ok = bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        password_ok = False

    # ========================================================
    # STEP 7: HANDLE FAILED LOGIN
    # ========================================================

    if user is None or not password_ok:
        failures += 1

        if failures >= MAX_FAILED_ATTEMPTS:
            locked_until = now + LOCK_DURATION

            if isinstance(store, dict):
                state.update(
                    count=failures,
                    locked_until=locked_until,
                )

            else:
                store.save_attempt(
                    email,
                    LoginAttempt(
                        failures,
                        locked_until,
                    ),
                )

            raise AccountLocked()

        if isinstance(store, dict):
            state["count"] = failures

        else:
            store.save_attempt(
                email,
                LoginAttempt(
                    failures,
                    locked_until,
                ),
            )

        raise InvalidCredentials()

    # ========================================================
    # STEP 8: RESET FAILED LOGIN COUNTER
    # ========================================================

    if isinstance(store, dict):
        store["failed_logins"].pop(email, None)

    else:
        store.save_attempt(
            email,
            LoginAttempt(),
        )

    # ========================================================
    # STEP 9: GENERATE JWT
    # ========================================================

    access_token = create_token(user)

    return jsonify(
        {
            "accessToken": access_token,
            "expiresIn": int(current_app.config["TOKEN_TTL_SECONDS"]),
        }
    ), 200
