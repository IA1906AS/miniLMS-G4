"""Course announcements with private per-student email delivery."""

import smtplib
from email.message import EmailMessage
from urllib.parse import urlencode

from flask import Blueprint, current_app, g, jsonify, request

from app.api.audit import write_audit
from app.api.errors import ValidationError
from app.api.guards import require_role
from app.api.learning import _authorize
from app.api.local_mail import save_local_message
from app.api.mail import send_smtp_message
from app.api.rate_limit import check_rate_limit
from app.api.reset import _rate_limited

bp = Blueprint("announcements", __name__)


@bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def public(item):
    result = {
        "id": item["id"],
        "courseId": item["course_id"],
        "title": item["title"],
        "body": item["body"],
        "authorId": item["author_id"],
        "authorName": item.get("author_name") or item["author_id"],
        "createdAt": item["created_at"].isoformat(),
    }
    if g.actor["role"] != "STUDENT":
        result["email"] = {
            "status": item["email_status"],
            "sent": item["email_sent"],
            "failed": item["email_failed"],
        }
    return result


@bp.get("/courses/<course_id>/announcements")
def list_announcements(course_id):
    _authorize(course_id)
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        raise ValidationError() from None
    if not 1 <= page <= 100000:
        raise ValidationError()
    rows, total = current_app.extensions["lms_store"].list_announcements(
        course_id, page
    )
    return jsonify(
        {
            "items": [public(row) for row in rows],
            "total": total,
            "page": page,
            "pageSize": 20,
        }
    )


@bp.post("/courses/<course_id>/announcements")
@require_role("INSTRUCTOR")
def create_announcement(course_id):
    course = _authorize(course_id, manage=True)
    request.max_content_length = 64 * 1024
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) - {"title", "body", "sendEmail"}:
        raise ValidationError()
    for field, limit in (("title", 200), ("body", 10000)):
        value = data.get(field)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > limit
            or "\x00" in value
        ):
            raise ValidationError()
    if "\n" in data["title"] or "\r" in data["title"]:
        raise ValidationError()
    if type(data.get("sendEmail", True)) is not bool:
        raise ValidationError()
    allowed, retry = check_rate_limit(f"announcements:{g.actor['id']}", 10, 3600)
    if not allowed:
        return _rate_limited(retry)
    store = current_app.extensions["lms_store"]
    row, recipients = store.create_announcement(
        course_id, g.actor["id"], data["title"].strip(), data["body"].strip()
    )
    sent = failed = 0
    status = "not_requested"
    cfg = current_app.config
    local_delivery = (
        not cfg["SMTP_ENABLED"] and cfg["LOCAL_EMAIL_ENABLED"] and current_app.debug
    )
    if data.get("sendEmail", True):
        status = "disabled" if not cfg["SMTP_ENABLED"] else "no_recipients"
        if (cfg["SMTP_ENABLED"] or local_delivery) and recipients:
            # Each message has one recipient so classmates' addresses stay private.
            link = (
                cfg["PUBLIC_BASE_URL"].rstrip("/")
                + "/catalog?"
                + urlencode({"course": course_id})
            )
            for email in recipients:
                message = EmailMessage()
                message["Subject"] = "miniLMS - " + row["title"]
                message["From"] = cfg["SMTP_FROM"] or "miniLMS <noreply@localhost>"
                message["To"] = email
                message.set_content(
                    f"Thông báo khóa học: {course.title}\n\n{row['title']}\n\n{row['body']}\n\nXem trên miniLMS: {link}\n"
                )
                try:
                    if local_delivery:
                        save_local_message(message, "announcement")
                    else:
                        send_smtp_message(message)
                    sent += 1
                except (OSError, smtplib.SMTPException):
                    failed += 1
                    current_app.logger.error(
                        "Course announcement email delivery failed."
                    )
            status = "sent" if not failed else "partial" if sent else "failed"
            if local_delivery:
                status = (
                    "local" if not failed else "local_partial" if sent else "failed"
                )
        elif local_delivery:
            status = "no_recipients"
    store.announcement_delivery(row["id"], status, sent, failed)
    row.update(email_status=status, email_sent=sent, email_failed=failed)
    write_audit(g.actor["id"], "CREATE_ANNOUNCEMENT", request.path, "SUCCESS")
    return jsonify(public(row)), 201
