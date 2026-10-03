# Campus Commons

Campus Commons is a full-stack MVP for sharing campus resources between organizations. Organizations can publish equipment, spaces, skills, and people resources; submit Missions; choose acceptable options; and receive an allocation after the application window closes.

The repository includes:

- A user app for publishing resources, submitting Missions, managing an organization profile, checking approved results, and reporting disputes.
- An administrator console opened from the user app. It manages resources, organizations, allocation batches, disputes, credit events, and explainable demo scenarios.
- Persistent history for resources, Missions, bookings, decisions, disputes, credit events, contribution events, and platform changes.
- A SQLite demo database for an offline local run.
- A Supabase Postgres + Supabase Storage mode for a shared cloud database and cloud evidence files.

## What users see

The user app keeps the wording short and practical:

- The resource directory can be sorted by status, availability time (earliest first), location (A–Z), or price (low to high).
- Mission submission lets users select the required resource types (equipment, space, skill, or people), describe the need, choose a location, and set the use interval. The server calculates the application deadline and returns only complete capability matches.
- The organization profile shows contribution, credit, history, and resources owned by the current organization. Owners can edit their own resource details, availability, and status.
- Users see the submitted time, cutoff, use interval, and the exact approved resources. Requesters can use their Mission details; resource providers see the Mission and loan period for each resource they supply. Fairness weights, batch internals, and administrator controls stay in the admin console.
- Recent activity is filtered to the current organization.
- The Impact and value page quantifies shared hours, estimated external cost avoided, coordination time saved, Mission coverage, and resource-pool utilization. The page shows the calculation assumptions used for each estimate.
- A user can report a dispute and upload evidence. When an approved compensation dispute is resolved by the affected organization, the provider account is unfrozen.

## Double-click startup (recommended)

For trusted collaborators, there is no need to install packages manually or run a separate connection check.

**First use:**

1. Install **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/) if it is not already installed. On Windows include the Python launcher (`py`) during installation. Linux may also need its distribution's Python venv package.
2. Download **Code → Download ZIP** from the latest `main` branch and extract the entire folder. Receive the owner's private test-project `.env` and place it next to `server.py` and `start.py`. Keep its filename exactly `.env`, not `.env.txt`.
3. Double-click **`Start Campus Commons.bat`** on Windows or **`Start Campus Commons.command`** on macOS. On Linux, run the executable `.command` file from a terminal or run `python3 start.py` in the project folder.

The launcher creates `.venv`, installs the pinned cloud driver on first use, starts the application in Supabase mode, and opens the browser after the page and shared data respond. It waits for initialization before making one cloud-data request with a 60-second timeout, rather than repeatedly interrupting database requests after two seconds. Dependencies are reused on later launches. Keep its terminal window open; press **Ctrl + C** to stop the server. Later visits only require double-clicking the launcher. First-time dependency installation and every cloud connection need internet access.

If macOS blocks opening the downloaded command, use Finder's **Open** option for the file you trust. If executable permission was lost while extracting, run `chmod +x "Start Campus Commons.command"` once, or use `python3 start.py` from a terminal. Windows users should extract the folder before double-clicking, not run from inside the ZIP viewer. Startup does not require administrator rights.

If `CAMPUS_ADMIN_PASSWORD` is absent in an older private `.env`, the launcher automatically generates a local password in `.launcher-admin-password` and reuses it on later launches. Open that hidden file privately when you need admin login; the password is not printed or committed. A supplied `CAMPUS_ADMIN_PASSWORD` still takes priority. Direct `server.py` startup does not use this launcher fallback.

A missing/incomplete `.env`, occupied port or failed cloud startup produces a short message and leaves the error window open. The launcher never copies credentials into code, migrates the SQLite data to Supabase, or silently switches to SQLite. Normal application startup can still initialize/backfill schema/history. It does not test evidence uploads; those happen when used in the app. Connection checks below are optional troubleshooting tools, not a daily startup requirement.

**Owner's simplest handoff:** privately send the trusted collaborator a folder/package containing this source version plus the completed test `.env`, using the encrypted delivery method below. Exclude `.git`, `.venv`, local backups and your historical `.admin-password`; do not omit the tracked demo SQLite file if you want the optional offline demo. Never publish a configured package on GitHub. Alternatively, let collaborators download GitHub's ZIP and privately send just `.env` once. Keep automatic scheduling Manual and prepare the shared database once before distributing the package.

