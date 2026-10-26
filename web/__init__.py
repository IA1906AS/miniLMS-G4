import os
import secrets
from pathlib import Path

from flask import Flask, render_template

from web.auth import auth_bp, csrf_token
from web.db import init_app
from web.reset import reset_bp
from web.seed_import import import_seed_command


def create_app(config=None):
    base_dir = Path(__file__).resolve().parent.parent
    instance_dir = base_dir / "instance"

    instance_dir.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, instance_path=str(instance_dir))

    # CAU HINH WEBSITE
    app.config.from_mapping(
        DATABASE=str(instance_dir / "website.sqlite3"),
        SECRET_KEY=(os.environ.get("WEB_SECRET_KEY") or secrets.token_hex(32)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Hien link reset trong Terminal khi demo
        DEMO_RESET_LINKS=(os.environ.get("DEMO_RESET_LINKS") == "1"),
    )

    if config is not None:
        app.config.update(config)

    # KET NOI DATABASE SQLITE

    init_app(app)

    # Lenh import du lieu tu seed.json
    app.cli.add_command(import_seed_command)

    # Dang ky cac blueprint
    app.register_blueprint(auth_bp)
    app.register_blueprint(reset_bp)

    # CSRF TOKEN CHO FORM HTML
    @app.context_processor
    def inject_csrf():
        return {"csrf_token": csrf_token}

    # TRANG CHU
    @app.get("/")
    def home():
        return render_template("home.html")

    return app
