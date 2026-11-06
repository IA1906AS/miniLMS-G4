import hashlib
import os
from contextlib import contextmanager

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

SCHEMAS: set[str] = set()


def schema_for(path) -> str:
    prefix = os.environ["LMS_TEST_SCHEMA_PREFIX"]
    name = prefix + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    SCHEMAS.add(name)
    return name


@contextmanager
def connect_schema(schema=None):
    schema = schema or os.environ["DATABASE_SCHEMA"]
    if not schema.startswith(os.environ["LMS_TEST_SCHEMA_PREFIX"]):
        raise ValueError("Tests may access only their own isolated schema")
    SCHEMAS.add(schema)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], row_factory=dict_row) as conn:
        conn.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
        )
        conn.execute("SELECT set_config('search_path', %s, false)", (schema,))
        yield conn