## Manual setup and optional diagnostics

A clone alone cannot connect to the shared database: the owner must supply a valid private `.env`, prepare the cloud schema/data and allow your network to reach Supabase. Use a **separate Supabase test project**. Everyone using it can change the same test data. Ordinary end users should use a hosted backend instead of receiving these credentials.

These instructions are on `main` **after** the `v2.0.0` tag. Clone `main`; that older tag does not contain the preflight script or dependency file below. Python 3.10+ is required; Git is needed only for `git clone`. Downloading **Code → Download ZIP** and extracting it is also supported; run commands in the folder containing `server.py`.

### 1. Download and install

macOS/Linux:

```bash
git clone https://github.com/mayoix/campus-commons.git
cd campus-commons
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-cloud.txt
```

Windows PowerShell:

```powershell
git clone https://github.com/mayoix/campus-commons.git
cd campus-commons
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-cloud.txt
```

No activation or PowerShell execution-policy change is needed. The pinned driver includes its binary dependencies.

### 2. Receive the owner's private configuration

Ask the owner for the **test project's** `.env` using the delivery procedure below. Place it next to `server.py`, not in `static/` or `scripts/`. If creating it yourself, copy `.env.example` and replace every placeholder:

```bash
# macOS/Linux; only if you have not already received .env
cp .env.example .env
```

```powershell
# Windows; only if you have not already received .env
Copy-Item .env.example .env
```

Enable filename extensions in Windows Explorer and verify it is `.env`, not `.env.txt`. Never overwrite an existing working `.env` without saving a private backup outside Git. On macOS, Command + Shift + Period shows hidden files; on Linux use Ctrl + H.

Required configuration (examples only, never real credentials in this document):

```dotenv
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SECRET_KEY=sb_secret_replace_me
SUPABASE_EVIDENCE_BUCKET=campus-evidence
SUPABASE_DATABASE_URL=postgresql://postgres.your-project-ref:YOUR_DATABASE_PASSWORD@YOUR_SESSION_POOLER_HOST:5432/postgres?sslmode=verify-full&sslrootcert=system
CAMPUS_DB_BACKEND=supabase
CAMPUS_ADMIN_PASSWORD=replace_with_a_new_private_admin_password
PORT=8765
```

Use the actual **Session pooler** URI from Supabase **Connect**; do not guess its region, hostname or username. Session pooling is compatible with typical IPv4 networks. URL-encode only the password component if it contains `@`, `:`, `/`, `#`, `%` or other reserved characters. Do not paste passwords into online encoders. Keep TLS certificate/hostname verification enabled; the bundled modern PostgreSQL client supports `sslrootcert=system`. If a trusted CA file is required on your system, obtain it from the provider and use its path instead. Append parameters with `&` if the URI already contains `?`.

The Storage URL, server key and database URI must all belong to the same test project. A publishable/anon key is not a replacement for this MVP's server key. Set a new private administrator password: an older `.admin-password` is already tracked in repository history and is **not a secret**. The environment override takes precedence.

Shell environment variables override `.env`. If an old configuration persists, use a fresh terminal or unset the old `SUPABASE_*`/`CAMPUS_DB_BACKEND` values and restart. `CAMPUS_DB_PATH` is read before `.env` in this version; if you need that optional SQLite override, set it in the shell rather than in `.env`.

### 3. Optional connection diagnostics

macOS/Linux:

```bash
.venv/bin/python scripts/check_connection.py
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts/check_connection.py
```

The check loads the root `.env`, verifies PostgreSQL authentication and TLS, reads all 13 application tables, checks that organizations/admin configuration exist, checks that automatic scheduling is off, and authenticates to Storage to find the private evidence bucket. It rejects placeholder admin passwords; if no override is set, it explains the launcher-generated password option. It prints no keys, passwords or raw server errors. A failure returns a nonzero exit code; it never migrates, writes rows, creates buckets or starts the scheduler.

Expected final message: `Read-only preflight passed.` This establishes connectivity and reads, **not** database writes, evidence upload permissions or UI behavior. Complete the two-person test below as well. If you run these diagnostics, resolve failures with the owner; double-click startup does not require this separate step.

