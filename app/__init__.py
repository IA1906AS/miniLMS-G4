import os

from flask import Flask, g, jsonify, request

from app.audit import write_audit
from app.auth import auth_bp
from app.errors import register_error_handlers
from app.gate import register_gate
from app.guards import require_role
from app.schemas import validate_score_body
from app.services import (
    configure_store,
    get_grades,
    update_grade,
)
from app.store import load_seed


def create_app(config=None):
    app = Flask(__name__)

    # 1. Cau hinh
    app.config.update(
        JWT_SECRET=os.environ.get("JWT_SECRET"),
        TOKEN_TTL_SECONDS=int(os.environ.get("TOKEN_TTL_SECONDS", "900")),
        AUDIT_LOG_PATH=os.environ.get("AUDIT_LOG_PATH", "audit.log"),
    )

    if config is not None:
        app.config.update(config)

    secret = app.config.get("JWT_SECRET")

    if not isinstance(secret, str) or len(secret) < 32:
        raise RuntimeError("JWT_SECRET phai co it nhat 32 ky tu")

    # 2. Nap du lieu
    store = load_seed()
    app.extensions["lms_store"] = store

    configure_store(store)

    # 3. Dang ky bao mat va xu ly loi
    register_error_handlers(app)
    register_gate(app)
    app.register_blueprint(auth_bp)

    # 4. API thong tin tai khoan
    @app.get("/me")
    def get_me():
        return jsonify(
            {
                "id": g.actor["id"],
                "email": g.actor["email"],
                "role": g.actor["role"],
            }
        ), 200

    # 5. API xem diem
    @app.get("/courses/<course_id>/grades")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def view_grades(course_id):
        result = get_grades(g.actor, course_id, store=store)

        return jsonify(result), 200

    # 6. API cap nhat diem
    @app.put("/courses/<course_id>/grades/<student_id>")
    @require_role("INSTRUCTOR")
    def edit_grade(course_id, student_id):

        data = request.get_json(silent=True)
        score = validate_score_body(data)

        old_score = next(
            (
                item["score"]
                for item in store["enrollments"]
                if (item["courseId"] == course_id and item["studentId"] == student_id)
            ),
            None,
        )

        result = update_grade(g.actor, course_id, student_id, score, store=store)

        # Ghi nhat ky sua diem thanh cong
        write_audit(
            actor_id=g.actor["id"],
            action="UPDATE_GRADE",
            resource=(f"/courses/{course_id}/grades/{student_id}"),
            result="SUCCESS",
            old_score=old_score,
            new_score=result["score"],
        )

        return jsonify(result), 200

    return app
