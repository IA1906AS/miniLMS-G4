import os

from flask import Flask, g, jsonify, request

from app.api.audit import write_audit
from app.api.auth import auth_bp
from app.api.errors import register_error_handlers
from app.api.gate import register_gate
from app.api.guards import require_role
from app.api.pages import bp as pages_bp
from app.api.reset import bp as reset_bp
from app.api.schemas import validate_score_body
from app.api.services import (
    configure_store,
    get_grades,
    update_grade,
)
from app.api.signup import bp as signup_bp
from app.api.store import SEED_PATH, load_seed


def create_app(config=None):
    app = Flask(__name__)

    # 1. Cấu hình ứng dụng
    app.config.update(
        JWT_SECRET=os.environ.get("JWT_SECRET"),
        TOKEN_TTL_SECONDS=int(os.environ.get("TOKEN_TTL_SECONDS", "900")),
        AUDIT_LOG_PATH=os.environ.get(
            "AUDIT_LOG_PATH",
            "audit.log",
        ),
        ENABLE_EXTENSIONS=os.environ.get("ENABLE_EXTENSIONS") == "1",
        RESET_TOKEN_TTL_SECONDS=int(os.environ.get("RESET_TOKEN_TTL_SECONDS", "900")),
        RESET_TOKEN_ECHO=os.environ.get("RESET_TOKEN_ECHO") == "1",
        BCRYPT_ROUNDS=int(os.environ.get("BCRYPT_ROUNDS", "12")),
        LMS_STORE=os.environ.get("LMS_STORE", "memory").lower(),
        SQLITE_PATH=os.environ.get(
            "SQLITE_PATH",
            "instance/mini_lms.sqlite3",
        ),
    )

    # Cho phép ghi đè cấu hình khi chạy test
    if config is not None:
        app.config.update(config)

    # 2. Kiểm tra JWT secret
    secret = app.config.get("JWT_SECRET")

    if not isinstance(secret, str) or len(secret) < 32:
        raise RuntimeError("JWT_SECRET phải có ít nhất 32 ký tự")

    # 3. Khởi tạo kho dữ liệu
    if app.config["LMS_STORE"] == "memory":
        store = load_seed()

    elif app.config["LMS_STORE"] == "sqlite":
        from app.database.db import build_sqlite_store

        store = build_sqlite_store(
            app.config["SQLITE_PATH"],
            seed_path=SEED_PATH,
            bcrypt_rounds=app.config["BCRYPT_ROUNDS"],
        )

    else:
        raise ValueError("LMS_STORE phải là 'memory' hoặc 'sqlite'")

    app.extensions["lms_store"] = store
    app.extensions["lms_reset_tokens"] = {}

    configure_store(store)

    # 4. Đăng ký xử lý lỗi và xác thực
    register_error_handlers(app)
    register_gate(app)

    # 5. Đăng ký các Blueprint
    app.register_blueprint(auth_bp)
    app.register_blueprint(signup_bp)
    app.register_blueprint(reset_bp)
    app.register_blueprint(pages_bp)

    # Giữ nguyên cơ chế đăng ký extension tùy chọn.
    # Không đăng ký lại các Blueprint ở đây.
    if app.config["ENABLE_EXTENSIONS"]:
        from app.database import register_extensions

        register_extensions(app)

    # 6. API thông tin tài khoản
    @app.get("/me")
    def get_me():
        return jsonify(
            {
                "id": g.actor["id"],
                "email": g.actor["email"],
                "role": g.actor["role"],
            }
        ), 200

    # 7. API xem điểm
    @app.get("/courses/<course_id>/grades")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def view_grades(course_id):
        result = get_grades(
            g.actor,
            course_id,
            store=store,
        )

        return jsonify(result), 200

    # 8. API cập nhật điểm
    @app.put("/courses/<course_id>/grades/<student_id>")
    @require_role("INSTRUCTOR")
    def edit_grade(course_id, student_id):
        data = request.get_json(silent=True)
        score = validate_score_body(data)

        if isinstance(store, dict):
            old_score = next(
                (
                    item["score"]
                    for item in store["enrollments"]
                    if item["courseId"] == course_id and item["studentId"] == student_id
                ),
                None,
            )
        else:
            enrollment = store.get_enrollment(
                course_id,
                student_id,
            )
            old_score = enrollment.score if enrollment is not None else None

        result = update_grade(
            g.actor,
            course_id,
            student_id,
            score,
            store=store,
        )

        # Ghi audit log sau khi cập nhật điểm thành công
        write_audit(
            actor_id=g.actor["id"],
            action="UPDATE_GRADE",
            resource=f"/courses/{course_id}/grades/{student_id}",
            result="SUCCESS",
            old_score=old_score,
            new_score=result["score"],
        )

        return jsonify(result), 200

    return app
