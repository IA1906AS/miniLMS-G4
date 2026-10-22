"""Reset password — tính năng thứ hai của bảng yêu cầu.

Luồng: ``POST /auth/forgot-password`` phát token dùng một lần (TTL ngắn), sau đó
``POST /auth/reset-password`` đổi mật khẩu. Không có email server nên token được
in ra response **chỉ khi** ``RESET_TOKEN_ECHO=1`` (môi trường demo) và không bao
giờ ghi vào audit log.
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
    return current_app.extensions["lms_store"]


@bp.post("/auth/forgot-password")
def forgot_password() -> tuple[Response, int]:
    email = validate_reset_request(request.get_json(silent=True))
    store = _store()
    cfg = current_app.config

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
            store.add_reset_token(token, user_id, int(cfg["RESET_TOKEN_TTL_SECONDS"]))
        if bool(cfg["RESET_TOKEN_ECHO"]):
            payload["resetToken"] = token

    # Luôn trả cùng một phản hồi để không dò được email có tồn tại hay không.
    return jsonify(payload), 202


@bp.post("/auth/reset-password")
def reset_password() -> Response:
    token, password = validate_reset_confirm(request.get_json(silent=True))
    store = _store()

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

    password_hash = hash_password(
        password, rounds=int(current_app.config["BCRYPT_ROUNDS"])
    )
    if isinstance(store, dict):
        store["users"][user_id]["password_hash"] = password_hash
    else:
        store.update_password(user_id, password_hash)
    write_audit(
        actor_id=user_id,
        action="RESET_PASSWORD",
        resource=f"users/{user_id}/password",
        result="SUCCESS",
    )
    return jsonify({"status": "password-updated"})
