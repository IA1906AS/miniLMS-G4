"""Lớp lưu trữ SQLite tùy chọn cho các API của miniLMS.

Đây là *tuỳ chọn*: mặc định ``LMS_STORE=memory`` để đường chấm điểm của đề giữ
đúng ràng buộc "không dùng database". Bật bằng ``LMS_STORE=sqlite``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.api.auth import hash_password
from app.api.store import Course, Enrollment, LoginAttempt, ResetToken, User

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    instructor_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS enrollments (
    course_id TEXT NOT NULL,
    student_id TEXT NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY (course_id, student_id)
);
CREATE TABLE IF NOT EXISTS attempts (
    email TEXT PRIMARY KEY,
    failures INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reset_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


class SqliteStore:
    """Persistent store with the same operations used by the API routes."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._lock = threading.Lock()
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # -- hạ tầng -------------------------------------------------------
    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def seed_if_empty(self, seed_path: str | Path, *, bcrypt_rounds: int = 10) -> None:
        with self._lock, self._connect() as conn:
            if conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]:
                return
            payload: dict[str, Any] = json.loads(
                Path(seed_path).read_text(encoding="utf-8")
            )
            for row in payload.get("users", []):
                conn.execute(
                    "INSERT INTO users (id, email, role, password_hash) VALUES (?, ?, ?, ?)",
                    (
                        str(row["id"]),
                        str(row["email"]).lower(),
                        str(row["role"]).upper(),
                        hash_password(str(row["password"]), rounds=bcrypt_rounds),
                    ),
                )
            for row in payload.get("courses", []):
                conn.execute(
                    "INSERT INTO courses (id, title, instructor_id) VALUES (?, ?, ?)",
                    (str(row["id"]), str(row["title"]), str(row["instructorId"])),
                )
            for row in payload.get("enrollments", []):
                conn.execute(
                    "INSERT INTO enrollments (course_id, student_id, score) VALUES (?, ?, ?)",
                    (str(row["courseId"]), str(row["studentId"]), float(row["score"])),
                )

    # -- users ---------------------------------------------------------
    def find_user_by_email(self, email: str) -> User | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
            ).fetchone()
        return _user(row) if row else None

    def get_fallback_password_hash(self) -> str:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users ORDER BY id LIMIT 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("SQLite store has no users; seed the database first")
        return str(row["password_hash"])

    def get_user(self, user_id: str) -> User | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return _user(row) if row else None

    def add_user(self, email: str, password_hash: str, role: str) -> User:
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
            user_id = f"u{100 + int(total)}"
            conn.execute(
                "INSERT INTO users (id, email, role, password_hash) VALUES (?, ?, ?, ?)",
                (user_id, email.strip().lower(), role.upper(), password_hash),
            )
        return User(
            id=user_id, email=email, role=role.upper(), password_hash=password_hash
        )

    def update_password(self, user_id: str, password_hash: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, user_id),
            )

    # -- courses -------------------------------------------------------
    def get_course(self, course_id: str) -> Course | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM courses WHERE id = ?", (course_id,)
            ).fetchone()
        if row is None:
            return None
        return Course(
            id=row["id"], title=row["title"], instructor_id=row["instructor_id"]
        )

    def list_enrollments(self, course_id: str) -> list[Enrollment]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM enrollments WHERE course_id = ? ORDER BY student_id",
                (course_id,),
            ).fetchall()
        return [_enrollment(row) for row in rows]

    def get_enrollment(self, course_id: str, student_id: str) -> Enrollment | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM enrollments WHERE course_id = ? AND student_id = ?",
                (course_id, student_id),
            ).fetchone()
        return _enrollment(row) if row else None

    def set_score(self, course_id: str, student_id: str, score: float) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE enrollments SET score = ? WHERE course_id = ? AND student_id = ?",
                (score, course_id, student_id),
            )

    # -- attempts / reset tokens ---------------------------------------
    def get_attempt(self, email: str) -> LoginAttempt:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM attempts WHERE email = ?", (email.strip().lower(),)
            ).fetchone()
        if row is None:
            return LoginAttempt()
        return LoginAttempt(
            failures=int(row["failures"]), locked_until=float(row["locked_until"])
        )

    def save_attempt(self, email: str, attempt: LoginAttempt) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO attempts (email, failures, locked_until) VALUES (?, ?, ?) "
                "ON CONFLICT(email) DO UPDATE SET failures = excluded.failures, "
                "locked_until = excluded.locked_until",
                (email.strip().lower(), attempt.failures, attempt.locked_until),
            )

    def add_reset_token(self, token: str, user_id: str, ttl_seconds: int) -> ResetToken:
        expires_at = time.time() + ttl_seconds
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO reset_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, expires_at),
            )
        return ResetToken(token=token, user_id=user_id, expires_at=expires_at)

    def take_reset_token(self, token: str) -> ResetToken | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reset_tokens WHERE token = ?", (token,)
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM reset_tokens WHERE token = ?", (token,))
        item = ResetToken(
            token=row["token"],
            user_id=row["user_id"],
            expires_at=float(row["expires_at"]),
        )
        return item if item.expires_at >= time.time() else None


def _user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        role=row["role"],
        password_hash=row["password_hash"],
    )


def _enrollment(row: sqlite3.Row) -> Enrollment:
    return Enrollment(
        course_id=row["course_id"], student_id=row["student_id"], score=row["score"]
    )


def build_sqlite_store(
    path: str | Path, *, seed_path: str | Path, bcrypt_rounds: int = 10
) -> SqliteStore:
    store = SqliteStore(path)
    store.seed_if_empty(seed_path, bcrypt_rounds=bcrypt_rounds)
    return store
