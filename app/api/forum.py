"""Course-scoped topics and comments; edits belong to the author."""

from flask import Blueprint, current_app, g, jsonify, request

from app.api.audit import write_audit
from app.api.errors import NotFound, ValidationError
from app.api.guards import require_role
from app.api.learning import _authorize
from app.api.rate_limit import check_rate_limit
from app.api.reset import _rate_limited

bp = Blueprint("forum", __name__)


@bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def store():
    return current_app.extensions["lms_store"]


def public(row):
    return {
        "id": row["id"],
        "courseId": row["course_id"],
        "topicId": row["parent_id"],
        "title": row["title"],
        "body": row["body"],
        "authorId": row["author_id"],
        "authorName": row.get("author_name") or row["author_id"],
        "createdAt": row["created_at"].isoformat(),
        "updatedAt": row["updated_at"].isoformat(),
        "canEdit": row["author_id"] == g.actor["id"]
        and g.actor["role"] in {"STUDENT", "INSTRUCTOR"},
        "replies": row.get("replies", 0),
    }


def body(*, topic):
    request.max_content_length = 64 * 1024
    data = request.get_json(silent=True)
    fields = {"title", "body"} if topic else {"body"}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValidationError()
    for key in fields:
        value = data[key]
        if (
            not isinstance(value, str)
            or not value.strip()
            or "\x00" in value
            or len(value) > (200 if key == "title" else 10000)
        ):
            raise ValidationError()
    return {key: value.strip() for key, value in data.items()}


def listing(course_id, parent_id=None):
    _authorize(course_id)
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        raise ValidationError() from None
    if not 1 <= page <= 100000:
        raise ValidationError()
    rows, total = store().forum_list(course_id, parent_id, page)
    return jsonify(
        {
            "items": [public(row) for row in rows],
            "total": total,
            "page": page,
            "pageSize": 20,
        }
    )


def create(course_id, parent_id=None):
    _authorize(course_id)
    data = body(topic=parent_id is None)
    allowed, retry = check_rate_limit(f"forum:{g.actor['id']}", 30, 3600)
    if not allowed:
        return _rate_limited(retry)
    post_id = store().forum_write(course_id, g.actor["id"], parent_id=parent_id, **data)
    write_audit(g.actor["id"], "FORUM_CREATE", request.path, "SUCCESS")
    return jsonify(public(store().forum_post(course_id, post_id))), 201


@bp.get("/courses/<course_id>/forum/topics")
def topics(course_id):
    return listing(course_id)


@bp.post("/courses/<course_id>/forum/topics")
@require_role("STUDENT", "INSTRUCTOR")
def create_topic(course_id):
    return create(course_id)


@bp.get("/courses/<course_id>/forum/topics/<topic_id>")
def topic_detail(course_id, topic_id):
    _authorize(course_id)
    row = store().forum_post(course_id, topic_id)
    if row["parent_id"] is not None:
        raise NotFound()
    return jsonify(public(row))


@bp.get("/courses/<course_id>/forum/topics/<topic_id>/comments")
def comments(course_id, topic_id):
    return listing(course_id, topic_id)


@bp.post("/courses/<course_id>/forum/topics/<topic_id>/comments")
@require_role("STUDENT", "INSTRUCTOR")
def create_comment(course_id, topic_id):
    return create(course_id, topic_id)


@bp.put("/courses/<course_id>/forum/posts/<post_id>")
@require_role("STUDENT", "INSTRUCTOR")
def edit_post(course_id, post_id):
    _authorize(course_id)
    row = store().forum_post(course_id, post_id)
    data = body(topic=row["parent_id"] is None)
    store().forum_write(course_id, g.actor["id"], post_id=post_id, **data)
    write_audit(g.actor["id"], "FORUM_EDIT", request.path, "SUCCESS")
    return jsonify(public(store().forum_post(course_id, post_id)))


@bp.delete("/courses/<course_id>/forum/posts/<post_id>")
@require_role("STUDENT", "INSTRUCTOR")
def delete_post(course_id, post_id):
    _authorize(course_id)
    store().forum_write(course_id, g.actor["id"], post_id=post_id, delete=True)
    write_audit(g.actor["id"], "FORUM_DELETE", request.path, "SUCCESS")
    return jsonify({"status": "deleted"})
