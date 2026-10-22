"""Đăng ký tài khoản — tính năng thứ nhất của bảng yêu cầu."""

from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify, request

from app.api.auth import hash_password
from app.api.errors import ValidationError
from app.api.schemas import validate_register_body

bp = Blueprint("signup", __name__)


@bp.post("/auth/register")
def register() -> tuple[Response, int]:
    store = current_app.extensions["lms_store"]
    email, password = validate_register_body(request.get_json(silent=True))

    if isinstance(store, dict):
        existing_user = email in store["users_by_email"]
    else:
        existing_user = store.find_user_by_email(email) is not None
    if existing_user:
        raise ValidationError("email đã được đăng ký")

    password_hash = hash_password(
        password, rounds=int(current_app.config["BCRYPT_ROUNDS"])
    )
    if isinstance(store, dict):
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
        }
        store["users_by_email"][email] = user_id
    else:
        user = store.add_user(email=email, password_hash=password_hash, role="STUDENT")
        user_id = user.id

    return jsonify({"id": user_id, "email": email, "role": "STUDENT"}), 201
