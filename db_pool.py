"""PostgreSQL connection pool utilities for hosted deployment.

Keeps the old SQLite-shaped database API while reusing PostgreSQL connections.
"""

import os

try:
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row
except ImportError:
    ConnectionPool = None
    dict_row = None


_pool = None


def get_pool():
    global _pool
    if _pool is None:
        if ConnectionPool is None:
            raise RuntimeError("psycopg_pool is required for Supabase deployment")
        dsn = os.environ.get("SUPABASE_DATABASE_URL", "").strip()
        if not dsn:
            raise RuntimeError("SUPABASE_DATABASE_URL is missing")
        _pool = ConnectionPool(
            conninfo=dsn,
            min_size=2,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=False
        )
        _pool.open(wait=True)
    return _pool


class CursorAdapter:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, statement, params=None):
        statement = _translate(statement)
        self.cursor.execute(statement, params or ())
        return self

    def fetchone(self):
        row = self.cursor.fetchone()
        return row

    def fetchall(self):
        return self.cursor.fetchall()


class ConnectionAdapter:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, params=None):
        return CursorAdapter(self.connection.execute(_translate(statement), params or ()))

    def cursor(self):
        return CursorAdapter(self.connection.cursor())

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _translate(statement):
    out = []
    quoted = False
    for char in statement:
        if char == "'":
            quoted = not quoted
        out.append("%s" if char == "?" and not quoted else char)
    return "".join(out)


class PooledConnection:
    def __enter__(self):
        self.connection = get_pool().getconn()
        return ConnectionAdapter(self.connection)

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self.connection.rollback()
            else:
                self.connection.commit()
        finally:
            get_pool().putconn(self.connection)


def pooled_connection():
    return PooledConnection()
