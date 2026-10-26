import re
import secrets
import sqlite3

import bcrypt
from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from web.db import get_db

auth_bp = Blueprint("auth", __name__)

# Hash du phong cho email khong ton tai
DUMMY_HASH = bcrypt.hashpw(
    b"dummy-password",
    bcrypt.gensalt(rounds=12),
)


# =================================
# 1. CSRF TOKEN
# =================================


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)

    return session["csrf_token"]


def check_csrf():
    expected = session.get("csrf_token", "")
    received = request.form.get("csrf_token", "")

    if not expected or not secrets.compare_digest(expected, received):
        abort(400)


# =================================
# 2. LOAD USER
# =================================


@auth_bp.before_app_request
def load_user():
    g.user = None

    user_id = session.get("user_id")

    if user_id is not None:
        g.user = (
            get_db()
            .execute(
                """
                SELECT id, full_name, email, role
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            )
            .fetchone()
        )


# =================================
# 3. DANG KY
# =================================


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        check_csrf()

        full_name = request.form.get("full_name", "").strip()

        email = request.form.get("email", "").strip().lower()

        password = request.form.get("password", "")

        password_bytes = password.encode("utf-8")

        if not 2 <= len(full_name) <= 100:
            flash("Ho ten phai co 2-100 ky tu.")

        elif (
            len(email) > 254
            or re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                email,
            )
            is None
        ):
            flash("Email khong hop le.")

        elif not 8 <= len(password_bytes) <= 72:
            flash("Mat khau phai co 8-72 byte.")

        else:
            password_hash = bcrypt.hashpw(
                password_bytes,
                bcrypt.gensalt(rounds=12),
            ).decode("utf-8")

            db = get_db()

            try:
                db.execute(
                    """
                    INSERT INTO users
                    (full_name, email, password_hash, role)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        full_name,
                        email,
                        password_hash,
                        "STUDENT",
                    ),
                )

                db.commit()

            except sqlite3.IntegrityError:
                flash("Email da duoc su dung.")

            else:
                flash("Dang ky thanh cong!")
                return redirect(url_for("auth.login"))

    return render_template("register.html")


# =================================
# 4. DANG NHAP
# =================================


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        check_csrf()

        email = request.form.get("email", "").strip().lower()

        password = request.form.get("password", "")

        user = (
            get_db()
            .execute(
                "SELECT * FROM users WHERE email = ?",
                (email,),
            )
            .fetchone()
        )

        password_bytes = password.encode("utf-8")

        if len(password_bytes) > 72:
            password_ok = False

        else:
            password_hash = (
                user["password_hash"].encode("utf-8")
                if user is not None
                else DUMMY_HASH
            )

            password_ok = bcrypt.checkpw(
                password_bytes,
                password_hash,
            )

        if user is None or not password_ok:
            flash("Email hoac mat khau khong dung.")

        else:
            session.clear()
            session["user_id"] = user["id"]

            return redirect(url_for("auth.account"))

    return render_template("login.html")


# =================================
# 5. ACCOUNT - PHAN QUYEN XEM DIEM
# =================================


@auth_bp.get("/account")
def account():
    # Kiem tra dang nhap
    if g.user is None:
        return redirect(url_for("auth.login"))

    db = get_db()

    role = g.user["role"]
    user_id = g.user["id"]

    grades = []

    # =================================
    # ADMIN - XEM TAT CA DIEM
    # =================================

    if role == "ADMIN":
        grades = db.execute(
            """
            SELECT
                c.id AS course_id,
                c.title AS course_title,
                s.full_name AS student_name,
                s.email AS student_email,
                i.full_name AS instructor_name,
                e.score
            FROM enrollments AS e

            JOIN courses AS c
                ON e.course_id = c.id

            JOIN users AS s
                ON e.student_id = s.id

            JOIN users AS i
                ON c.instructor_id = i.id

            ORDER BY c.title, s.email
            """
        ).fetchall()

    # =================================
    # INSTRUCTOR - XEM DIEM MON MINH DAY
    # =================================

    elif role == "INSTRUCTOR":
        grades = db.execute(
            """
            SELECT
                c.id AS course_id,
                c.title AS course_title,
                s.full_name AS student_name,
                s.email AS student_email,
                i.full_name AS instructor_name,
                e.score
            FROM enrollments AS e

            JOIN courses AS c
                ON e.course_id = c.id

            JOIN users AS s
                ON e.student_id = s.id

            JOIN users AS i
                ON c.instructor_id = i.id

            WHERE c.instructor_id = ?

            ORDER BY c.title, s.email
            """,
            (user_id,),
        ).fetchall()

    # =================================
    # STUDENT - CHI XEM DIEM CUA MINH
    # =================================

    elif role == "STUDENT":
        grades = db.execute(
            """
            SELECT
                c.id AS course_id,
                c.title AS course_title,
                i.full_name AS instructor_name,
                e.score
            FROM enrollments AS e

            JOIN courses AS c
                ON e.course_id = c.id

            JOIN users AS i
                ON c.instructor_id = i.id

            WHERE e.student_id = ?

            ORDER BY c.title
            """,
            (user_id,),
        ).fetchall()

    # Vai tro khong hop le
    else:
        abort(403)

    # =================================
    # HIEN THI GIAO DIEN
    # =================================

    return render_template(
        "account.html",
        grades=grades,
        role=role,
    )


# =================================
# 6. DANG XUAT
# =================================


@auth_bp.post("/logout")
def logout():
    check_csrf()

    session.clear()

    return redirect(url_for("auth.login"))
