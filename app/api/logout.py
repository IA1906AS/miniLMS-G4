"""Server-side logout: revoke only the current JWT."""

from __future__ import annotations

import time

from flask import Blueprint, current_app, g, jsonify

bp = Blueprint("logout", __name__)


@bp.post("/auth/logout")
def logout():
    """Revoke the authenticated JWT until its expiry."""
    claims = g.jwt_payload
    jti = claims["jti"]
    expires_at = claims["exp"]
    store = current_app.extensions["lms_store"]

    if isinstance(store, dict):
        revoked = current_app.extensions["lms_revoked_tokens"]
        lock = current_app.extensions["lms_revoked_tokens_lock"]
        with lock:
            now = int(time.time())
            for key, expiry in list(revoked.items()):
                if expiry <= now:
                    del revoked[key]
            revoked[jti] = expires_at
    else:
        store.revoke_token(jti, expires_at)

    return jsonify({"status": "logged_out"}), 200
