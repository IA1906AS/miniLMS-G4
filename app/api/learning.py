"""Course enrollment and authenticated lecture document storage."""

import io
import secrets
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from app.api.audit import write_audit
from app.api.errors import Forbidden, NotFound, ValidationError
from app.api.guards import require_role
from app.api.services import (
    _course_to_dict,
    _get_actor,
    _get_course,
    _require_course_manager,
    add_enrollment,
)

bp = Blueprint("learning", __name__)
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def _store():
    return current_app.extensions["lms_store"]


def _audit(action):
    write_audit(g.actor["id"], action, request.path, "SUCCESS")


def course_materials(store, course_id):
    return store.list_materials(course_id)


def _path(storage_name):
    if len(storage_name) != 32 or any(
        c not in "0123456789abcdef" for c in storage_name
    ):
        raise NotFound()
    return Path(current_app.config["MATERIAL_UPLOAD_DIR"]) / storage_name


def remove_material_files(materials):
    for item in materials:
        _path(item["storage_name"]).unlink(missing_ok=True)


def _authorize(course_id, *, manage=False):
    store = _store()
    user = _get_actor(store, g.actor)
    course = _get_course(store, course_id)
    if manage or g.actor["role"] != "STUDENT":
        _require_course_manager(user, course)
    else:
        enrolled = store.get_enrollment(course_id, g.actor["id"]) is not None
        if not enrolled:
            raise Forbidden()
    return course


@bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/instructors")
def instructors():
    store = _store()
    result = store.list_instructors()
    return jsonify(result)


@bp.post("/courses/join")
@require_role("STUDENT")
def join_course():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {"courseCode"}:
        raise ValidationError()
    code = data["courseCode"]
    if not isinstance(code, str) or not code.strip() or len(code) > 100:
        raise ValidationError()
    code = code.strip()
    result = add_enrollment(
        g.actor, code, g.actor["id"], store=_store(), self_enroll=True
    )
    _audit("SELF_ENROLL")
    return jsonify({"courseId": code, **result}), 201


@bp.get("/courses/<course_id>")
def course_detail(course_id):
    store = _store()
    course = _course_to_dict(_get_course(store, course_id))
    can_manage = g.actor["role"] == "ADMIN" or (
        g.actor["role"] == "INSTRUCTOR" and course["instructorId"] == g.actor["id"]
    )
    enrolled = store.get_enrollment(course_id, g.actor["id"]) is not None
    return jsonify(
        {
            **course,
            "courseCode": course_id,
            "canManage": can_manage,
            "enrolled": enrolled,
            "canAccessMaterials": can_manage or enrolled,
        }
    )


@bp.get("/courses/<course_id>/materials")
def list_materials(course_id):
    _authorize(course_id)
    return jsonify([_public(item) for item in course_materials(_store(), course_id)])


def _public(item):
    return {
        "id": item["id"],
        "title": item["title"],
        "fileName": item["filename"],
        "size": item["size"],
        "uploadedAt": item["uploaded_at"],
        "downloadUrl": f"/courses/{item['course_id']}/materials/{item['id']}/download",
    }


def _validate_document(filename, content):
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" and content.startswith(b"%PDF-"):
        return
    if suffix == ".txt":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError() from exc
        if b"\x00" not in content:
            return
    office = {
        ".docx": "word/document.xml",
        ".pptx": "ppt/presentation.xml",
        ".xlsx": "xl/workbook.xml",
    }
    if suffix in office:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
                if (
                    "[Content_Types].xml" in names
                    and office[suffix] in names
                    and not any(
                        name.lower().endswith("vbaproject.bin") for name in names
                    )
                ):
                    return
        except zipfile.BadZipFile as exc:
            raise ValidationError() from exc
    raise ValidationError()


@bp.post("/courses/<course_id>/materials")
def upload_material(course_id):
    _authorize(course_id, manage=True)
    request.max_content_length = MAX_DOCUMENT_BYTES + 64 * 1024
    if set(request.files) != {"file"} or len(request.files.getlist("file")) != 1:
        raise ValidationError()
    upload = request.files["file"]
    filename = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    title = request.form.get("title", "").strip() or filename
    if (
        not filename
        or len(filename) > 200
        or len(title) > 200
        or any(ord(char) < 32 for char in filename + title)
    ):
        raise ValidationError()
    content = upload.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise RequestEntityTooLarge()
    if not content:
        raise ValidationError()
    _validate_document(filename, content)
    item = {
        "id": secrets.token_hex(16),
        "course_id": course_id,
        "title": title,
        "filename": filename,
        "storage_name": secrets.token_hex(16),
        "size": len(content),
        "uploaded_at": datetime.now(UTC).isoformat(),
        "uploaded_by": g.actor["id"],
    }
    path = _path(item["storage_name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as file:
        file.write(content)
    store = _store()
    try:
        store.add_material(item)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    _audit("UPLOAD_MATERIAL")
    return jsonify(_public(item)), 201


def _material(course_id, material_id):
    item = next(
        (
            item
            for item in course_materials(_store(), course_id)
            if item["id"] == material_id
        ),
        None,
    )
    if item is None:
        raise NotFound()
    return item


@bp.get("/courses/<course_id>/materials/<material_id>/download")
def download_material(course_id, material_id):
    _authorize(course_id)
    item = _material(course_id, material_id)
    try:
        content = _path(item["storage_name"]).read_bytes()
    except FileNotFoundError as exc:
        raise NotFound() from exc
    return send_file(
        io.BytesIO(content),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=item["filename"],
        conditional=False,
    )


@bp.delete("/courses/<course_id>/materials/<material_id>")
def delete_material(course_id, material_id):
    _authorize(course_id, manage=True)
    item = _material(course_id, material_id)
    store = _store()
    store.remove_material(course_id, material_id)
    remove_material_files([item])
    _audit("DELETE_MATERIAL")
    return jsonify({"status": "deleted"})
