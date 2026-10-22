"""Các trang giao diện của miniLMS."""

from flask import Blueprint, render_template

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


@bp.get("/resetpassword")
def reset_password_page():
    """Trang đặt lại mật khẩu."""
    return render_template("resetpassword.html")
