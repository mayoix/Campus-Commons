# Supabase setup for owners and trusted collaborators

For ordinary visitors, use **<https://campus-commons.onrender.com>**. They need only a browser; no private configuration or Python installation is necessary. This guide is for trusted collaborators who need to run a local backend against the shared cloud test project.

Return to the [main README](../../README.md) for the product workflow and administrator controls.

## Owner: prepare access once

1. Use a dedicated Supabase test project. Keep a backup before importing earlier local data.
2. Copy the exact database URI from **Supabase → Connect**. The Session pooler URI is convenient for networks without direct database IPv6 access. Supply the real database password and URL-encode password characters that require it. Do not invent a host/port from an example.
3. Copy the project URL and a **server-only secret key** (`sb_secret_...`, or the supported legacy service-role key). This key belongs only on trusted backends.
4. In Supabase Storage, create a **private** bucket named `campus-evidence`, or choose another name consistently. The upload handler can attempt to create an absent bucket on first upload; the optional diagnostic expects it to exist already.
5. Complete `.env.example` into a private `.env`. Use a newly chosen admin password for hosted deployments. Never copy the historical demo password.
6. Run one owner backend against this project to initialize/upgrade schema. Keep only one backend responsible for automatic scheduling. Stop other local backends during a repeatable shared-data allocation test.

## Private configuration format

Save a plain-text file named exactly `.env`, with one `KEY=value` per line. It belongs beside `start.py` and `server.py`. Example **format only** (replace every example value; do not send this unfilled template):

```dotenv
CAMPUS_DB_BACKEND=supabase
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SECRET_KEY=sb_secret_replace_me
SUPABASE_EVIDENCE_BUCKET=campus-evidence
SUPABASE_DATABASE_URL=postgresql://postgres.your-project-ref:YOUR_DATABASE_PASSWORD@YOUR_SESSION_POOLER_HOST:5432/postgres?sslmode=verify-full&sslrootcert=system
CAMPUS_ADMIN_PASSWORD=replace_with_a_new_private_admin_password
PORT=8765
```

The URI shown is illustrative; use the exact connection method/URI supplied by Supabase. `PORT=8765` is for the collaborator's local server; Render supplies its own port. Explicit shell environment variables take precedence over `.env`. The legacy `SUPABASE_SERVICE_ROLE_KEY` is accepted when `SUPABASE_SECRET_KEY` is absent.

`CAMPUS_ADMIN_PASSWORD` is optional for double-click startup: when omitted, `start.py` creates a local password in `.launcher-admin-password`. It is not optional operationally for a public deployment: set a private password in Render so it is known, controlled and stable across deployments.

## Owner: securely deliver `.env`

The `.env` is a private access package, not a repository release. Do not commit it or attach it to a public GitHub issue, README, release or shared screenshot. Give it only to collaborators you trust with backend-level test-project access.

One practical option uses 7-Zip to create an encrypted archive. From the project root, with a completed `.env` and 7-Zip installed:

```bash
mkdir private-share
7z a -t7z -mhe=on -p private-share/campus-private-config.7z .env
```

`-p` prompts for the archive password instead of placing it in shell history; `-mhe=on` encrypts filenames. Enter a strong archive password. Send the archive through a private channel and the password through a separate private channel. The ignored `private-share/` directory prevents accidental normal Git additions, but do not force-add it. If that directory already exists, skip `mkdir`.

Tell the recipient which test project and branch to use, whether automatic scheduling should remain disabled, and who supplies the admin password. Credentials enable direct backend/database access, not a limited per-user login. Rotate them if disclosed or when access should end; do not circulate the configuration to public website visitors.

## Collaborator: receive once, then double-click

1. Download `main` from GitHub and extract the code ZIP. The correct folder contains `server.py`, `start.py` and the launchers.
2. Decrypt the owner's private configuration archive. Copy its `.env` into that folder. On Windows, check that the name is not `.env.txt` and that it is not one directory above the code.
3. Install Python 3.10+; on Windows enable the installer option to add Python to PATH.
4. Double-click `Start Campus Commons.bat` on Windows or `Start Campus Commons.command` on macOS. On macOS, use `chmod +x "Start Campus Commons.command"` once if execution permission is missing. Terminal fallback: `python start.py` / `python3 start.py`.
5. First launch creates `.venv` and installs dependencies. The browser opens after shared data loads. Keep the terminal window open, and use the launcher again for later sessions. Stop with `Ctrl+C`.
6. To open admin, use **Alt/Option + Shift + A**, then the owner's configured password or your generated `.launcher-admin-password`.

If an old `.venv` already contains psycopg but lacks the newly required pool package, install `requirements-cloud.txt` with that environment's Python as shown in the [README](../../README.md#trusted-collaborator-double-click-cloud-startup). No separate validation or migration command is needed for normal startup.

Startup can apply schema/backfills and seed an empty cloud database. Joining is therefore not strictly read-only; use the owner's intended test project. **Do not run the SQLite migration as a collaborator.**

## Two-person acceptance test

Use a dedicated test project. Pick one backend for automatic scheduling, or leave all backends on Manual and run a batch deliberately from one admin console.

1. Collaborator A publishes a distinctly named resource with a future availability window.
2. Collaborator B refreshes their resource list and confirms the same resource/owner is visible. Distinguish shared data from browser state by using separate computers or browser profiles.
3. B submits a Mission that fits that resource and saves acceptable plan preferences.
4. The designated admin runs a manual batch; B checks the allocated result and A checks the provider view/booking.
5. B checks out and completes the Mission. Both inspect persistent status/history; A's sharing contribution reflects the completed booked hours.
6. For a separate allocated Mission, B can submit evidence, then the admin reviews it and verifies the private evidence endpoint. Use a separate browser/profile for another organization when demonstrating resolution.

This procedure is for users to run; it is not a claim that every network or production deployment has passed. Shared data is in Postgres; evidence is in private Storage. Browser updates use polling, not WebSocket push.

## Owner-only data migration

A clean checkout creates its local sample database on the first SQLite run. Cloud startup creates current schema and seeds an empty project, so **migration is only needed to preserve an earlier SQLite dataset**.

When that is intentional, keep the source `campus_commons.sqlite3` (or configured `CAMPUS_DB_PATH`) beside the project, complete `.env`, install the cloud requirements and run:

```bash
python3 -m pip install -r requirements-cloud.txt
python3 scripts/migrate_sqlite_to_supabase.py
```

Use `python` on Windows. The script asks for `YES` before import; `--yes` skips that prompt and is only for an intentional owner-controlled run. Upserts can overwrite newer cloud records with matching IDs. Back up source and target and confirm the intended test project before importing. It does not delete the source database. This is not a collaborator startup step.

## Diagnostics and hosted deployment

Optional read-only check:

```bash
python3 scripts/check_connection.py
```

It checks database authentication/TLS, schema/read access, scheduler suitability for multi-backend testing, and Storage authentication/private-bucket lookup. It does not migrate data, create a bucket or upload evidence. Share only PASS/FAIL summaries, never the configuration.

For Render, set environment variables in the service dashboard; do not publish `.env`. Use `pip install -r requirements.txt` and `python render_start.py`. The same server-owned pool is used by local cloud startup and hosted startup, preserving dictionary and numeric row access. See the [deployment section](../../README.md#deployment-and-data).