### 4. Start and open the platform

macOS/Linux:

```bash
.venv/bin/python server.py
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe server.py
```

Keep the terminal open and visit <http://127.0.0.1:8765/> on the **same computer**. The startup line must say `(database: supabase)`. Press Ctrl + C to stop. Each collaborator starts their own local server, all connected to the same cloud project; sending your localhost URL to someone else does not share your server.

Open the admin overlay with **Option + Shift + A** on macOS or **Alt + Shift + A** on Windows/Linux and enter `CAMPUS_ADMIN_PASSWORD`. If the shortcut is intercepted, focus the page and check keyboard shortcuts. The admin dashboard should show `Supabase Postgres · Connected`. Its Storage badge only reflects configuration presence; use the preflight and upload test to verify actual access.

**Collaborators must not run `migrate_sqlite_to_supabase.py`.** The existing shared database is already prepared by the owner. Starting the server can initialize/backfill schema and history, so this is not a read-only activity. Current startup requires schema-creation and application read/write privileges; a SELECT-only database role is insufficient.

## Owner: prepare access once

1. Use a separate Supabase project for shared testing. Keep production data and credentials separate. Confirm the project is running and collaborators can reach its HTTPS API (443) and Session pooler (normally TCP 5432). Any configured database IP restrictions must permit their networks. An HTTPS proxy alone may not support PostgreSQL TCP.
2. Create your private `.env` from the template. Choose a new admin password in a password manager. Use a revocable test-project server key and database credential. Treat every recipient as a backend administrator; hiding the in-page admin button does not limit someone who has these keys.
3. Prepare the schema and demonstration data **once**. If the cloud database already works, skip migration. For a new/empty test project only, first back up the intended local SQLite source and verify it is the current dataset; the Git-tracked demo database may be older than your working local database. Install `requirements-cloud.txt`, then run `.venv/bin/python scripts/migrate_sqlite_to_supabase.py --yes` (Windows: `.\.venv\Scripts\python.exe scripts/migrate_sqlite_to_supabase.py --yes`). The migration updates existing rows with the same ID using the local values; repeated execution can overwrite newer cloud changes. It is not a safe reset. For an existing populated database, back up the cloud data and compare records before deciding to migrate.
4. In Supabase Storage create a bucket named `campus-evidence` (or the configured name) with **Public bucket disabled**. The application can create it on first upload, but precreating it makes the read-only preflight meaningful before testing.
5. With only the owner's server running, open **Demo tests → Scheduler settings**, choose **Manual**, and save. Stop extra servers while changing this. Each running server launches a scheduler thread, while its lock is only local to that process. Leave scheduling manual during collaboration and designate one operator to run batches; do not run batches concurrently on several machines.
6. Run the preflight and the browser test yourself, then deliver access. Record who received it. On revocation, rotate the distributed database password/server key and update remaining collaborators' private files; deleting a shared link cannot revoke already downloaded credentials.

## Owner: securely deliver `.env`

**Preferred:** share a secure note/file through a password manager with named-recipient access and expiry. Include only the test-project `.env` and the README link. A normal ZIP archive is not encryption. Never put `.env` in a GitHub commit, Issue, PR, Release asset or public download.

**Encrypted archive alternative:** use a trusted 7-Zip-compatible application with **7z format, AES-256 encryption and encrypted filenames**. Install it from its official distribution if needed. Archive creation is a local owner action; no real configuration package is generated or published by this repository.

1. Create a temporary folder **outside the checkout**, such as a private folder on your desktop. Copy only the intended `.env` into it; exclude `.git`, `.admin-password`, SQLite databases, backups and other project files. If you already have a correct `.env`, do not run the template-copy command over it.
2. Using the application's GUI, select `.env` → **Add to archive** → format **7z** → encryption **AES-256** → **Encrypt file names**. Use a unique strong passphrase saved in your password manager. Choose an output path outside the repository.
3. If the `7z` command is installed, the equivalent command, run inside that temporary folder, is:

   ```text
   7z a -t7z -mhe=on -p campus-commons-test-env.7z .env
   ```

   `-p` prompts interactively; do not append the passphrase to the command or store it in shell history. Run `7z t campus-commons-test-env.7z` and enter the passphrase to verify the archive. Basic OS ZIP tools may not support encrypted 7z extraction; recipients need a compatible tool.
