"""PostgreSQL connection pool utilities for hosted deployment.

This module is intentionally separated from server.py so the database layer can
be optimized without touching business logic.
"""

import os

try:
    from psycopg_pool import ConnectionPool
except ImportError:
    ConnectionPool = None


_pool = None


def get_pool():
    global _pool
    if _pool is not None:
        return _pool

    if ConnectionPool is None:
        raise RuntimeError("psycopg_pool is required for Supabase deployment")

    dsn = os.environ.get("SUPABASE_DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("SUPABASE_DATABASE_URL is missing")

    _pool = ConnectionPool(
        conninfo=dsn,
        min_size=2,
        max_size=10,
        timeout=30,
    )
    return _pool


class PooledConnection:
    """Small compatibility wrapper matching the old connection lifecycle."""

    def __enter__(self):
        self._connection = get_pool().connection()
        return self._connection.__enter__()

    def __exit__(self, exc_type, exc, tb):
        return self._connection.__exit__(exc_type, exc, tb)


def pooled_connection():
    return PooledConnection()
