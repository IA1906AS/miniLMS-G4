"""Password reset endpoints with local email simulation.

Security features:
- Shared SQLite rate limiting.
- Account enumeration protection.
- Cryptographically secure reset tokens.
- SHA-256 reset token storage.
- One-time reset token usage.
- Atomic password reset for SQLite.
- JWT invalidation after password reset.
- Thread-safe Memory backend.
- Local email simulation for development.
"""

from __future__ import annotations

import hashlib
import secrets
import time

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    make_response,
    request,
)

from app.api.audit import write_audit
from app.api.auth import hash_password
from app.api.errors import ValidationError
from app.api.local_mail import send_reset_email
from app.api.rate_limit import check_rate_limit, client_ip
from app.api.schemas import (
    validate_reset_confirm,
    validate_reset_request,
)

bp = Blueprint("reset", __name__)

TOKEN_BYTES = 32

RATE_LIMIT_WINDOW_SECONDS = 15 * 60

FORGOT_EMAIL_LIMIT = 3
FORGOT_IP_LIMIT = 10
RESET_IP_LIMIT = 5


# ============================================================
# RESET TOKEN HASHING
# ============================================================


def _token_digest(token: str) -> str:
    """Hash a reset token before storing or looking it up."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ============================================================
# STORAGE
# ============================================================


def _store():
    """Return the configured storage backend."""
    return current_app.extensions["lms_store"]


# ============================================================
# RATE LIMIT RESPONSE
# ============================================================


def _rate_limited(retry_after: int) -> Response:
    """Return HTTP 429 with Retry-After header."""
    response = make_response(
        jsonify({"error": "RATE_LIMITED"}),
        429,
    )

    response.headers["Retry-After"] = str(retry_after)

    return response


# ============================================================
# LOCAL EMAIL SIMULATION
# ============================================================


def _send_local_reset_email(
    email: str,
    token: str,
    user_id: str | None,
) -> None:
    """Simulate reset email only in explicitly enabled local debug mode."""

    cfg = current_app.config

    if user_id is None:
        return

    if not cfg.get("LOCAL_EMAIL_ENABLED", False):
        return

    if not current_app.debug:
        return

    if cfg.get("TESTING", False):
        return

    # Local email is stored in instance/mailbox/.
    # Never return the token in the HTTP response.
    try:
        send_reset_email(email, token)
    except OSError:
        # Avoid leaking mailbox failures to API clients.
        current_app.logger.exception("Unable to write local reset email.")


# ============================================================
# FORGOT PASSWORD
# ============================================================


@bp.post("/auth/forgot-password")
def forgot_password() -> tuple[Response, int] | Response:
    """Handle password reset requests without revealing account existence."""

    # STEP 1: VALIDATE REQUEST
    email = validate_reset_request(request.get_json(silent=True))

    cfg = current_app.config
    store = _store()

    # STEP 2: SHARED IP RATE LIMIT
    ip_allowed, ip_retry_after = check_rate_limit(
        key=f"forgot:ip:{client_ip()}",
        limit=FORGOT_IP_LIMIT,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    )

    # STEP 3: SHARED EMAIL RATE LIMIT
    email_allowed, email_retry_after = check_rate_limit(
        key=f"forgot:email:{email}",
        limit=FORGOT_EMAIL_LIMIT,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    )

    if not ip_allowed or not email_allowed:
        return _rate_limited(max(ip_retry_after, email_retry_after))

    # STEP 4: LOOK UP ACCOUNT
    if isinstance(store, dict):
        user_id = store["users_by_email"].get(email)
    else:
        user = store.find_user_by_email(email)
        user_id = user.id if user is not None else None

    # STEP 5: GENERATE TOKEN FOR BOTH CASES
    # Reduces timing differences between known and unknown emails.
    token = secrets.token_urlsafe(TOKEN_BYTES)
    token_hash = _token_digest(token)

    ttl = int(cfg["RESET_TOKEN_TTL_SECONDS"])

    # STEP 6: STORE TOKEN ONLY FOR EXISTING ACCOUNTS
    if user_id is not None:
        if isinstance(store, dict):
            with current_app.extensions["lms_reset_lock"]:
                current_app.extensions["lms_reset_tokens"][token_hash] = (
                    user_id,
                    time.time() + ttl,
                )
        else:
            store.add_reset_token(
                token_hash,
                user_id,
                ttl,
            )

    # STEP 7: LOCAL EMAIL SIMULATION
    # Enabled only for local development.
    _send_local_reset_email(
        email=email,
        token=token,
        user_id=user_id,
    )

    # STEP 8: GENERIC RESPONSE
    # Same response for existing and nonexistent emails.
    payload: dict[str, object] = {"status": "sent"}

    # Token echo is allowed only in automated tests.
    if (
        user_id is not None
        and bool(cfg.get("TESTING"))
        and bool(cfg.get("RESET_TOKEN_ECHO"))
    ):
        payload["resetToken"] = token

    return jsonify(payload), 202


# ============================================================
# RESET PASSWORD
# ============================================================


@bp.post("/auth/reset-password")
def reset_password() -> Response | tuple[Response, int]:
    """Reset password and invalidate previously issued JWTs."""

    # STEP 1: SHARED IP RATE LIMIT
    allowed, retry_after = check_rate_limit(
        key=f"reset:ip:{client_ip()}",
        limit=RESET_IP_LIMIT,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    )

    if not allowed:
        return _rate_limited(retry_after)

    # STEP 2: VALIDATE REQUEST
    token, password = validate_reset_confirm(request.get_json(silent=True))

    token_hash = _token_digest(token)
    store = _store()

    # STEP 3: HASH PASSWORD BEFORE CONSUMING TOKEN
    password_hash = hash_password(
        password,
        rounds=int(current_app.config["BCRYPT_ROUNDS"]),
    )

    # STEP 4: ATOMIC PASSWORD RESET
    if isinstance(store, dict):
        reset_tokens = current_app.extensions["lms_reset_tokens"]

        with current_app.extensions["lms_reset_lock"]:
            record = reset_tokens.get(token_hash)

            if record is None or record[1] <= time.time():
                raise ValidationError("token không hợp lệ hoặc đã hết hạn")

            user_id = record[0]
            user = store["users"].get(user_id)

            if user is None:
                raise ValidationError("token không hợp lệ hoặc đã hết hạn")

            user["password_hash"] = password_hash
            user["token_version"] = user.get("token_version", 0) + 1

            del reset_tokens[token_hash]

    else:
        user_id = store.reset_password_atomic(
            token_hash,
            password_hash,
        )

        if user_id is None:
            raise ValidationError("token không hợp lệ hoặc đã hết hạn")

    # STEP 5: AUDIT LOG
    write_audit(
        actor_id=user_id,
        action="RESET_PASSWORD",
        resource=f"users/{user_id}/password",
        result="SUCCESS",
    )

    return jsonify({"status": "password-updated"})
