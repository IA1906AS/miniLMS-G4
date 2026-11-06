import os
import uuid

import psycopg
import pytest
from psycopg import sql

from tests.db_helpers import SCHEMAS, schema_for


@pytest.fixture(autouse=True)
def isolated_postgres_schema(monkeypatch, tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL is required. Start PostgreSQL and set a dedicated test database URL."
        )
    prefix = "test_" + uuid.uuid4().hex[:12] + "_"
    monkeypatch.setenv("LMS_TEST_SCHEMA_PREFIX", prefix)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATABASE_SCHEMA", schema_for(tmp_path / "default"))
    monkeypatch.setenv("BCRYPT_ROUNDS", "4")
    yield
    # Only this test's random schemas are removed; public/application tables stay untouched.
    owned = [schema for schema in SCHEMAS if schema.startswith(prefix)]
    with psycopg.connect(url, autocommit=True) as conn:
        for schema in owned:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
            SCHEMAS.discard(schema)
