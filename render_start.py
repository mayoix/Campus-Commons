#!/usr/bin/env python3
"""Render deployment entrypoint for Campus Commons.

Keeps the original local launcher unchanged while exposing the HTTP server on
Render's public interface.
"""

import os
import threading

import server
from http.server import ThreadingHTTPServer


if __name__ == "__main__":
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
