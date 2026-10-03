# Supabase collaboration setup

The maintained setup guide is in [README.md](README.md). It covers:

- [Double-click collaborator startup](README.md#double-click-startup-recommended)
- [One-time owner preparation](README.md#owner-prepare-access-once)
- [Private configuration delivery and encrypted archives](README.md#owner-securely-deliver-env)
- [Two-person acceptance testing](README.md#two-person-acceptance-test)
- [Connection troubleshooting](README.md#troubleshooting)

Use `main` for these instructions; the original `v2.0.0` tag predates the new helper.

Install Python 3.10+, receive the owner's private test-project `.env`, and double-click the Windows `.bat` or macOS `.command` launcher. Dependencies are installed automatically and the browser opens once the server responds. No separate connection check is required. For troubleshooting, `scripts/check_connection.py` is an optional read-only diagnostic; it does not migrate data or create the evidence bucket.

Only the owner should run `scripts/migrate_sqlite_to_supabase.py`, after backups and checking the intended source database. Its upserts can overwrite newer cloud records with matching IDs. Collaborators joining an existing test database must skip migration.

Supabase credentials give backend-level access. Share them only with trusted collaborators against a dedicated test project. For ordinary users, deploy one backend that keeps credentials private.
