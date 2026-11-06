"""One-time, read-only SQLite import into an empty PostgreSQL schema."""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from dotenv import load_dotenv
from psycopg import sql
from psycopg.types.json import Jsonb

from app.api.store import BASE_DIR
from app.database.db import PostgresStore

TABLES = (
    "users",
    "courses",
    "enrollments",
    "attempts",
    "revoked_jwts",
    "reset_tokens",
    "materials",
    "assignments",
    "submissions",
    "quizzes",
    "quiz_attempts",
    "rate_limits",
)


def _read_source(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def migrate_sqlite(source, database_url, *, schema="public", rate_source=None):
    store = PostgresStore(database_url, schema=schema)
    sources = [(source, TABLES)]
    if rate_source:
        sources[0] = (
            source,
            tuple(table for table in TABLES if table != "rate_limits"),
        )
        sources.append((rate_source, ("rate_limits",)))
    counts = {}
    with store._connect() as destination:
        destination.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ("minilms:seed:" + schema,),
        )
        for table in TABLES:
            if destination.execute(
                sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table))
            ).fetchone():
                raise ValueError(
                    "Destination must be empty. Import before starting Flask or use a new schema."
                )
        for filename, allowed in sources:
            with closing(_read_source(filename)) as old:
                old.execute("BEGIN")
                present = {
                    row["name"]
                    for row in old.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "users" in allowed and "users" not in present:
                    raise ValueError(
                        "Source is not a miniLMS database: users table is missing"
                    )
                for table in allowed:
                    if table not in present:
                        continue
                    columns = {
                        row["column_name"]
                        for row in destination.execute(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = %s AND table_name = %s",
                            (schema, table),
                        )
                    }
                    # Source table names come only from the fixed allow-list above.
                    rows = old.execute(
                        f'SELECT * FROM "{table}" ORDER BY rowid'
                    ).fetchall()
                    counts[table] = len(rows)
                    for row in rows:
                        keys = [
                            key
                            for key in dict(row)
                            if key in columns and key != "sequence"
                        ]
                        values = [
                            Jsonb(json.loads(row[key])) if key == "data" else row[key]
                            for key in keys
                        ]
                        destination.execute(
                            sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                                sql.Identifier(table),
                                sql.SQL(", ").join(map(sql.Identifier, keys)),
                                sql.SQL(", ").join(sql.Placeholder() for _ in keys),
                            ),
                            values,
                        )
    return counts


def main():
    load_dotenv(BASE_DIR / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--rate-source", type=Path)
    parser.add_argument("--schema", default=os.environ.get("DATABASE_SCHEMA", "public"))
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL is required (environment or .env)")
    try:
        counts = migrate_sqlite(
            args.source, url, schema=args.schema, rate_source=args.rate_source
        )
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))
    print("Imported into PostgreSQL: " + json.dumps(counts, ensure_ascii=False))
    print("SQLite sources and uploaded files were left unchanged.")


if __name__ == "__main__":
    main()
