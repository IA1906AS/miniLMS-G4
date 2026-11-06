"""PostgreSQL transactions for assignments and authoritative quiz attempts."""

from contextlib import contextmanager

from psycopg.types.json import Jsonb

from app.api.errors import NotFound

TABLES = {"assignments", "submissions", "quizzes", "quiz_attempts"}


class AssessmentRecords:
    def __init__(self, course_id, connection):
        self.course_id = course_id
        self.connection = connection

    def list(self, table, *, parent_id=None, student_id=None):
        if table not in TABLES:
            raise ValueError("Unknown assessment table")
        rows = self.connection.execute(
            f"SELECT data FROM {table} WHERE course_id = %s "
            "AND (%s::text IS NULL OR parent_id = %s) "
            "AND (%s::text IS NULL OR student_id = %s) ORDER BY sequence",
            (self.course_id, parent_id, parent_id, student_id, student_id),
        ).fetchall()
        return [row["data"] for row in rows]

    def get(self, table, record_id):
        if table not in TABLES:
            raise ValueError("Unknown assessment table")
        row = self.connection.execute(
            f"SELECT data FROM {table} WHERE id = %s AND course_id = %s",
            (record_id, self.course_id),
        ).fetchone()
        if row is None:
            raise NotFound()
        return row["data"]

    def save(self, table, item):
        if table not in TABLES or item["courseId"] != self.course_id:
            raise ValueError("Invalid assessment record")
        self.connection.execute(
            f"INSERT INTO {table} (id, course_id, parent_id, student_id, data) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (
                item["id"],
                self.course_id,
                item.get("parentId", ""),
                item.get("studentId", ""),
                Jsonb(item),
            ),
        )


@contextmanager
def assessment_records(store, course_id):
    # Row locks enforce attempt limits across Flask workers and app instances.
    with store._connect() as connection:
        if (
            connection.execute(
                "SELECT id FROM courses WHERE id = %s FOR UPDATE", (course_id,)
            ).fetchone()
            is None
        ):
            raise NotFound()
        yield AssessmentRecords(course_id, connection)
