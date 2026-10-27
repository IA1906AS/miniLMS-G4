"""Lớp lưu trữ SQLite tùy chọn cho các API của miniLMS.

Mặc định LMS_STORE=memory để giữ đúng yêu cầu không dùng database.
Bật SQLite bằng LMS_STORE=sqlite.

Hỗ trợ JWT Token Versioning:
- Mỗi user có token_version mặc định bằng 0.
- Khi reset mật khẩu, token_version tăng thêm 1.
- JWT cũ bị từ chối khi version không khớp.
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

# ============================================================
# DATABASE SCHEMA
# ============================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    token_version INTEGER NOT NULL DEFAULT 0
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

CREATE TABLE IF NOT EXISTS revoked_jwts (
    jti TEXT PRIMARY KEY,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS reset_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


class SqliteStore:
    """Persistent storage backend for miniLMS."""

    # ========================================================
    # INITIALIZATION
    # ========================================================

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._lock = threading.Lock()

        Path(self._path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

            # Migration for existing SQLite databases.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}

            if "token_version" not in columns:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN "
                    "token_version INTEGER NOT NULL DEFAULT 0"
                )

    # ========================================================
    # DATABASE CONNECTION
    # ========================================================

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(
            self._path,
            timeout=10,
        )

        conn.row_factory = sqlite3.Row

        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ========================================================
    # SEED DATA
    # ========================================================

    def seed_if_empty(
        self,
        seed_path: str | Path,
        *,
        bcrypt_rounds: int = 10,
    ) -> None:

        with self._lock, self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

            if count:
                return

            payload: dict[str, Any] = json.loads(
                Path(seed_path).read_text(encoding="utf-8")
            )

            # Seed users
            for row in payload.get("users", []):
                conn.execute(
                    """
                    INSERT INTO users (
                        id,
                        email,
                        role,
                        password_hash,
                        token_version
                    )
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (
                        str(row["id"]),
                        str(row["email"]).lower(),
                        str(row["role"]).upper(),
                        hash_password(
                            str(row["password"]),
                            rounds=bcrypt_rounds,
                        ),
                    ),
                )

            # Seed courses
            for row in payload.get("courses", []):
                conn.execute(
                    """
                    INSERT INTO courses (
                        id,
                        title,
                        instructor_id
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        str(row["id"]),
                        str(row["title"]),
                        str(row["instructorId"]),
                    ),
                )

            # Seed enrollments
            for row in payload.get("enrollments", []):
                conn.execute(
                    """
                    INSERT INTO enrollments (
                        course_id,
                        student_id,
                        score
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        str(row["courseId"]),
                        str(row["studentId"]),
                        float(row["score"]),
                    ),
                )

    # ========================================================
    # USER MANAGEMENT
    # ========================================================

    def find_user_by_email(
        self,
        email: str,
    ) -> User | None:

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()

        return _user(row) if row else None

    def get_fallback_password_hash(self) -> str:

        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT password_hash
                FROM users
                ORDER BY id
                LIMIT 1
                """
            ).fetchone()

        if row is None:
            raise RuntimeError("SQLite store has no users; seed the database first")

        return str(row["password_hash"])

    def get_user(
        self,
        user_id: str,
    ) -> User | None:

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

        return _user(row) if row else None

    def add_user(
        self,
        email: str,
        password_hash: str,
        role: str,
    ) -> User:
        """Create a user with a collision-resistant ID."""

        import uuid

        user_id = f"u{uuid.uuid4().hex}"
        normalized_email = email.strip().lower()

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    id,
                    email,
                    role,
                    password_hash,
                    token_version
                )
                VALUES (?, ?, ?, ?, 0)
                """,
                (
                    user_id,
                    normalized_email,
                    role.upper(),
                    password_hash,
                ),
            )

        return User(
            id=user_id,
            email=normalized_email,
            role=role.upper(),
            password_hash=password_hash,
            token_version=0,
        )

    # ========================================================
    # PASSWORD RESET + JWT INVALIDATION
    # ========================================================

    def update_password(
        self,
        user_id: str,
        password_hash: str,
    ) -> None:

        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET password_hash = ?,
                    token_version = token_version + 1
                WHERE id = ?
                """,
                (
                    password_hash,
                    user_id,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError("User not found")

    def reset_password_atomic(
        self,
        token_hash: str,
        password_hash: str,
    ) -> str | None:
        """Atomically reset password and consume reset token."""

        with self._lock, self._connect() as conn:
            # Acquire the write lock before reading the token.
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                """
                SELECT user_id
                FROM reset_tokens
                WHERE token = ?
                  AND expires_at > ?
                """,
                (token_hash, time.time()),
            ).fetchone()

            if row is None:
                return None

            user_id = str(row["user_id"])

            cursor = conn.execute(
                """
                UPDATE users
                SET password_hash = ?,
                    token_version = token_version + 1
                WHERE id = ?
                """,
                (password_hash, user_id),
            )

            if cursor.rowcount != 1:
                raise ValueError("Reset token references missing user")

            cursor = conn.execute(
                "DELETE FROM reset_tokens WHERE token = ?",
                (token_hash,),
            )

            if cursor.rowcount != 1:
                raise RuntimeError("Failed to consume reset token")

            return user_id

    # ========================================================
    # COURSE MANAGEMENT
    # ========================================================

    def get_course(
        self,
        course_id: str,
    ) -> Course | None:

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM courses WHERE id = ?",
                (course_id,),
            ).fetchone()

        if row is None:
            return None

        return Course(
            id=row["id"],
            title=row["title"],
            instructor_id=row["instructor_id"],
        )

    def list_enrollments(
        self,
        course_id: str,
    ) -> list[Enrollment]:

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM enrollments
                WHERE course_id = ?
                ORDER BY student_id
                """,
                (course_id,),
            ).fetchall()

        return [_enrollment(row) for row in rows]

    def get_enrollment(
        self,
        course_id: str,
        student_id: str,
    ) -> Enrollment | None:

        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM enrollments
                WHERE course_id = ?
                AND student_id = ?
                """,
                (
                    course_id,
                    student_id,
                ),
            ).fetchone()

        return _enrollment(row) if row else None

    def set_score(
        self,
        course_id: str,
        student_id: str,
        score: float,
    ) -> None:

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE enrollments
                SET score = ?
                WHERE course_id = ?
                AND student_id = ?
                """,
                (
                    score,
                    course_id,
                    student_id,
                ),
            )

    # ========================================================
    # LOGIN ATTEMPTS
    # ========================================================

    def get_attempt(
        self,
        email: str,
    ) -> LoginAttempt:

        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM attempts
                WHERE email = ?
                """,
                (email.strip().lower(),),
            ).fetchone()

        if row is None:
            return LoginAttempt()

        return LoginAttempt(
            failures=int(row["failures"]),
            locked_until=float(row["locked_until"]),
        )

    def save_attempt(
        self,
        email: str,
        attempt: LoginAttempt,
    ) -> None:

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO attempts (
                    email,
                    failures,
                    locked_until
                )
                VALUES (?, ?, ?)

                ON CONFLICT(email)
                DO UPDATE SET
                    failures = excluded.failures,
                    locked_until = excluded.locked_until
                """,
                (
                    email.strip().lower(),
                    attempt.failures,
                    attempt.locked_until,
                ),
            )

    # ========================================================
    # JWT REVOCATION
    # ========================================================

    def revoke_token(self, jti: str, expires_at: int) -> None:
        """Persist a revoked JWT until its expiration."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM revoked_jwts WHERE expires_at <= ?", (int(time.time()),)
            )
            conn.execute(
                "INSERT OR IGNORE INTO revoked_jwts (jti, expires_at) VALUES (?, ?)",
                (jti, expires_at),
            )

    def is_token_revoked(self, jti: str) -> bool:
        """Return whether an unexpired revoked JWT exists."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM revoked_jwts WHERE expires_at <= ?", (int(time.time()),)
            )
            row = conn.execute(
                "SELECT 1 FROM revoked_jwts WHERE jti = ?", (jti,)
            ).fetchone()
        return row is not None

    # ========================================================
    # RESET TOKENS
    # ========================================================

    def add_reset_token(
        self,
        token: str,
        user_id: str,
        ttl_seconds: int,
    ) -> ResetToken:

        expires_at = time.time() + ttl_seconds

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reset_tokens (
                    token,
                    user_id,
                    expires_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    token,
                    user_id,
                    expires_at,
                ),
            )

        return ResetToken(
            token=token,
            user_id=user_id,
            expires_at=expires_at,
        )

    def take_reset_token(
        self,
        token: str,
    ) -> ResetToken | None:

        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM reset_tokens
                WHERE token = ?
                """,
                (token,),
            ).fetchone()

            if row is None:
                return None

            conn.execute(
                "DELETE FROM reset_tokens WHERE token = ?",
                (token,),
            )

        item = ResetToken(
            token=row["token"],
            user_id=row["user_id"],
            expires_at=float(row["expires_at"]),
        )

        if item.expires_at < time.time():
            return None

        return item


# ============================================================
# ROW MAPPERS
# ============================================================


def _user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        role=row["role"],
        password_hash=row["password_hash"],
        token_version=int(row["token_version"]),
    )


def _enrollment(row: sqlite3.Row) -> Enrollment:
    return Enrollment(
        course_id=row["course_id"],
        student_id=row["student_id"],
        score=row["score"],
    )


# ============================================================
# STORE FACTORY
# ============================================================


def build_sqlite_store(
    path: str | Path,
    *,
    seed_path: str | Path,
    bcrypt_rounds: int = 10,
) -> SqliteStore:

    store = SqliteStore(path)

    store.seed_if_empty(
        seed_path,
        bcrypt_rounds=bcrypt_rounds,
    )

    return store
