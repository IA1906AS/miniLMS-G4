import hashlib
import secrets
import time

import bcrypt
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from web.auth import check_csrf
from web.db import get_db

reset_bp = Blueprint("password_reset", __name__)


# =========================================
# 1. HASH RESET TOKEN
# =========================================


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# =========================================
# 2. FORGOT PASSWORD
# =========================================


@reset_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        check_csrf()

        email = request.form.get("email", "").strip().lower()

        if email and len(email) <= 254:
            db = get_db()

            user = db.execute(
                """
                SELECT id
                FROM users
                WHERE email = ?
                """,
                (email,),
            ).fetchone()

            if user is not None:
                # Tao token ngau nhien
                token = secrets.token_urlsafe(32)
                now = int(time.time())

                # Huy cac token reset cu
                db.execute(
                    """
                    UPDATE password_reset_tokens
                    SET used_at = ?
                    WHERE user_id = ?
                      AND used_at IS NULL
                    """,
                    (now, user["id"]),
                )

                # Luu hash cua token vao SQLite
                db.execute(
                    """
                    INSERT INTO password_reset_tokens
                    (user_id, token_hash, expires_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        user["id"],
                        hash_token(token),
                        now + 900,
                    ),
                )

                db.commit()

                # =====================================
                # SECURITY FIX: HOST HEADER INJECTION
                # =====================================

                # Chi hien link khi demo local
                if current_app.config.get("DEMO_RESET_LINKS", False):
                    # Tao duong dan tuong doi
                    reset_path = url_for(
                        "password_reset.reset_password",
                        token=token,
                    )

                    # Lay dia chi website tin cay
                    # tu cau hinh server
                    base_url = current_app.config["RESET_BASE_URL"].rstrip("/")

                    # Khong tao URL tuyet doi
                    # truc tiep tu Host header
                    link = f"{base_url}{reset_path}"

                    current_app.logger.warning(
                        "LOCAL DEMO RESET LINK: %s",
                        link,
                    )

        # Khong tiet lo email co ton tai hay khong
        flash(
            "Yeu cau da duoc ghi nhan. "
            "Neu email ton tai, ban co the tiep tuc "
            "theo huong dan dat lai mat khau."
        )

        return redirect(url_for("password_reset.forgot_password"))

    return render_template("forgot_password.html")


# =========================================
# 3. RESET PASSWORD
# =========================================


@reset_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if request.method == "POST":
        check_csrf()

    now = int(time.time())
    db = get_db()

    # Kiem tra token hop le va con han
    record = db.execute(
        """
        SELECT id, user_id
        FROM password_reset_tokens
        WHERE token_hash = ?
          AND used_at IS NULL
          AND expires_at > ?
        """,
        (hash_token(token), now),
    ).fetchone()

    if record is None:
        flash("Link khong hop le hoac da het han.")

        return redirect(url_for("password_reset.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")

        confirm = request.form.get("confirm", "")

        password_bytes = password.encode("utf-8")

        # Kiem tra do dai mat khau
        if not 8 <= len(password_bytes) <= 72:
            flash("Mat khau phai co 8-72 byte.")

        elif password != confirm:
            flash("Hai mat khau khong khop.")

        else:
            # Hash mat khau moi bang bcrypt
            password_hash = bcrypt.hashpw(
                password_bytes,
                bcrypt.gensalt(rounds=12),
            ).decode("utf-8")

            now = int(time.time())

            # Token chi duoc su dung mot lan
            updated = db.execute(
                """
                UPDATE password_reset_tokens
                SET used_at = ?
                WHERE id = ?
                  AND used_at IS NULL
                  AND expires_at > ?
                """,
                (now, record["id"], now),
            )

            if updated.rowcount != 1:
                db.rollback()

                flash("Link khong con hop le.")

                return redirect(url_for("password_reset.forgot_password"))

            # Cap nhat mat khau moi
            db.execute(
                """
                UPDATE users
                SET password_hash = ?
                WHERE id = ?
                """,
                (
                    password_hash,
                    record["user_id"],
                ),
            )

            # Vo hieu hoa cac reset token con lai
            db.execute(
                """
                UPDATE password_reset_tokens
                SET used_at = ?
                WHERE user_id = ?
                  AND used_at IS NULL
                """,
                (now, record["user_id"]),
            )

            db.commit()

            # Xoa phien dang nhap hien tai
            session.clear()

            flash("Doi mat khau thanh cong!")

            return redirect(url_for("auth.login"))

    return render_template("reset_password.html")
