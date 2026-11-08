import os

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request

from app.api.admin import bp as admin_bp
from app.api.announcements import bp as announcements_bp
from app.api.assessments import bp as assessments_bp
from app.api.assessments import remove_submission_files, submission_files
from app.api.audit import write_audit
from app.api.auth import auth_bp
from app.api.dashboard import bp as dashboard_bp
from app.api.errors import register_error_handlers
from app.api.forum import bp as forum_bp
from app.api.gate import register_gate
from app.api.guards import require_role
from app.api.learning import bp as learning_bp
from app.api.learning import course_materials, remove_material_files
from app.api.logout import bp as logout_bp
from app.api.pages import bp as pages_bp
from app.api.profiles import bp as profiles_bp
from app.api.reset import bp as reset_bp
from app.api.schemas import (
    validate_course_body,
    validate_course_update,
    validate_enrollment_body,
    validate_score_body,
)
from app.api.services import (
    add_enrollment,
    configure_store,
    create_course,
    delete_course,
    get_grades,
    list_course_enrollments,
    list_courses,
    remove_enrollment,
    update_course,
    update_grade,
)
from app.api.signup import bp as signup_bp
from app.api.store import BASE_DIR, SEED_PATH

# ============================================================
# SEC-07: CONTENT SECURITY POLICY
# ============================================================

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def create_app(config=None):
    # Hosting environment variables take precedence over local development values.
    load_dotenv(BASE_DIR / ".env", override=False)
    app = Flask(__name__)

    # ========================================================
    # 1. APPLICATION CONFIGURATION
    # ========================================================

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
        DATABASE_URL=os.environ.get("DATABASE_URL"),
        DATABASE_SCHEMA=os.environ.get("DATABASE_SCHEMA", "public"),
        LOGIN_MAX_FAILED_ATTEMPTS=int(os.environ.get("LOGIN_MAX_FAILED_ATTEMPTS", "5")),
        LOGIN_LOCK_DURATION_SECONDS=int(
            os.environ.get("LOGIN_LOCK_DURATION_SECONDS", "900")
        ),
        # Local email simulation (development only).
        LOCAL_EMAIL_ENABLED=os.environ.get("LOCAL_EMAIL_ENABLED") == "1",
        MATERIAL_UPLOAD_DIR=os.environ.get(
            "MATERIAL_UPLOAD_DIR", os.path.join(app.instance_path, "materials")
        ),
        SUBMISSION_UPLOAD_DIR=os.environ.get(
            "SUBMISSION_UPLOAD_DIR", os.path.join(app.instance_path, "submissions")
        ),
        AVATAR_UPLOAD_DIR=os.environ.get(
            "AVATAR_UPLOAD_DIR", os.path.join(app.instance_path, "avatars")
        ),
        PUBLIC_BASE_URL=os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:5000"),
        SMTP_ENABLED=os.environ.get("SMTP_ENABLED") == "1",
        SMTP_HOST=os.environ.get("SMTP_HOST", ""),
        SMTP_PORT=int(os.environ.get("SMTP_PORT", "587")),
        SMTP_FROM=os.environ.get("SMTP_FROM", ""),
        SMTP_USERNAME=os.environ.get("SMTP_USERNAME", ""),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
        SMTP_USE_TLS=os.environ.get("SMTP_USE_TLS", "1") == "1",
        SMTP_USE_SSL=os.environ.get("SMTP_USE_SSL", "0") == "1",
        SMTP_TIMEOUT_SECONDS=int(os.environ.get("SMTP_TIMEOUT_SECONDS", "10")),
    )

    # Allow tests to override configuration.
    if config is not None:
        app.config.update(config)

    from app.api.mail import validate_mail_config

    validate_mail_config(app.config)

    # ========================================================
    # 2. VALIDATE JWT SECRET
    # ========================================================

    secret = app.config.get("JWT_SECRET")

    if not isinstance(secret, str) or len(secret) < 32:
        raise RuntimeError("JWT_SECRET phải có ít nhất 32 ký tự")

    # ========================================================
    # 3. INITIALIZE STORAGE BACKEND
    # ========================================================

    from app.database.db import build_postgres_store

    if not app.config["DATABASE_URL"]:
        raise RuntimeError("DATABASE_URL is required; configure PostgreSQL in .env")
    store = build_postgres_store(
        app.config["DATABASE_URL"],
        schema=app.config["DATABASE_SCHEMA"],
        seed_path=SEED_PATH,
        bcrypt_rounds=app.config["BCRYPT_ROUNDS"],
    )

    app.extensions["lms_store"] = store

    configure_store(store)

    # ========================================================
    # 4. REGISTER SECURITY MIDDLEWARE
    # ========================================================

    register_error_handlers(app)
    register_gate(app)

    # ========================================================
    # 5. SEC-07: HTTP SECURITY HEADERS
    # ========================================================

    @app.after_request
    def apply_security_headers(response):
        """Apply security headers to every HTTP response."""

        # Prevent MIME-type sniffing.
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Restrict referrer information.
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Legacy frame protection; CSP frame-ancestors is primary.
        response.headers["X-Frame-Options"] = "DENY"

        # Restrict unnecessary browser features.
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )

        # Apply Content Security Policy.
        response.headers["Content-Security-Policy"] = CSP_POLICY

        return response

    # ========================================================
    # 6. REGISTER BLUEPRINTS
    # ========================================================

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(announcements_bp)
    app.register_blueprint(forum_bp)
    app.register_blueprint(logout_bp)
    app.register_blueprint(signup_bp)
    app.register_blueprint(reset_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(profiles_bp)
    app.register_blueprint(learning_bp)
    app.register_blueprint(assessments_bp)

    if app.config["ENABLE_EXTENSIONS"]:
        from app.database import register_extensions

        register_extensions(app)

    # ========================================================
    # 7. ACCOUNT INFORMATION API
    # ========================================================

    @app.get("/me")
    def get_me():
        return jsonify(
            {
                "id": g.actor["id"],
                "email": g.actor["email"],
                "role": g.actor["role"],
            }
        ), 200

    # ========================================================
    # 8. VIEW GRADES API
    # ========================================================

    @app.get("/courses/<course_id>/grades")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def view_grades(course_id):
        result = get_grades(
            g.actor,
            course_id,
            store=store,
        )

        return jsonify(result), 200

    # ========================================================
    # 9. UPDATE GRADES API
    # ========================================================

    @app.put("/courses/<course_id>/grades/<student_id>")
    @require_role("INSTRUCTOR")
    def edit_grade(course_id, student_id):
        data = request.get_json(silent=True)
        score, version = validate_score_body(data)

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
            version=version,
            store=store,
        )

        write_audit(
            actor_id=g.actor["id"],
            action="UPDATE_GRADE",
            resource=f"/courses/{course_id}/grades/{student_id}",
            result="SUCCESS",
            old_score=old_score,
            new_score=result["score"],
        )

        return jsonify(result), 200

    # ========================================================
    # 10. COURSES API
    # ========================================================

    @app.get("/courses")
    def list_courses_route():
        return jsonify(
            list_courses(
                store=store,
                query=request.args.get("q", "").strip(),
                instructor_id=request.args.get("instructorId", "").strip(),
            )
        ), 200

    @app.post("/courses")
    @require_role("ADMIN", "INSTRUCTOR")
    def create_course_route():
        title, instructor_id = validate_course_body(
            request.get_json(silent=True),
            default_instructor=g.actor["id"]
            if g.actor["role"] == "INSTRUCTOR"
            else None,
        )
        result = create_course(g.actor, title, instructor_id, store=store)

        write_audit(
            actor_id=g.actor["id"],
            action="CREATE_COURSE",
            resource=f"/courses/{result['id']}",
            result="SUCCESS",
        )

        return jsonify(result), 201

    @app.put("/courses/<course_id>")
    @require_role("ADMIN", "INSTRUCTOR")
    def update_course_route(course_id):
        title, instructor_id = validate_course_update(request.get_json(silent=True))
        result = update_course(
            g.actor,
            course_id,
            title=title,
            instructor_id=instructor_id,
            store=store,
        )

        write_audit(
            actor_id=g.actor["id"],
            action="UPDATE_COURSE",
            resource=f"/courses/{course_id}",
            result="SUCCESS",
        )

        return jsonify(result), 200

    @app.delete("/courses/<course_id>")
    @require_role("ADMIN")
    def delete_course_route(course_id):
        materials = course_materials(store, course_id)
        submissions = submission_files(store, course_id)
        delete_course(g.actor, course_id, store=store)
        remove_material_files(materials)
        remove_submission_files(submissions)

        write_audit(
            actor_id=g.actor["id"],
            action="DELETE_COURSE",
            resource=f"/courses/{course_id}",
            result="SUCCESS",
        )

        return jsonify({"status": "deleted"}), 200

    # ========================================================
    # 11. ENROLLMENTS API
    # ========================================================

    @app.get("/courses/<course_id>/enrollments")
    @require_role("ADMIN", "INSTRUCTOR")
    def list_enrollments_route(course_id):
        result = list_course_enrollments(g.actor, course_id, store=store)
        return jsonify(result), 200

    @app.post("/courses/<course_id>/enrollments")
    @require_role("ADMIN", "INSTRUCTOR")
    def add_enrollment_route(course_id):
        student_id = validate_enrollment_body(request.get_json(silent=True))
        result = add_enrollment(g.actor, course_id, student_id, store=store)

        write_audit(
            actor_id=g.actor["id"],
            action="ENROLL",
            resource=f"/courses/{course_id}/enrollments/{student_id}",
            result="SUCCESS",
        )

        return jsonify(result), 201

    @app.delete("/courses/<course_id>/enrollments/<student_id>")
    @require_role("ADMIN", "INSTRUCTOR")
    def remove_enrollment_route(course_id, student_id):
        remove_enrollment(g.actor, course_id, student_id, store=store)

        write_audit(
            actor_id=g.actor["id"],
            action="UNENROLL",
            resource=f"/courses/{course_id}/enrollments/{student_id}",
            result="SUCCESS",
        )

        return jsonify({"status": "unenrolled"}), 200

    # ==========================================
    # FAVICON
    # ==========================================

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    return app
