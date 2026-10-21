from flask import (
    current_app,
    g,
    request,
)

from app.auth import verify_token
from app.errors import Unauthenticated


def register_gate(app):

    @app.before_request
    def authentication_gate():

        # Chi cho phep login khong can JWT
        if request.path == "/auth/login" and request.method == "POST":
            return

        header = request.headers.get("Authorization", "")

        parts = header.split()

        if len(parts) != 2:
            raise Unauthenticated()

        if parts[0] != "Bearer":
            raise Unauthenticated()

        token = parts[1]

        payload = verify_token(token)

        store = current_app.extensions["lms_store"]

        user = store["users"].get(payload["sub"])

        if user is None:
            raise Unauthenticated()

        # Chi dua du lieu an toan vao actor
        g.actor = {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
        }

        return
