"""Các trang giao diện của miniLMS."""

from flask import Blueprint, render_template

# Tên biến phải là bp để app/__init__.py import được
bp = Blueprint(
    "pages",
    __name__,
    template_folder="../templates",
)


@bp.get("/")
def home():
    """Trang chủ."""
    return render_template("landing.html")


@bp.get("/login")
def login_page():
    """Trang đăng nhập."""
    return render_template("login.html")


@bp.get("/register")
def register_page():
    """Trang đăng ký."""
    return render_template("register.html")


@bp.get("/account")
def account():
    """Trang tài khoản."""
    return render_template("account.html")


@bp.get("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@bp.get("/grades")
def grades():
    return render_template("grades.html")


@bp.get("/catalog")
def catalog():
    return render_template("courses.html")


@bp.get("/study")
def study():
    return render_template("study.html")


@bp.get("/forum")
def forum():
    return render_template("forum.html")


@bp.get("/resetpassword")
def reset_password_page():
    """Trang đặt lại mật khẩu."""
    return render_template("resetpassword.html")


@bp.get("/changepassword")
def change_password_page():
    """Trang đổi mật khẩu cho người dùng đã đăng nhập."""
    return render_template("changepassword.html")


@bp.get("/admin/users")
def admin_users_page():
    return render_template("admin_users.html")


@bp.get("/admin/audit")
def admin_audit_page():
    return render_template("admin_audit.html")
