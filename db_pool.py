"""Compatibility entrypoints for the unified cloud connection pool."""
import server


def get_pool():
    with server.CloudConnection(server.SUPABASE_DATABASE_URL) as db:
        return db._pool


def pooled_connection():
    return server.CloudConnection(server.SUPABASE_DATABASE_URL)
