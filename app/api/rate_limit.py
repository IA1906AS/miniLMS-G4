"""Atomic PostgreSQL rate limiting shared by all application workers."""

import math
import time

from flask import current_app, request


def client_ip() -> str:
    return request.remote_addr or "unknown"


def check_rate_limit(key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    store = current_app.extensions["lms_store"]
    now = time.time()
    with store._connect() as conn:
        cleanup = conn.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0)) AS acquired",
            ("minilms:rate_cleanup:" + store.schema,),
        ).fetchone()
        if cleanup["acquired"]:
            conn.execute("DELETE FROM rate_limits WHERE expires_at <= %s", (now,))
        row = conn.execute(
            "INSERT INTO rate_limits (key, count, expires_at) VALUES (%s, 1, %s) "
            "ON CONFLICT(key) DO UPDATE SET "
            "count = CASE WHEN rate_limits.expires_at <= %s THEN 1 ELSE rate_limits.count + 1 END, "
            "expires_at = CASE WHEN rate_limits.expires_at <= %s THEN EXCLUDED.expires_at "
            "ELSE rate_limits.expires_at END RETURNING count, expires_at",
            (key, now + window_seconds, now, now),
        ).fetchone()
    allowed = row["count"] <= limit
    return allowed, 0 if allowed else max(1, math.ceil(row["expires_at"] - now))