4. Send the archive through a private recipient-restricted transfer with an expiry. Deliver the passphrase over a separate authenticated channel, such as a phone call or password manager. Verify the recipient identity; do not post both in a shared public channel.
5. The recipient decrypts it locally, places `.env` next to `server.py`, double-clicks the platform launcher, and keeps the file private. On macOS/Linux run `chmod 600 .env`. On Windows use an access-controlled user folder and check the file's Security permissions. Remove unnecessary temporary plaintext copies after confirming setup; keep only a protected backup if needed.

Before committing any project changes, run:

```text
git check-ignore .env
git ls-files --error-unmatch .env
```

The first must report `.env`; the second must **fail** because the file must not be tracked. `.gitignore` does not untrack files already committed. Review staged filenames with `git diff --cached --name-only` before pushing. If a real key was committed, rotate it; deleting it in a later commit does not erase history.

## Two-person acceptance test

Use only the shared test project and dummy evidence. Agree on a unique prefix such as `TEST-A-20261003` so test records are identifiable.

1. Both collaborators double-click their launchers and confirm the Supabase backend. Use the optional preflight only if needed for troubleshooting. Use a healthy demo organization; keep the scheduler manual.
2. Person A publishes an available resource with the prefix and a future availability window. Person B waits at least five seconds (or refreshes) and confirms that the same named resource appears on their computer. A changes its description/location, and B confirms the updated value. This proves shared reads and writes rather than two isolated SQLite demos.
3. B switches to a different demo organization and submits a Mission for that resource's available time. The designated administrator confirms it appears in their Mission list/history. User Mission lists are scoped to their current organization, so A's ordinary user view need not show B's Mission.
4. Stop and restart B's local server. Confirm the resource/Mission/history persist. Opening another browser profile can test a separate user session.
5. Run an isolated admin demo and review the report. It saves a `demo_runs` report; the scenario animation/report is not a substitute for the actual shared-write test above. For a real batch test, wait until a test Mission is due (the normal cutoff is 24 hours before its start), then have one admin run the batch.
6. To test evidence end-to-end, use an eligible approved/in-use/completed test Mission and the affected organization's session. Submit a dispute with a small, non-sensitive evidence file (and the required amount for compensation). The admin must be able to preview/download it; verify the object exists in the private bucket in Supabase. A Storage badge or read-only bucket lookup alone does not prove uploads work.
7. Withdraw test Missions and mark test resources offline through the application when finished. Test/history/evidence records persist; these actions are not a complete deletion. Use the test project's retention policy for any owner-managed cleanup, and never rerun migration to erase test records.

## Optional: offline SQLite demo

SQLite mode needs Python 3.10+ and no third-party packages. It does not share data between machines. Explicitly override cloud mode if `.env` exists:

```bash
# macOS/Linux
CAMPUS_DB_BACKEND=sqlite PORT=8765 python3 server.py
```

```powershell
# Windows PowerShell
$env:CAMPUS_DB_BACKEND = 'sqlite'
$env:PORT = '8765'
py -3 server.py
# After stopping, remove the override before cloud testing:
Remove-Item Env:CAMPUS_DB_BACKEND
Remove-Item Env:PORT
```

The application preserves and incrementally migrates the local SQLite data, and makes a timestamped local backup. This backup is not a backup of Supabase. Never delete a working database to reset a demo.

## Shared database behavior

When two or more local servers use the same `SUPABASE_DATABASE_URL`:

- New resources and Missions are written to the same Postgres database.
- The user app and administrator console read the same records.
- The user app and admin console poll the shared database version every five seconds and refresh after a change.
- Dispute evidence is uploaded to the private `campus-evidence` Supabase Storage bucket. The database stores its name, type, size, and cloud object path.
- The local browser session identifies the organization being simulated. It is not production identity management.

Sharing the same server Secret key gives every person who receives it backend-level access through their local copy. This is acceptable only for trusted hackathon participants. For an internet-facing deployment, keep the credentials on one hosted backend and never distribute them to end users.

## User app workflow

