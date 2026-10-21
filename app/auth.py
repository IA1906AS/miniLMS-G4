import time
from datetime import UTC, datetime

import bcrypt
import jwt
from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
)

from app.errors import (
    AccountLocked,
    InvalidCredentials,
    Unauthenticated,
    ValidationError,
)

auth_bp = Blueprint("auth", __name__)

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = 15 * 60


def create_token(user):
    now = int(datetime.now(UTC).timestamp())

    ttl = int(current_app.config["TOKEN_TTL_SECONDS"])

    payload = {
        "sub": user["id"],
        "iat": now,
        "exp": now + ttl,
    }

    return jwt.encode(
        payload,
        current_app.config["JWT_SECRET"],
        algorithm="HS256",
    )


def verify_token(token):
    try:
        payload = jwt.decode(
            token,
            current_app.config["JWT_SECRET"],
            algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp"]},
        )

        if set(payload.keys()) != {"sub", "iat", "exp"}:
            raise Unauthenticated()

        if not isinstance(payload["sub"], str):
            raise Unauthenticated()

        if not payload["sub"]:
            raise Unauthenticated()

        if type(payload["iat"]) is not int:
            raise Unauthenticated()

        if type(payload["exp"]) is not int:
            raise Unauthenticated()

        return payload

    except jwt.InvalidTokenError:
        raise Unauthenticated() from None


@auth_bp.post("/auth/login")
def login():

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        raise ValidationError()

    if set(data.keys()) != {"email", "password"}:
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

    store = current_app.extensions["lms_store"]

    # Lay bo dem dang nhap that bai
    failed_logins = store["failed_logins"]

    state = failed_logins.setdefault(
        email,
        {
            "count": 0,
            "locked_until": 0,
        },
    )

    now = time.time()

    # Tai khoan dang bi khoa
    if state["locked_until"] > now:
        raise AccountLocked()

    # Het thoi gian khoa thi reset
    if state["locked_until"] != 0:
        state["count"] = 0
        state["locked_until"] = 0

    user_id = store["users_by_email"].get(email)
    user = store["users"].get(user_id)

    # Dung hash du phong khi email khong ton tai
    fallback_hash = next(iter(store["users"].values()))["password_hash"]

    password_hash = user["password_hash"] if user is not None else fallback_hash

    try:
        password_ok = bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        password_ok = False

    if user is None or not password_ok:
        state["count"] += 1

        if state["count"] >= MAX_FAILED_ATTEMPTS:
            state["locked_until"] = now + LOCK_DURATION
            raise AccountLocked()

        raise InvalidCredentials()

    # Dang nhap dung: reset bo dem
    failed_logins.pop(email, None)

    token = create_token(user)

    return jsonify(
        {
            "accessToken": token,
            "expiresIn": int(current_app.config["TOKEN_TTL_SECONDS"]),
        }
    ), 200
