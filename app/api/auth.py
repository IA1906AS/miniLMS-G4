"""Authentication and JWT management for miniLMS.

Security features:
- Password verification using bcrypt.
- JWT signed with HS256.
- Unique JWT identifier (jti).
- JWT token versioning.
- Soft, time-limited account lockout after repeated failed logins.
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
        jsonify({"error": "RATE_LIMITED"}),
        429,
    )

    response.headers["Retry-After"] = str(retry_after)

    return response


# ============================================================
# ACCOUNT LOCKOUT RESPONSE
# ============================================================


def account_locked_response(retry_after):
    """Return HTTP 429 with Retry-After header for a locked account."""

    response = make_response(
        jsonify({"error": "ACCOUNT_LOCKED"}),
        429,
    )

    response.headers["Retry-After"] = str(retry_after)

    return response


# ============================================================
# ACCOUNT LOCKOUT STATE
# ============================================================


def _get_attempt(store, email):
    if isinstance(store, dict):
        return store["failed_logins"].setdefault(
            email,
            {"count": 0, "locked_until": 0},
        )

    return store.get_attempt(email)


def _save_attempt(store, email, failures, locked_until):
    if isinstance(store, dict):
        store["failed_logins"][email] = {
            "count": failures,
            "locked_until": locked_until,
        }
    else:
        store.save_attempt(
            email,
            LoginAttempt(
                failures=failures,
                locked_until=locked_until,
            ),
        )


def _reset_attempt(store, email):
    if isinstance(store, dict):
        store["failed_logins"].pop(email, None)
    else:
        store.save_attempt(email, LoginAttempt())


def _attempt_failures(attempt):
    return attempt["count"] if isinstance(attempt, dict) else attempt.failures


def _attempt_locked_until(attempt):
    return (
        attempt["locked_until"]
        if isinstance(attempt, dict)
        else attempt.locked_until
    )


# ============================================================
# LOGIN ENDPOINT
# ============================================================


@auth_bp.post("/auth/login")
def login():
    """Authenticate user and issue a signed JWT.

    Brute force is mitigated with a shared IP rate limit plus a soft,
    time-limited account lockout: an account is locked for a short window
    after too many failed attempts and then unlocks automatically.
    """

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

    store = current_app.extensions["lms_store"]
    now = time.time()

    max_attempts = int(current_app.config.get("LOGIN_MAX_FAILED_ATTEMPTS", 5))
    lock_seconds = int(current_app.config.get("LOGIN_LOCK_DURATION_SECONDS", 900))

    # STEP 3: Load per-account lockout state
    attempt = _get_attempt(store, email)
    failures = _attempt_failures(attempt)
    locked_until = _attempt_locked_until(attempt)

    # STEP 4: Enforce soft lockout
    if locked_until > now:
        return account_locked_response(max(1, int(locked_until - now)))

    if locked_until:
        failures = 0
        locked_until = 0

    # STEP 5: Load user (timing-safe fallback for unknown emails)
    if isinstance(store, dict):
        user_id = store["users_by_email"].get(email)
        user = store["users"].get(user_id)

        fallback_hash = next(iter(store["users"].values()))["password_hash"]
    else:
        user = store.find_user_by_email(email)
        fallback_hash = store.get_fallback_password_hash()

    # STEP 6: Verify password
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

    # STEP 7: Failed login -> increment counter, lock when threshold reached
    if user is None or not password_ok:
        failures += 1

        if failures >= max_attempts:
            locked_until = now + lock_seconds
            _save_attempt(store, email, failures, locked_until)
            return account_locked_response(lock_seconds)

        _save_attempt(store, email, failures, 0)
        raise InvalidCredentials()

    # STEP 8: Success -> reset counter
    _reset_attempt(store, email)

    # STEP 9: Issue JWT
    access_token = create_token(user)

    return jsonify(
        {
            "accessToken": access_token,
            "expiresIn": int(current_app.config["TOKEN_TTL_SECONDS"]),
        }
    ), 200
