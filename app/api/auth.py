"""Authentication and JWT management for miniLMS."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import bcrypt
import jwt
from flask import Blueprint, current_app, jsonify, request

from app.api.errors import (
    AccountLocked,
    InvalidCredentials,
    Unauthenticated,
    ValidationError,
)
from app.api.store import LoginAttempt

auth_bp = Blueprint("auth", __name__)

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = 15 * 60


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
    """Create a signed JWT with the user's token version."""

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
    """Verify JWT signature, expiry and required claims."""

    try:
        payload = jwt.decode(
            token,
            current_app.config["JWT_SECRET"],
            algorithms=["HS256"],
            options={
                "require": ["sub", "iat", "exp", "ver"],
            },
        )

    except jwt.PyJWTError as exc:
        raise Unauthenticated() from exc

    required_claims = {"sub", "iat", "exp", "ver"}

    if set(payload) != required_claims:
        raise Unauthenticated()

    if not isinstance(payload["sub"], str):
        raise Unauthenticated()

    if not payload["sub"]:
        raise Unauthenticated()

    if type(payload["iat"]) is not int:
        raise Unauthenticated()

    if type(payload["exp"]) is not int:
        raise Unauthenticated()

    if type(payload["ver"]) is not int:
        raise Unauthenticated()

    if payload["ver"] < 0:
        raise Unauthenticated()

    return payload


# ============================================================
# LOGIN ENDPOINT
# ============================================================


@auth_bp.post("/auth/login")
def login():
    """Authenticate user and issue a JWT."""

    # --------------------------------------------------------
    # STEP 1: Validate request body
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # STEP 2: Load storage backend
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # STEP 3: Check account lockout
    # --------------------------------------------------------

    if locked_until > now:
        raise AccountLocked()

    if locked_until != 0:
        failures = 0
        locked_until = 0

    # --------------------------------------------------------
    # STEP 4: Find user
    # --------------------------------------------------------

    if isinstance(store, dict):
        user_id = store["users_by_email"].get(email)
        user = store["users"].get(user_id)

        fallback_hash = next(iter(store["users"].values()))["password_hash"]

    else:
        user = store.find_user_by_email(email)
        fallback_hash = store.get_fallback_password_hash()

    # --------------------------------------------------------
    # STEP 5: Verify password
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # STEP 6: Handle failed login
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # STEP 7: Reset failed login counter
    # --------------------------------------------------------

    if isinstance(store, dict):
        store["failed_logins"].pop(email, None)
    else:
        store.save_attempt(
            email,
            LoginAttempt(),
        )

    # --------------------------------------------------------
    # STEP 8: Generate JWT
    # --------------------------------------------------------

    token = create_token(user)

    return jsonify(
        {
            "accessToken": token,
            "expiresIn": int(current_app.config["TOKEN_TTL_SECONDS"]),
        }
    ), 200
