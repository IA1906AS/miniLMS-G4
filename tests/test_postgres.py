import hashlib
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import bcrypt
import psycopg
import pytest

from app import create_app
from app.api.assessment_store import assessment_records
from app.database.db import PostgresStore
from app.database.migrate_sqlite import migrate_sqlite
from tests.db_helpers import schema_for


def old_database(path, *, invalid=False):
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE users (id TEXT, email TEXT, role TEXT, password_hash TEXT);
            CREATE TABLE courses (id TEXT, title TEXT, instructor_id TEXT);
            CREATE TABLE enrollments (course_id TEXT, student_id TEXT, score REAL);
            CREATE TABLE quizzes (id TEXT, course_id TEXT, parent_id TEXT, student_id TEXT, data TEXT);
        """)
        hashed = bcrypt.hashpw(b"Lms@2026", bcrypt.gensalt(rounds=4)).decode()
        conn.executemany(
            "INSERT INTO users VALUES (?, ?, ?, ?)",
            [
                ("u2", None if invalid else "teacher@lms.test", "INSTRUCTOR", hashed),
                ("u4", "student@lms.test", "STUDENT", hashed),
            ],
        )
        conn.execute("INSERT INTO courses VALUES ('c1', 'Imported course', 'u2')")
        conn.execute("INSERT INTO enrollments VALUES ('c1', 'u4', 7.25)")
        data = {
            "id": "q1",
            "courseId": "c1",
            "title": "Imported quiz",
            "durationSeconds": 60,
            "maxAttempts": 1,
            "questions": [
                {
                    "id": "question1",
                    "prompt": "1+1?",
                    "choices": ["1", "2"],
                    "correctIndex": 1,
                }
            ],
        }
        conn.execute(
            "INSERT INTO quizzes VALUES ('q1','c1','','',?)", (json.dumps(data),)
        )


def test_import_preserves_hash_grades_and_jsonb_without_modifying_source(tmp_path):
    source = tmp_path / "old.sqlite3"
    old_database(source)
    original = hashlib.sha256(source.read_bytes()).digest()
    rate = tmp_path / "rate.sqlite3"
    with sqlite3.connect(rate) as conn:
        conn.execute(
            "CREATE TABLE rate_limits (key TEXT, count INTEGER, expires_at REAL)"
        )
        conn.execute("INSERT INTO rate_limits VALUES ('legacy', 2, 9999999999)")
    schema = schema_for(tmp_path / "import")
    url = os.environ["TEST_DATABASE_URL"]
    counts = migrate_sqlite(source, url, schema=schema, rate_source=rate)
    assert counts["users"] == 2 and counts["rate_limits"] == 1
    assert hashlib.sha256(source.read_bytes()).digest() == original
    store = PostgresStore(url, schema=schema)
    assert store.get_enrollment("c1", "u4").score == 7.25
    assert store.get_user("u4").full_name == ""
    with assessment_records(store, "c1") as records:
        assert records.get("quizzes", "q1")["questions"][0]["correctIndex"] == 1
    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "test-migration-secret-at-least-32-characters",
            "DATABASE_SCHEMA": schema,
        }
    )
    client = app.test_client()
    assert (
        client.post(
            "/auth/login", json={"email": "student@lms.test", "password": "Lms@2026"}
        ).status_code
        == 200
    )
    with pytest.raises(ValueError, match="empty"):
        migrate_sqlite(source, url, schema=schema)
    assert store.get_user("u4") is not None


def test_failed_import_rolls_back_all_records(tmp_path):
    source = tmp_path / "invalid.sqlite3"
    old_database(source, invalid=True)
    schema = schema_for(tmp_path / "invalid_import")
    url = os.environ["TEST_DATABASE_URL"]
    with pytest.raises(psycopg.IntegrityError):
        migrate_sqlite(source, url, schema=schema)
    store = PostgresStore(url, schema=schema)
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM courses").fetchone()["n"] == 0


def test_separate_app_instances_share_atomic_quiz_attempt_limit(tmp_path):
    config = {
        "TESTING": True,
        "JWT_SECRET": "test-multi-app-secret-at-least-32-characters",
        "DATABASE_SCHEMA": schema_for(tmp_path / "shared"),
        "BCRYPT_ROUNDS": 4,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    }
    first = create_app(config)
    second = create_app(config)
    teacher = (
        first.test_client()
        .post("/auth/login", json={"email": "an.gv@lms.test", "password": "Lms@2026"})
        .json["accessToken"]
    )
    student = (
        first.test_client()
        .post("/auth/login", json={"email": "chi.sv@lms.test", "password": "Lms@2026"})
        .json["accessToken"]
    )
    quiz = (
        first.test_client()
        .post(
            "/courses/c1/quizzes",
            headers={"Authorization": "Bearer " + teacher},
            json={
                "title": "Atomic quiz",
                "durationSeconds": 60,
                "maxAttempts": 1,
                "questions": [
                    {"prompt": "Q?", "choices": ["A", "B"], "correctIndex": 0}
                ],
            },
        )
        .json
    )
    barrier = Barrier(2)

    def begin(app):
        with app.test_client() as client:
            barrier.wait(timeout=10)
            result = client.post(
                f"/courses/c1/quizzes/{quiz['id']}/attempts",
                headers={"Authorization": "Bearer " + student},
            )
            return result.status_code, result.json["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(begin, (first, second)))
    assert sorted(status for status, _ in results) == [200, 201]
    assert results[0][1] == results[1][1]


def test_schema_validation_and_missing_database_url(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="schema"):
        PostgresStore(
            os.environ["TEST_DATABASE_URL"], schema="public; DROP TABLE users"
        )
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(
            {
                "DATABASE_URL": None,
                "JWT_SECRET": "test-missing-url-secret-at-least-32-characters",
            }
        )
