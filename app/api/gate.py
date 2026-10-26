"""Authentication gate for miniLMS.

Protect private routes using JWT authentication.

Supports:
- Memory and SQLite storage backends.
- Public pages and authentication endpoints.
- JWT signature and expiration verification.
- JWT token versioning.
- Automatic rejection of old JWTs after password reset.
"""

from flask import current_app, g, request

from app.api.auth import verify_token
from app.api.errors import Unauthenticated


def register_gate(app):
    """Register the global authentication middleware."""

    @app.before_request
    def authentication_gate():
        # ====================================================
        # STEP 1: PUBLIC PAGE ROUTES
        # ====================================================

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

        # Login does not require an existing JWT.
        if request.method == "POST" and request.path == "/auth/login":
            return

        # Allow public frontend pages.
        if (request.method, request.path) in public_page_routes:
            return

        # Allow registration and password reset APIs.
        if (request.method, request.path) in public_api_routes:
            return

        # Account page is public only when extensions
        # are enabled.
        if (
            current_app.config.get(
                "ENABLE_EXTENSIONS",
                False,
            )
            and request.method == "GET"
            and request.path == "/account"
        ):
            return

        # Allow Flask static resources.
        if request.endpoint == "static":
            return

        # ====================================================
        # STEP 2: EXTRACT BEARER TOKEN
        # ====================================================

        authorization = request.headers.get(
            "Authorization",
            "",
        )

        parts = authorization.split()

        if len(parts) != 2 or parts[0] != "Bearer":
            raise Unauthenticated()

        token = parts[1]

        # ====================================================
        # STEP 3: VERIFY JWT
        # ====================================================

        payload = verify_token(token)

        # ====================================================
        # STEP 4: LOAD USER FROM STORE
        # ====================================================

        store = current_app.extensions["lms_store"]

        if isinstance(store, dict):
            user = store["users"].get(payload["sub"])
        else:
            user = store.get_user(payload["sub"])

        if user is None:
            raise Unauthenticated()

        # ====================================================
        # STEP 5: VERIFY JWT TOKEN VERSION
        # ====================================================

        if isinstance(user, dict):
            current_version = user.get(
                "token_version",
                0,
            )
        else:
            current_version = user.token_version

        # Reject tokens issued before password reset.
        if payload["ver"] != current_version:
            raise Unauthenticated()

        # ====================================================
        # STEP 6: SET AUTHENTICATED ACTOR
        # ====================================================

        if isinstance(user, dict):
            g.actor = {
                "id": user["id"],
                "email": user["email"],
                "role": user["role"],
            }
        else:
            g.actor = {
                "id": user.id,
                "email": user.email,
                "role": user.role,
            }
