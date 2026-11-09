"""Password reset endpoints with local email simulation.

Security features:
- Shared PostgreSQL rate limiting.
- Account enumeration protection.
- Cryptographically secure reset tokens.
- SHA-256 reset token storage.
- One-time reset token usage.
- Atomic password reset for PostgreSQL.
- JWT invalidation after password reset.
- Local email simulation for development.
"""

from __future__ import annotations

import hashlib
import secrets
import smtplib

import bcrypt
from flask import (
    Blueprint,
    Response,
    current_app,
    g,
    jsonify,
    make_response,
    request,
)

from app.api.audit import make_audit_record, write_audit, write_audit_file
from app.api.auth import hash_password
from app.api.errors import InvalidCredentials, ValidationError
from app.api.local_mail import send_reset_email
from app.api.mail import send_smtp_reset_email
from app.api.rate_limit import check_rate_limit, client_ip
from app.api.schemas import (
    validate_change_password,
    validate_reset_confirm,
    validate_reset_request,
)

bp = Blueprint("reset", __name__)


@bp.post("/auth/change-password")
def change_password():
    current, new = validate_change_password(request.get_json(silent=True))
    allowed, retry_after = check_rate_limit(
        key=f"change-password:user:{g.actor['id']}",
        limit=5,
        window_seconds=15 * 60,
    )
    if not allowed:
        return _rate_limited(retry_after)

    store = _store()
    user_id = g.actor["id"]
    user = store.get_user(user_id)
    old_hash = user.password_hash
    if not bcrypt.checkpw(current.encode("utf-8"), old_hash.encode("utf-8")):
        raise InvalidCredentials()

    new_hash = hash_password(new, rounds=int(current_app.config["BCRYPT_ROUNDS"]))
    if not store.change_password_atomic(user_id, old_hash, new_hash):
        raise InvalidCredentials()

    write_audit(
        actor_id=user_id,
        action="CHANGE_PASSWORD",
        resource=f"users/{user_id}/password",
        result="SUCCESS",
    )
    return jsonify({"status": "password-updated"})


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
    user = store.find_user_by_email(email)
    user_id = user.id if user is not None else None

    # STEP 5: GENERATE TOKEN FOR BOTH CASES
    # Reduces timing differences between known and unknown emails.
    token = secrets.token_urlsafe(TOKEN_BYTES)
    token_hash = _token_digest(token)

    ttl = int(cfg["RESET_TOKEN_TTL_SECONDS"])

    # STEP 6: STORE TOKEN ONLY FOR EXISTING ACCOUNTS
    if user_id is not None:
        store.add_reset_token(
            token_hash,
            user_id,
            ttl,
        )

    # Keep the public response generic even when delivery fails.
    if user_id is not None and cfg["SMTP_ENABLED"]:
        try:
            send_smtp_reset_email(email, token)
        except (OSError, smtplib.SMTPException):
            # SMTP exceptions can contain recipient addresses; do not log details.
            current_app.logger.error("Password reset email delivery failed.")
    else:
        _send_local_reset_email(email=email, token=token, user_id=user_id)

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
    audit_record = make_audit_record(
        None, "RESET_PASSWORD", "/auth/reset-password", "SUCCESS"
    )
    user_id = store.reset_password_atomic(
        token_hash,
        password_hash,
        audit_record=audit_record,
    )

    if user_id is None:
        raise ValidationError("token không hợp lệ hoặc đã hết hạn")

    # STEP 5: AUDIT LOG
    write_audit_file(audit_record)

    return jsonify({"status": "password-updated"})