1. Open **Resources** and publish a resource with its type, capability, schedule, location, status, external replacement cost, and cost reference source.
2. Open **Mission** and submit a short request. The platform builds feasible resource options.
3. Before the deadline, reorder and select acceptable options. The user sees the option order but not the fairness weights.
4. After the deadline, the administrator batch checks time and capacity conflicts, ranks competing Missions with the fairness policy, and approves a feasible option or places the Mission on the waitlist.
5. The user sees the approved Mission/resource/space result, starts use at the scheduled time, and confirms return.
6. If a provider does not show up or a resource is damaged, the affected organization can submit a dispute and upload evidence.

## Latest allocation control

The admin **Run allocation batch** button explicitly sends `force: true` and processes the current open/waitlisted queue immediately, even before a Mission cutoff. Background scheduling keeps the deadline gate. Use the manual action intentionally on your shared test project; ordinary users cannot trigger it.

## v3 visual demo for recording

Open the admin console → **Demo tests**. Select **Run all scenarios** (or one scenario). The new **Demo studio** starts playing automatically:

- Mission cards show Open → Frozen → Ranking → Allocated/Waitlisted.
- Resource cards show capacity, free slots and the current booking.
- Animated routes show which request is competing, withdrawn, proposed or booked.
- Fairness cards show each input × policy weight, its points contribution and the total score.
- The no-show scenario keeps the alternative unbooked until requester confirmation; the preference scenario visibly skips infeasible P1 and books P2.

Click **Recording view** to fill the screen. Use **Pause**, **Next**, **Back**, **Restart** or a numbered step to narrate; choose 3, 5 or 8 seconds per step. All frames are loaded once. Playback runs locally with CSS animations and pauses admin polling while playing/recording, so individual steps do not wait for cloud round trips. Written reports and scheduler settings are collapsed below the player.

These are deterministic teaching scenarios using the report's policy snapshot, not a replay of live transactions or proof that the allocation engine passed a test. Business records are unchanged; a report is stored in `demo_runs`. Older stored reports need to be rerun once to generate the new visual frames. Real shared-database and evidence-upload behavior still uses the acceptance tests above.

## Administrator console

The administrator console is an overlay inside the original website; it is not a separate public website. It is hidden from normal users and requires the administrator password.

Set `CAMPUS_ADMIN_PASSWORD` in your private root `.env` before starting. Use that value to log in. Without it the server reads `.admin-password` or generates one when the file is absent and password authentication is first used. This repository has a historically tracked password file, so do not rely on it as a private default. Do not place real passwords in shell commands, screenshots or README examples.

The console can:

- Run due allocation batches and inspect conflicts, waitlists, bookings, and replacement states.
- Review resources, organizations, credit scores, contribution, and freeze status.
- Record provider no-shows and automatically reduce provider credit.
- Review dispute descriptions and evidence files. An approved monetary compensation dispute freezes the provider until the affected organization marks it resolved.
- Change scheduler settings and fairness policy weights. These controls are admin-only.
- Run isolated, explainable demos without changing live resources, Missions, or bookings.
- Review persistent history and decision snapshots.

Available demo scenarios:

- **Conflict and fairness** — two Missions compete for one camera after the application window closes.
- **Withdrawal and release** — one Mission withdraws before the batch, so the conflict disappears.
- **No-show and replacement** — the original booking is released and the requester must confirm a replacement.
- **Option preferences** — the first option is infeasible, so the batch tries the second option in the submitted order.

## Main API groups

User API:

- `GET /api/bootstrap`
- `GET /api/history`
- `POST /api/resources`
- `PATCH /api/resources/:id`
- `POST /api/missions`
- `POST /api/missions/:id/preferences`
- `POST /api/missions/:id/checkout`
- `POST /api/missions/:id/complete`
- `POST /api/missions/:id/withdraw`
- `POST /api/missions/:id/disputes`
- `POST /api/disputes/:id/resolve`

Administrator API:

- `POST /api/admin/login`
- `GET /api/admin/bootstrap`
- `POST /api/admin/allocation/run`
- `POST /api/admin/demo/run`
- `PATCH /api/admin/config`

