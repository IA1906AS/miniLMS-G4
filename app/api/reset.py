"""Password reset endpoints for miniLMS.

POST /auth/forgot-password:
    Generate a one-time reset token.

POST /auth/reset-password:
    Update password and invalidate old JWT tokens.

RESET_TOKEN_ECHO is only intended for demo environments.
"""

from __future__ import annotations

import secrets
import time

from flask import Blueprint, Response, current_app, jsonify, request

from app.api.audit import write_audit
from app.api.auth import hash_password
from app.api.errors import ValidationError
from app.api.schemas import validate_reset_confirm, validate_reset_request

bp = Blueprint("reset", __name__)

TOKEN_BYTES = 32


def _store():
    """Return the configured LMS storage backend."""
    return current_app.extensions["lms_store"]


@bp.post("/auth/forgot-password")
def forgot_password() -> tuple[Response, int]:
    """Generate a one-time password reset token."""

    email = validate_reset_request(request.get_json(silent=True))

    store = _store()
    cfg = current_app.config

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
def reset_password() -> Response:
    """Reset password and invalidate previously issued JWTs."""

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

        # Invalidate all previously issued JWTs.
        # Use 0 as the default for older user records.
        user["token_version"] = user.get("token_version", 0) + 1

    else:
        # SQLite update_password() must increment
        # token_version in the same transaction.
        store.update_password(
            user_id,
            password_hash,
        )

    # ==========================================
    # STEP 4: Write security audit log
    # ==========================================

    write_audit(
        actor_id=user_id,
        action="RESET_PASSWORD",
        resource=f"users/{user_id}/password",
        result="SUCCESS",
    )

    # ==========================================
    # STEP 5: Return success response
    # ==========================================

    return jsonify({"status": "password-updated"})
