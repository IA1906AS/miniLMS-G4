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

from app.api.errors import (
    AccountLocked,
    InvalidCredentials,
    Unauthenticated,
    ValidationError,
)

auth_bp = Blueprint("auth", __name__)

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = 15 * 60


def hash_password(password, *, rounds=12):
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)
    ).decode("utf-8")


def create_token(user):
    now = int(datetime.now(UTC).timestamp())

    ttl = int(current_app.config["TOKEN_TTL_SECONDS"])
    user_id = user["id"] if isinstance(user, dict) else user.id

    payload = {
        "sub": user_id,
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

    now = time.time()

    if isinstance(store, dict):
        state = store["failed_logins"].setdefault(
            email,
            {"count": 0, "locked_until": 0},
        )
        failures = state["count"]
        locked_until = state["locked_until"]
    else:
        attempt = store.get_attempt(email)
        failures = attempt.failures
        locked_until = attempt.locked_until

    # Tai khoan dang bi khoa
    if locked_until > now:
        raise AccountLocked()

    # Het thoi gian khoa thi reset
    if locked_until != 0:
        failures = 0
        locked_until = 0

    if isinstance(store, dict):
        user_id = store["users_by_email"].get(email)
        user = store["users"].get(user_id)
        fallback_hash = next(iter(store["users"].values()))["password_hash"]
    else:
        user = store.find_user_by_email(email)
        fallback_hash = store.get_fallback_password_hash()

    # Dung hash du phong khi email khong ton tai
    if user is None:
        password_hash = fallback_hash
    else:
        password_hash = (
            user["password_hash"] if isinstance(user, dict) else user.password_hash
        )

    try:
        password_ok = bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        password_ok = False

    if user is None or not password_ok:
        failures += 1

        if failures >= MAX_FAILED_ATTEMPTS:
            locked_until = now + LOCK_DURATION
            if isinstance(store, dict):
                state.update(count=failures, locked_until=locked_until)
            else:
                from app.api.store import LoginAttempt

                store.save_attempt(email, LoginAttempt(failures, locked_until))
            raise AccountLocked()

        if isinstance(store, dict):
            state["count"] = failures
        else:
            from app.api.store import LoginAttempt

            store.save_attempt(email, LoginAttempt(failures, locked_until))

        raise InvalidCredentials()

    # Dang nhap dung: reset bo dem
    if isinstance(store, dict):
        store["failed_logins"].pop(email, None)
    else:
        from app.api.store import LoginAttempt

        store.save_attempt(email, LoginAttempt())

    token = create_token(user)

    return jsonify(
        {
            "accessToken": token,
            "expiresIn": int(current_app.config["TOKEN_TTL_SECONDS"]),
        }
    ), 200
