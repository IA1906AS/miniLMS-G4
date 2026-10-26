import json
import sqlite3
from pathlib import Path

import bcrypt
import click
from flask import current_app
from flask.cli import with_appcontext

from web.db import get_db, init_db

VALID_ROLES = {"ADMIN", "INSTRUCTOR", "STUDENT"}


@click.command("import-seed")
@with_appcontext
def import_seed_command():
    # Duong dan file seed.json cua project
    seed_path = Path(current_app.root_path).parent / "seed.json"

    if not seed_path.is_file():
        raise click.ClickException("Khong tim thay seed.json")

    try:
        with seed_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Khong doc duoc seed.json: {exc}") from exc

    # Tao them cac bang chua ton tai
    init_db()

    db = get_db()

    # Mapping:
    # seed ID u1, u2... -> SQLite integer ID
    user_map = {}
    user_roles = {}

    created_users = 0
    created_courses = 0
    created_enrollments = 0

    try:
        # ======================================
        # 1. IMPORT USERS
        # ======================================
        for record in data["users"]:
            seed_id = record["id"]
            email = record["email"].strip().lower()
            role = record["role"]

            if role not in VALID_ROLES:
                raise ValueError(f"Vai tro khong hop le: {role}")

            existing = db.execute(
                """
                SELECT id, role
                FROM users
                WHERE email = ?
                """,
                (email,),
            ).fetchone()

            if existing is not None:
                if existing["role"] != role:
                    raise ValueError(f"Email {email} da ton tai voi vai tro khac")

                user_id = existing["id"]

            else:
                password = record["password"].encode("utf-8")

                if not 8 <= len(password) <= 72:
                    raise ValueError(f"Mat khau mau khong hop le: {email}")

                password_hash = bcrypt.hashpw(
                    password,
                    bcrypt.gensalt(rounds=12),
                ).decode("utf-8")

                full_name = record.get(
                    "full_name",
                    email.split("@")[0].replace(".", " ").title(),
                )

                cursor = db.execute(
                    """
                    INSERT INTO users
                    (full_name, email, password_hash, role)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        full_name,
                        email,
                        password_hash,
                        role,
                    ),
                )

                user_id = cursor.lastrowid
                created_users += 1

            user_map[seed_id] = user_id
            user_roles[seed_id] = role

        # ======================================
        # 2. IMPORT COURSES
        # ======================================
        for course in data["courses"]:
            instructor_seed_id = course["instructorId"]

            if user_roles[instructor_seed_id] != "INSTRUCTOR":
                raise ValueError("Giang vien cua mon hoc khong hop le")

            cursor = db.execute(
                """
                INSERT OR IGNORE INTO courses
                (id, title, instructor_id)
                VALUES (?, ?, ?)
                """,
                (
                    course["id"],
                    course["title"],
                    user_map[instructor_seed_id],
                ),
            )

            created_courses += cursor.rowcount

        # ======================================
        # 3. IMPORT ENROLLMENTS
        # ======================================
        for item in data["enrollments"]:
            student_seed_id = item["studentId"]

            if user_roles[student_seed_id] != "STUDENT":
                raise ValueError("Sinh vien ghi danh khong hop le")

            score = item["score"]

            if type(score) not in (int, float) or not 0 <= score <= 10:
                raise ValueError("Diem so khong hop le")

            cursor = db.execute(
                """
                INSERT OR IGNORE INTO enrollments
                (course_id, student_id, score)
                VALUES (?, ?, ?)
                """,
                (
                    item["courseId"],
                    user_map[student_seed_id],
                    score,
                ),
            )

            created_enrollments += cursor.rowcount

        db.commit()

    except (
        KeyError,
        ValueError,
        TypeError,
        sqlite3.Error,
    ) as exc:
        db.rollback()

        raise click.ClickException(f"Import that bai: {exc}") from exc

    click.echo("IMPORT SEED THANH CONG!")
    click.echo(f"Users moi: {created_users}")
    click.echo(f"Courses moi: {created_courses}")
    click.echo(f"Enrollments moi: {created_enrollments}")
