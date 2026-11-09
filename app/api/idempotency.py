"""Idempotency records for assignment submissions only."""

import hashlib
import json
from uuid import UUID

from flask import request
from psycopg.types.json import Jsonb

from app.api.errors import APIError


class IdempotencyError(APIError):
    def __init__(self, code, status=400):
        self.error_code = code
        self.status_code = status
        super().__init__(code)


def submission_key():
    raw = request.headers.get("Idempotency-Key", "")
    if not raw:
        raise IdempotencyError("IDEMPOTENCY_KEY_REQUIRED")
    if len(raw) > 36:
        raise IdempotencyError("INVALID_IDEMPOTENCY_KEY")
    try:
        return str(UUID(raw))
    except ValueError as exc:
        raise IdempotencyError("INVALID_IDEMPOTENCY_KEY") from exc


def submission_hash(course_id, assignment_id, filename, content):
    metadata = json.dumps(
        [course_id, assignment_id, filename],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(metadata + b"\x00")
    digest.update(content)
    return digest.hexdigest()


def find_response(connection, scope, request_hash):
    row = connection.execute(
        "SELECT request_hash, response_status, response_body "
        "FROM submission_idempotency WHERE student_id = %s "
        "AND course_id = %s AND assignment_id = %s AND idempotency_key = %s",
        scope,
    ).fetchone()
    if row is not None and row["request_hash"] != request_hash:
        raise IdempotencyError("IDEMPOTENCY_KEY_REUSED", 409)
    return row


def save_response(connection, scope, request_hash, body, status=201):
    connection.execute(
        "INSERT INTO submission_idempotency "
        "(student_id, course_id, assignment_id, idempotency_key, "
        "request_hash, response_status, response_body) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (*scope, request_hash, status, Jsonb(body)),
    )
