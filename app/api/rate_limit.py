"""Shared SQLite rate limiter for miniLMS."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from flask import current_app, request


def client_ip() -> str:
    """Get the direct client IP address."""
    return request.remote_addr or "unknown"


def check_rate_limit(
    key: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds)."""

    db_path = Path(
        current_app.config.get(
            "RATE_LIMIT_DB_PATH",
            "instance/rate_limits.sqlite3",
        )
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)

    now = time.time()

    with sqlite3.connect(
        db_path,
        timeout=10,
        isolation_level=None,
    ) as conn:
        conn.execute("PRAGMA busy_timeout = 10000")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rate_limits (
                key TEXT PRIMARY KEY,
                count INTEGER NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )

        conn.execute("BEGIN IMMEDIATE")

        try:
            conn.execute(
                "DELETE FROM rate_limits WHERE expires_at <= ?",
                (now,),
            )

            row = conn.execute(
                "SELECT count, expires_at FROM rate_limits WHERE key = ?",
                (key,),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO rate_limits (key, count, expires_at)
                    VALUES (?, 1, ?)
                    """,
                    (key, now + window_seconds),
                )
                result = (True, 0)

            elif row[0] >= limit:
                retry_after = max(
                    1,
                    int(row[1] - now + 0.999),
                )
                result = (False, retry_after)

            else:
                conn.execute(
                    """
                    UPDATE rate_limits
                    SET count = count + 1
                    WHERE key = ?
                    """,
                    (key,),
                )
                result = (True, 0)

            conn.commit()
            return result

        except Exception:
            conn.rollback()
            raise
