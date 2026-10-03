#!/usr/bin/env python3
"""Read-only cloud preflight. Never print credentials or raw remote errors."""
from __future__ import annotations

import json
import os
from pathlib import Path
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

TABLES = (
    'organizations', 'resources', 'missions', 'events', 'bookings', 'admin_config',
    'demo_runs', 'decisions', 'disputes', 'credit_events', 'contribution_events',
    'history_log', 'user_sessions',
)


def placeholder(value: str) -> bool:
    return not value or any(word in value.lower() for word in (
        'replace_me', 'replace_with_', 'your-project', 'your_database_password',
        '<your', '[your',
    ))


def main() -> int:
    errors = 0
    if server.DB_BACKEND != 'supabase' or placeholder(server.SUPABASE_DATABASE_URL):
        print('FAIL database configuration: set CAMPUS_DB_BACKEND=supabase and a real SUPABASE_DATABASE_URL in .env.')
        errors += 1
    elif server.psycopg is None:
        print('FAIL driver: run python -m pip install -r requirements-cloud.txt in your virtual environment.')
        errors += 1
    else:
        try:
            # Certificate and hostname verification stay enabled. For a private
            # CA, the operator can supply an authoritative CA file via PGSSLROOTCERT.
            rootcert = os.environ.get('PGSSLROOTCERT') or ssl.get_default_verify_paths().cafile or 'system'
            with server.psycopg.connect(
                server.SUPABASE_DATABASE_URL, connect_timeout=10,
                sslmode='verify-full', sslrootcert=rootcert,
                options='-c default_transaction_read_only=on -c statement_timeout=10000',
            ) as db:
                db.execute('SELECT 1').fetchone()
                print('PASS PostgreSQL authentication and verified TLS connection.')
                from psycopg import sql
                for table in TABLES:
                    db.execute(sql.SQL('SELECT 1 FROM {} LIMIT 1').format(sql.Identifier(table))).fetchone()
                count = db.execute('SELECT COUNT(*) FROM organizations').fetchone()[0]
                if not count:
                    print('FAIL demo data: no organizations; ask the owner to prepare the shared test database.')
                    errors += 1
                else:
                    print('PASS all 13 application tables are readable and organizations exist.')
                scheduler = db.execute('SELECT scheduler_enabled FROM admin_config WHERE id=1').fetchone()
                if scheduler is None:
                    print('FAIL admin configuration is missing; ask the owner to initialize the database.')
                    errors += 1
                elif scheduler[0]:
                    print('FAIL automatic scheduling is enabled: ask the owner to switch to Manual before running multiple local servers.')
                    errors += 1
        except Exception as exc:
            state = getattr(exc, 'sqlstate', None)
            if state == '28P01':
                hint = 'Database password rejected. Check the DSN password and its URL encoding.'
            elif state in ('42P01', '42703'):
                hint = 'Application schema is missing or outdated. Ask the owner; do not rerun migration yourself.'
            elif state == '42501':
                hint = 'Database role lacks permissions. Ask the owner to review test-project access.'
            else:
                hint = 'Check pooler host/port, DNS, TCP access, project status and trusted TLS CA (PGSSLROOTCERT).'
            print('FAIL PostgreSQL:', hint, '(Raw errors withheld to protect credentials.)')
            errors += 1

    if placeholder(server.SUPABASE_URL) or placeholder(server.SUPABASE_SECRET_KEY):
        print('FAIL Storage configuration: set a real SUPABASE_URL and server-only key.')
        errors += 1
    elif urllib.parse.urlsplit(server.SUPABASE_URL).scheme != 'https':
        print('FAIL Storage URL must use HTTPS.')
        errors += 1
    else:
        try:
            request = urllib.request.Request(
                server.SUPABASE_URL + '/storage/v1/bucket',
                headers={'apikey': server.SUPABASE_SECRET_KEY,
                         'Authorization': 'Bearer ' + server.SUPABASE_SECRET_KEY},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                buckets = json.load(response)
            bucket = next((b for b in buckets if b['id'] == server.SUPABASE_EVIDENCE_BUCKET), None)
            if bucket is None:
                print('FAIL evidence bucket is missing. Ask the owner to create the configured private bucket.')
                errors += 1
            elif bucket.get('public') is not False:
                print('FAIL evidence bucket is public; the owner must make it private.')
                errors += 1
            else:
                print('PASS Storage authentication and private evidence bucket lookup.')
        except urllib.error.HTTPError as exc:
            print(f'FAIL Storage HTTP {exc.code}: check project URL, server key, permissions and network policy.')
            errors += 1
        except Exception:
            print('FAIL Storage: check HTTPS access, DNS, proxy and trusted TLS certificates.')
            errors += 1

    if not os.environ.get('CAMPUS_ADMIN_PASSWORD'):
        print('INFO the double-click launcher will generate/reuse a local admin password. Set CAMPUS_ADMIN_PASSWORD for direct server.py startup.')
    elif placeholder(os.environ['CAMPUS_ADMIN_PASSWORD']):
        print('FAIL set a new private CAMPUS_ADMIN_PASSWORD in .env; do not use the historical repository password.')
        errors += 1
    if errors:
        print(f'Preflight failed ({errors} checks). No cloud data was modified.')
        return 1
    print('Read-only preflight passed. Next start the server and perform the README two-person test.')
    print('This checks connectivity and reads, not write permissions, uploads or browser behavior.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
