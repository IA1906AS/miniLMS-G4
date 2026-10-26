from flask import current_app, g, request

from app.api.auth import verify_token
from app.api.errors import Unauthenticated


def register_gate(app):

    @app.before_request
    def authentication_gate():

        # Các endpoint phục vụ giao diện công khai.
        public_page_routes = {
            ("GET", "/"),
            ("GET", "/login"),
            ("GET", "/register"),
            ("GET", "/resetpassword"),
        }

        public_api_routes = {
            ("POST", "/auth/register"),
            ("POST", "/auth/forgot-password"),
            ("POST", "/auth/reset-password"),
        }

        # Cho phép đăng nhập mà không cần JWT.
        if request.method == "POST" and request.path == "/auth/login":
            return

        # Cho phép các trang giao diện công khai.
        if (request.method, request.path) in public_page_routes:
            return

        # Cho phép các API công khai liên quan đến đăng ký / reset mật khẩu.
        if (request.method, request.path) in public_api_routes:
            return

        # Trang tài khoản chỉ mở khi extension được bật.
        if (
            current_app.config.get("ENABLE_EXTENSIONS", False)
            and request.method == "GET"
            and request.path == "/account"
        ):
            return

        # Cho phép tài nguyên tĩnh của Flask: CSS, JS, ảnh...
        if request.endpoint == "static":
            return

        # Các request còn lại cần Bearer JWT hợp lệ.
        header = request.headers.get("Authorization", "")
        parts = header.split()

        if len(parts) != 2 or parts[0] != "Bearer":
            raise Unauthenticated()

        token = parts[1]
        payload = verify_token(token)

        store = current_app.extensions["lms_store"]

        if isinstance(store, dict):
            user = store["users"].get(payload["sub"])
        else:
            user = store.get_user(payload["sub"])

        if user is None:
            raise Unauthenticated()

        # Chỉ đưa thông tin cần thiết vào actor.
        g.actor = {
            "id": user["id"] if isinstance(user, dict) else user.id,
            "email": (user["email"] if isinstance(user, dict) else user.email),
            "role": user["role"] if isinstance(user, dict) else user.role,
        }