Administrator endpoints require the separate HttpOnly `admin_sid` cookie. User and administrator data are written to the same configured database.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `py`, `python3` or Git is missing | Install Python 3.10+ and Git; open a new terminal. On Linux install the distribution's Python venv package if venv creation fails. |
| `psycopg` is missing | Use the same `.venv` Python for both `-m pip install -r requirements-cloud.txt` and startup. Avoid system `pip --user`. |
| Preflight reports placeholder/missing configuration | Check `.env` is next to `server.py`, not `.env.txt`, and replace all placeholders. The owner must privately provide real values. |
| PostgreSQL password rejected | Verify the **database password**, not the Storage key; copy the Session pooler username and URL-encode the password component. |
| `Cloud initialization timed out` | Initialization did not finish within two minutes. Stop other local servers and check database connectivity/locks. If `Server started. Loading shared data` appeared, the server is listening but its data request is failing; share only the new fixed diagnostic message. |
| DNS failure, proxy 403 or timeout | Check project status, DNS, HTTPS 443 and pooler TCP 5432 access, VPN/firewall/IP restrictions. Use the actual Session pooler URI for IPv4. Allowing only HTTPS does not enable direct PostgreSQL. |
| TLS certificate error | Obtain the correct CA through the provider/administrator. Configure `PGSSLROOTCERT` in your shell for preflight and `sslrootcert` in the DSN for the app. Do not disable certificate verification. |
| Missing schema/data or permission denied | Ask the owner to prepare the test database and review role permissions. Do not rerun migrations against a populated shared project. |
| Automatic scheduler enabled | Have the owner switch to Manual before multiple collaborators start their servers. |
| Storage HTTP 401/403 | Check the server key belongs to the same project and is authorized; a proxy 403 can instead mean blocked network access. Do not share full error dumps or keys. |
| Evidence bucket missing/public | Owner creates the configured private bucket or changes its visibility. Preflight does not make these changes. |
| App says Local SQLite | Remove an old shell `CAMPUS_DB_BACKEND=sqlite` override; use the received `.env` and restart. |
| Port already in use | Stop your previous process or change `PORT` in `.env` to 8766 and browse that port. Check for a shell override. |
| Records differ between collaborators | Confirm the owner gave both the same test project, cloud mode is active, and each is viewing the correct organization; wait for the five-second refresh. |
| Evidence upload fails after preflight passes | The preflight only verifies reads. Check upload permissions, configured bucket and file constraints; perform the real browser upload test. |

Share only the check's PASS/FAIL lines when asking for help. Never share `.env`, the DSN, keys or credential screenshots in GitHub issues.

## Repository and secret policy

- `.env`, local virtual environments and private handoff folders are ignored; `.env.example` is a placeholder template only.
- Existing tracked files are not protected by new ignore rules. The historical `.admin-password` must be overridden; previously exposed credentials must be rotated.
- Real Supabase keys and database passwords must never be committed or placed in frontend code.
- The tracked SQLite demo is not the shared source of truth in cloud mode. Local startup backups do not protect cloud data.
- Migration preserves local files but can overwrite matching cloud IDs. Only the owner manages migrations after backups and comparison.

## Validation status

The launcher and read-only diagnostic have 17 passing automated tests. Launcher readiness, browser-opening timing, child-process cleanup and safe failure paths were tested on Linux, along with real first-time dependency installation and reuse. Windows/macOS launch wrappers have not been run on their native operating systems. Earlier cloud checks in the onboarding environment were blocked by DNS/egress restrictions; no successful live cloud connection or migration from that environment is claimed. Each collaborator must run the preflight on their own network and complete the two-person acceptance test. The owner reports their own local cloud connection works; that does not establish access from other networks.

## Implementation decisions

Some details were not specified in the original brief, so the MVP makes these explicit choices:

- Local HttpOnly sessions and organization switching simulate multiple organizations; this is not production identity authentication.
- A `bookings` table represents time and capacity reservations. A reserved booking does not permanently change the resource lifecycle state.
- Taking a provider resource offline releases its active bookings and marks affected Missions as waiting for replacement confirmation.
- The fairness total score is stored in the user-facing Mission result; the component weights remain administrator-only.
- Real payments, maps, external identity providers, and public object storage are outside the local MVP scope.
- The database is the single source of truth. Writes are committed to the configured backend, history entries are persistent, and both clients refresh from the same database version.
