"""Administrator-only user management."""

from flask import Blueprint, current_app, g, jsonify, request

from app.api.audit import write_audit
from app.api.errors import ValidationError
from app.api.guards import require_role

bp = Blueprint("admin", __name__)


def public_user(user):
    return {
        "id": user.id,
        "email": user.email,
        "fullName": user.full_name,
        "role": user.role,
        "isLocked": user.is_locked,
    }


@bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/admin/api/users")
@require_role("ADMIN")
def users():
    query = request.args.get("q", "").strip()
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        raise ValidationError() from None
    if len(query) > 200 or not 1 <= page <= 100000:
        raise ValidationError()
    rows, total = current_app.extensions["lms_store"].search_users(
        query, 20, (page - 1) * 20
    )
    return jsonify(
        {
            "items": [public_user(user) for user in rows],
            "total": total,
            "page": page,
            "pageSize": 20,
        }
    )


@bp.put("/admin/api/users/<user_id>")
@require_role("ADMIN")
def update_user(user_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data or set(data) - {"role", "isLocked"}:
        raise ValidationError()
    if "role" in data and (
        not isinstance(data["role"], str)
        or data["role"] not in {"ADMIN", "INSTRUCTOR", "STUDENT"}
    ):
        raise ValidationError()
    if "isLocked" in data and type(data["isLocked"]) is not bool:
        raise ValidationError()
    user = current_app.extensions["lms_store"].administer_user(
        g.actor["id"], user_id, data
    )
    write_audit(g.actor["id"], "ADMIN_UPDATE_USER", f"users/{user_id}", "SUCCESS")
    return jsonify(public_user(user))
