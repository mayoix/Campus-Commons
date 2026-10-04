#!/usr/bin/env python3
"""Render deployment entrypoint for Campus Commons.

Uses a PostgreSQL connection pool for hosted deployment while keeping the
original server implementation unchanged.
"""

import os
import threading

import server
import db_pool
from http.server import ThreadingHTTPServer


if __name__ == "__main__":
    # Replace per-request psycopg.connect() with pooled connections only for
    # the hosted deployment. Local SQLite development remains unchanged.
    if server.DB_BACKEND == "supabase":
        server.connect = db_pool.pooled_connection

    server.backup_db()
    server.init_db()
    threading.Thread(
        target=server.scheduler_loop,
        daemon=True,
        name="campus-scheduler",
    ).start()

    port = int(os.environ.get("PORT", "8000"))
    app = ThreadingHTTPServer(("0.0.0.0", port), server.Handler)
    print(f"Campus Commons running on port {port} (database: {server.DB_BACKEND})")
    try:
        app.serve_forever()
    finally:
        app.server_close()
