"""Phần mở rộng tùy chọn cho miniLMS.

Các blueprint giao diện, đăng ký và reset password được đăng ký
trong create_app(), không đăng ký lại tại đây.
"""

from __future__ import annotations

from flask import Flask


def register_extensions(app: Flask) -> None:
    """Điểm mở rộng cho các extension tùy chọn trong tương lai."""
    # Không đăng ký lại pages_bp, signup_bp hoặc reset_bp:
    # create_app() đã đăng ký các blueprint này.


__all__ = ["register_extensions"]
