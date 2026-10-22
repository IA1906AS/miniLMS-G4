from flask import g, jsonify, request
from werkzeug.exceptions import HTTPException

from app.api.audit import write_audit

# ==========================================
# 1. DINH NGHIA CAC LOAI LOI
# ==========================================


class APIError(Exception):
    status_code = 500
    error_code = "INTERNAL_ERROR"


class ValidationError(APIError):
    status_code = 400
    error_code = "VALIDATION_ERROR"


class InvalidCredentials(APIError):
    status_code = 401
    error_code = "INVALID_CREDENTIALS"


class Unauthenticated(APIError):
    status_code = 401
    error_code = "UNAUTHENTICATED"


class Forbidden(APIError):
    status_code = 403
    error_code = "FORBIDDEN"


class NotFound(APIError):
    status_code = 404
    error_code = "NOT_FOUND"


class AccountLocked(APIError):
    status_code = 429
    error_code = "ACCOUNT_LOCKED"


# ==========================================
# 2. GHI AUDIT LOG KHI BI TU CHOI QUYEN
# ==========================================


def log_forbidden():
    actor = getattr(g, "actor", None)

    actor_id = actor.get("id") if isinstance(actor, dict) else None

    if request.method == "PUT":
        action = "UPDATE_GRADE"

    elif request.method == "GET":
        action = "VIEW_GRADES"

    else:
        action = request.method

    write_audit(
        actor_id=actor_id,
        action=action,
        resource=request.path,
        result="DENIED",
    )


# ==========================================
# 3. DANG KY CAC HAM XU LY LOI
# ==========================================


def register_error_handlers(app):

    # Xu ly cac loi do ung dung dinh nghia
    @app.errorhandler(APIError)
    def handle_api_error(error):

        if isinstance(error, Forbidden):
            log_forbidden()

        return jsonify({"error": error.error_code}), error.status_code

    # Xu ly loi HTTP mac dinh cua Flask
    @app.errorhandler(HTTPException)
    def handle_http_error(error):

        if error.code == 403:
            log_forbidden()

        codes = {
            400: "VALIDATION_ERROR",
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            429: "ACCOUNT_LOCKED",
        }

        code = codes.get(error.code, "INTERNAL_ERROR")

        return jsonify({"error": code}), error.code

    # Xu ly cac loi khong mong muon
    @app.errorhandler(Exception)
    def handle_unexpected_error(error):

        app.logger.exception("Unexpected server error")

        return jsonify({"error": "INTERNAL_ERROR"}), 500
