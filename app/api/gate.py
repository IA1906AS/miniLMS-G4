"""Authentication gate for miniLMS.

Protect private routes using JWT authentication.

Supports:
- Memory and SQLite storage backends.
- Public pages and authentication endpoints.
- JWT signature and expiration verification.
- JWT token versioning.
- Rejection of old JWTs after password reset.
- JWT revocation checking for server-side logout.
- Public favicon and static assets.
"""

from __future__ import annotations

from flask import current_app, g, request

from app.api.auth import verify_token
from app.api.errors import Unauthenticated

# ============================================================
# JWT REVOCATION CHECK
# ============================================================


def is_token_revoked(jti: str) -> bool:
    """Check whether a JWT has been revoked."""

    store = current_app.extensions["lms_store"]

    if isinstance(store, dict):
        revoked_tokens = current_app.extensions.get(
            "lms_revoked_tokens",
            {},
        )
        return jti in revoked_tokens

    return store.is_token_revoked(jti)


# ============================================================
# AUTHENTICATION GATE
# ============================================================


def register_gate(app):
    """Register the global authentication middleware."""

    @app.before_request
    def authentication_gate():
        # ====================================================
        # STEP 1: PUBLIC ROUTES
        # ====================================================

        public_pages = {
            "/",
            "/login",
            "/register",
            "/resetpassword",
            "/account",
        }

        public_apis = {
            "/auth/login",
            "/auth/register",
            "/auth/forgot-password",
            "/auth/reset-password",
        }

        # Public frontend pages.
        if request.method == "GET" and request.path in public_pages:
            return

        # Public authentication APIs.
        if request.method == "POST" and request.path in public_apis:
            return

        # Static files.
        if request.endpoint == "static":
            return

        # Browser favicon request.
        if request.method == "GET" and request.path == "/favicon.ico":
            return

        # ====================================================
        # STEP 2: EXTRACT BEARER TOKEN
        # ====================================================

        authorization = request.headers.get(
            "Authorization",
            "",
        )

        parts = authorization.split()

        if len(parts) != 2 or parts[0].lower() != "bearer":
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
        # STEP 5: VERIFY TOKEN VERSION
        # ====================================================

        if isinstance(user, dict):
            current_version = user.get("token_version", 0)
        else:
            current_version = user.token_version

        if payload["ver"] != current_version:
            raise Unauthenticated()

        # ====================================================
        # STEP 6: VERIFY REVOCATION
        # ====================================================

        if is_token_revoked(payload["jti"]):
            raise Unauthenticated()

        # ====================================================
        # STEP 7: SET ACTOR
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

        g.jwt_payload = payload

        return
