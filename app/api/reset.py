"""Password reset endpoints for miniLMS.

POST /auth/forgot-password:
    Generate a one-time reset token with rate limiting.

POST /auth/reset-password:
    Update password, invalidate old JWTs, and limit reset attempts.

RESET_TOKEN_ECHO is only intended for demo environments.
"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from threading import Lock

from flask import Blueprint, Response, current_app, jsonify, request

from app.api.audit import write_audit
from app.api.auth import hash_password
from app.api.errors import ValidationError
from app.api.schemas import validate_reset_confirm, validate_reset_request

bp = Blueprint("reset", __name__)

TOKEN_BYTES = 32

RATE_LIMIT_WINDOW_SECONDS = 15 * 60
FORGOT_EMAIL_LIMIT = 3
FORGOT_IP_LIMIT = 10
RESET_IP_LIMIT = 5

# Shared within this Python process.
# Production deployments should use a shared backend such as Redis.
_rate_limit_records: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_lock = Lock()


def _store():
    """Return the configured LMS storage backend."""
    return current_app.extensions["lms_store"]


def _client_ip() -> str:
    """Use the direct peer address, not an untrusted forwarded header."""
    return request.remote_addr or "unknown"


def _rate_limit_key(category: str, identifier: str) -> str:
    """Scope rate limits to the current application instance."""
    return f"{id(current_app._get_current_object())}:{category}:{identifier}"


def _check_rate_limit(
    category: str,
    identifier: str,
    limit: int,
) -> bool:
    """Atomically check and record an attempt within a sliding window."""
    now = time.monotonic()
    key = _rate_limit_key(category, identifier)

    with _rate_limit_lock:
        attempts = _rate_limit_records[key]
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS

        while attempts and attempts[0] <= cutoff:
            attempts.popleft()

        if len(attempts) >= limit:
            return False

        attempts.append(now)
        return True


def _rate_limited() -> tuple[Response, int]:
    """Return a consistent rate-limit response."""
    response = jsonify({"error": "RATE_LIMITED"})
    response.headers["Retry-After"] = str(RATE_LIMIT_WINDOW_SECONDS)
    return response, 429


@bp.post("/auth/forgot-password")
def forgot_password() -> tuple[Response, int]:
    """Generate a one-time password reset token with rate limiting."""

    email = validate_reset_request(request.get_json(silent=True))

    cfg = current_app.config
    store = _store()

    ip = _client_ip()

    # Apply both IP and email limits.
    # The limits are evaluated regardless of account existence.
    ip_allowed = _check_rate_limit(
        "forgot-ip",
        ip,
        FORGOT_IP_LIMIT,
    )
    email_allowed = _check_rate_limit(
        "forgot-email",
        email,
        FORGOT_EMAIL_LIMIT,
    )

    if not ip_allowed or not email_allowed:
        return _rate_limited()

    # Avoid revealing whether an email exists.
    payload: dict[str, object] = {"status": "sent"}

    if isinstance(store, dict):
        user_id = store["users_by_email"].get(email)
    else:
        user = store.find_user_by_email(email)
        user_id = user.id if user is not None else None

    if user_id is not None:
        token = secrets.token_urlsafe(TOKEN_BYTES)

        if isinstance(store, dict):
            current_app.extensions["lms_reset_tokens"][token] = (
                user_id,
                time.time() + int(cfg["RESET_TOKEN_TTL_SECONDS"]),
            )
        else:
            store.add_reset_token(
                token,
                user_id,
                int(cfg["RESET_TOKEN_TTL_SECONDS"]),
            )

        # Only expose the token in demo mode.
        if bool(cfg["RESET_TOKEN_ECHO"]):
            payload["resetToken"] = token

    return jsonify(payload), 202


@bp.post("/auth/reset-password")
def reset_password() -> Response | tuple[Response, int]:
    """Reset password and invalidate previously issued JWTs."""

    # Rate-limit attempts before processing reset tokens.
    if not _check_rate_limit(
        "reset-ip",
        _client_ip(),
        RESET_IP_LIMIT,
    ):
        return _rate_limited()

    token, password = validate_reset_confirm(request.get_json(silent=True))

    store = _store()

    # ==========================================
    # STEP 1: Validate and consume reset token
    # ==========================================

    if isinstance(store, dict):
        record = current_app.extensions["lms_reset_tokens"].pop(token, None)

        if record is None or record[1] < time.time():
            raise ValidationError("token không hợp lệ hoặc đã hết hạn")

        user_id = record[0]

    else:
        record = store.take_reset_token(token)

        if record is None:
            raise ValidationError("token không hợp lệ hoặc đã hết hạn")

        user_id = record.user_id

    if not user_id:
        raise ValidationError("token không hợp lệ hoặc đã hết hạn")

    # ==========================================
    # STEP 2: Hash the new password
    # ==========================================

    password_hash = hash_password(
        password,
        rounds=int(current_app.config["BCRYPT_ROUNDS"]),
    )

    # ==========================================
    # STEP 3: Update password and token version
    # ==========================================

    if isinstance(store, dict):
        user = store["users"].get(user_id)

        if user is None:
            raise ValidationError("token không hợp lệ hoặc đã hết hạn")

        user["password_hash"] = password_hash
        user["token_version"] = user.get("token_version", 0) + 1

    else:
        # SQLite update_password() increments token_version
        # in the same transaction.
        store.update_password(user_id, password_hash)

    # ==========================================
    # STEP 4: Write security audit log
    # ==========================================

    write_audit(
        actor_id=user_id,
        action="RESET_PASSWORD",
        resource=f"users/{user_id}/password",
        result="SUCCESS",
    )

    return jsonify({"status": "password-updated"})
