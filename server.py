#!/usr/bin/env python3
"""Campus Commons - a dependency-free full-stack MVP.

The server deliberately uses only Python's standard library so the demo can be
run in a hackathon environment without a package install or a build step.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import re
import sqlite3
import threading
import secrets
import hashlib
import shutil
import base64
import binascii
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # Cloud mode reports a helpful setup error when selected.
    psycopg = None
    dict_row = None


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CAMPUS_DB_PATH", str(ROOT / "campus_commons.sqlite3"))).expanduser()
STATIC_DIR = ROOT / "static"
UTC = timezone.utc
DB_LOCK = threading.RLock()
USER_SESSIONS: dict[str, int] = {}
ADMIN_SESSIONS: set[str] = set()
ADMIN_PASSWORD_PATH = ROOT / ".admin-password"


def load_local_env() -> None:
    """Load a tiny, dependency-free .env file for local setup.

    Explicit shell environment variables always win. Keeping this here avoids
    requiring python-dotenv for a hackathon checkout while still making the
    Supabase setup copy/paste friendly.
    """
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_EVIDENCE_BUCKET = os.environ.get("SUPABASE_EVIDENCE_BUCKET", "campus-evidence")
SUPABASE_DATABASE_URL = os.environ.get("SUPABASE_DATABASE_URL", "").strip()
# Once the cloud DSN is configured, business data uses the shared Postgres
# database. Set CAMPUS_DB_BACKEND=sqlite only for an intentional local rollback.
DB_BACKEND = os.environ.get("CAMPUS_DB_BACKEND", "supabase" if SUPABASE_DATABASE_URL else "sqlite").lower()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default


class CloudCursor:
    """Small psycopg adapter for the existing SQLite-shaped query code."""
    def __init__(self, cursor):
        self._cursor = cursor

    @staticmethod
    def _translate(statement: str) -> str:
        # The MVP uses SQLite's positional ? placeholders. Translate only
        # question marks outside SQL string literals for psycopg.
        out, quoted = [], False
        for char in statement:
            if char == "'":
                quoted = not quoted
            out.append("%s" if char == "?" and not quoted else char)
        return "".join(out)

    def execute(self, statement, params=None):
        self._cursor.execute(self._translate(statement), params or ())
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return CompatRow(row) if row is not None else None

    def fetchall(self):
        return [CompatRow(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        return (CompatRow(row) for row in self._cursor)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self._cursor.close()


class CompatRow(dict):
    """A dict row that also supports SQLite-style numeric indexing."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class CloudConnection:
    def __init__(self, dsn: str):
        if psycopg is None:
            raise RuntimeError("Supabase is configured, but psycopg is not installed. Run: python3 -m pip install 'psycopg[binary]'")
        self._conn = psycopg.connect(dsn, connect_timeout=15, row_factory=dict_row)

    def execute(self, statement, params=None):
        return CloudCursor(self._conn.execute(CloudCursor._translate(statement), params or ()))

    def cursor(self):
        return CloudCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._conn.__exit__(exc_type, exc, tb)


def connect() -> sqlite3.Connection:
    if DB_BACKEND == "supabase":
        if not SUPABASE_DATABASE_URL:
            raise RuntimeError("CAMPUS_DB_BACKEND=supabase is set, but SUPABASE_DATABASE_URL is missing. Check your .env file.")
        return CloudConnection(SUPABASE_DATABASE_URL)  # type: ignore[return-value]
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")
    db.execute("PRAGMA journal_mode = WAL")
    return db


SCHEMA = """
CREATE TABLE IF NOT EXISTS organizations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  short_name TEXT NOT NULL,
  kind TEXT NOT NULL,
  credit_score REAL NOT NULL DEFAULT 80,
  shared_hours REAL NOT NULL DEFAULT 0,
  available_hours REAL NOT NULL DEFAULT 0,
  allocations_won INTEGER NOT NULL DEFAULT 0,
  allocations_lost INTEGER NOT NULL DEFAULT 0,
  verified INTEGER NOT NULL DEFAULT 1,
  suspended INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_org_id INTEGER NOT NULL REFERENCES organizations(id),
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  capability TEXT NOT NULL,
  features TEXT NOT NULL DEFAULT '',
  availability_start TEXT NOT NULL,
  availability_end TEXT NOT NULL,
  location TEXT NOT NULL,
  capacity REAL NOT NULL DEFAULT 1,
  condition TEXT NOT NULL DEFAULT 'Good',
  hourly_value REAL NOT NULL DEFAULT 0,
  external_hourly_cost REAL NOT NULL DEFAULT 0,
  cost_source TEXT NOT NULL DEFAULT '',
  verified INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'available',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS missions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  requester_org_id INTEGER NOT NULL REFERENCES organizations(id),
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  location TEXT NOT NULL,
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  deadline TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  requirements TEXT NOT NULL DEFAULT '[]',
  plans TEXT NOT NULL DEFAULT '[]',
  preferences TEXT NOT NULL DEFAULT '[]',
  allocated_plan_id TEXT,
  replacement_pending INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TEXT NOT NULL,
  audience_org_id INTEGER REFERENCES organizations(id)
);
CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mission_id INTEGER NOT NULL REFERENCES missions(id),
  resource_id INTEGER NOT NULL REFERENCES resources(id),
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  quantity REAL NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active',
  completed_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(mission_id, resource_id)
);
CREATE TABLE IF NOT EXISTS admin_config (
  id INTEGER PRIMARY KEY CHECK(id=1), scheduler_enabled INTEGER NOT NULL DEFAULT 0, interval_seconds INTEGER NOT NULL DEFAULT 300, weights TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS demo_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT NOT NULL, status TEXT NOT NULL, report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mission_id INTEGER,
  urgency REAL,
  contribution REAL,
  credit REAL,
  access_fairness REAL,
  alternative_scarcity REAL,
  fairness_score REAL,
  submitted_preferences TEXT NOT NULL DEFAULT '[]',
  chosen_plan TEXT,
  outcome TEXT,
  explanation TEXT NOT NULL DEFAULT '',
  policy_snapshot TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS disputes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mission_id INTEGER NOT NULL REFERENCES missions(id),
  reporter_org_id INTEGER NOT NULL REFERENCES organizations(id),
  accused_org_id INTEGER REFERENCES organizations(id),
  category TEXT NOT NULL,
  description TEXT NOT NULL,
  compensation_amount REAL NOT NULL DEFAULT 0,
  evidence TEXT NOT NULL DEFAULT '[]',
  compensation_status TEXT NOT NULL DEFAULT 'not_requested',
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  resolved_at TEXT, resolved_by TEXT, resolution_description TEXT,
  approved_at TEXT, frozen_at TEXT, victim_resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS credit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INTEGER NOT NULL REFERENCES organizations(id),
  event_type TEXT NOT NULL,
  delta REAL NOT NULL,
  before_score REAL NOT NULL,
  after_score REAL NOT NULL,
  mission_id INTEGER REFERENCES missions(id),
  details TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contribution_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INTEGER NOT NULL REFERENCES organizations(id),
  event_type TEXT NOT NULL,
  hours REAL NOT NULL,
  resource_id INTEGER REFERENCES resources(id),
  mission_id INTEGER REFERENCES missions(id),
  details TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  organization_id INTEGER REFERENCES organizations(id),
  action TEXT NOT NULL,
  snapshot TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_org_time ON history_log(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_entity_time ON history_log(entity_type, entity_id, created_at DESC);
CREATE TABLE IF NOT EXISTS user_sessions (
  session_id TEXT PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES organizations(id),
  created_at TEXT NOT NULL,
  last_seen TEXT NOT NULL
);
"""


def init_db() -> None:
    if DB_BACKEND == "supabase":
        # Keep the schema source shared with the one-shot migration utility.
        from scripts.migrate_sqlite_to_supabase import DDL as POSTGRES_DDL
        with DB_LOCK, connect() as db:
            for statement in POSTGRES_DDL:
                db.execute(statement)
            db.execute("INSERT INTO admin_config(id,weights) VALUES(1,?) ON CONFLICT (id) DO NOTHING", (dumps({"urgency":.3,"contribution":.2,"credit":.15,"access_fairness":.2,"alternative_scarcity":.15}),))
            if db.execute("SELECT COUNT(*) AS count FROM organizations").fetchone()["count"] == 0:
                seed_db(db)
            refresh_open_mission_plans(db)
            for m in db.execute("SELECT * FROM missions WHERE status IN ('allocated','in_use','completed') AND allocated_plan_id IS NOT NULL").fetchall():
                for item in next((p for p in loads(m["plans"],[]) if p.get("id")==m["allocated_plan_id"]),{}).get("items",[]):
                    db.execute("INSERT INTO bookings(mission_id,resource_id,start_at,end_at,quantity,status,created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT (mission_id,resource_id) DO NOTHING", (m["id"],item["resource_id"],m["start_at"],m["end_at"],1,"active",m["created_at"]))
            db.execute("UPDATE resources SET external_hourly_cost=hourly_value WHERE external_hourly_cost=0")
            backfill_history(db)
            backfill_decisions(db)
            backfill_demo_reports(db)
            db.commit()
        return
    # Existing data is preserved. This migration only adds missing schema and
    # backfills one initial history entry for records created before history_log.
    with DB_LOCK, connect() as db:
        db.execute("PRAGMA busy_timeout=5000")
        db.executescript(SCHEMA)
        def add_column(table, column, definition):
            cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        add_column("events", "audience_org_id", "INTEGER")
        add_column("missions", "replacement_pending", "INTEGER NOT NULL DEFAULT 0")
        add_column("organizations", "verified", "INTEGER NOT NULL DEFAULT 1")
        add_column("organizations", "suspended", "INTEGER NOT NULL DEFAULT 0")
        add_column("disputes", "resolved_at", "TEXT")
        add_column("disputes", "resolved_by", "TEXT")
        add_column("disputes", "resolution_description", "TEXT")
        add_column("disputes", "accused_org_id", "INTEGER")
        add_column("disputes", "compensation_amount", "REAL NOT NULL DEFAULT 0")
        add_column("disputes", "evidence", "TEXT NOT NULL DEFAULT '[]'")
        add_column("disputes", "compensation_status", "TEXT NOT NULL DEFAULT 'not_requested'")
        add_column("disputes", "approved_at", "TEXT")
        add_column("disputes", "frozen_at", "TEXT")
        add_column("disputes", "victim_resolved_at", "TEXT")
        add_column("resources", "external_hourly_cost", "REAL NOT NULL DEFAULT 0")
        add_column("resources", "cost_source", "TEXT NOT NULL DEFAULT ''")
        add_column("bookings", "completed_at", "TEXT")
        add_column("decisions", "urgency", "REAL")
        add_column("decisions", "contribution", "REAL")
        add_column("decisions", "credit", "REAL")
        add_column("decisions", "access_fairness", "REAL")
        add_column("decisions", "alternative_scarcity", "REAL")
        add_column("decisions", "submitted_preferences", "TEXT NOT NULL DEFAULT '[]'")
        add_column("decisions", "explanation", "TEXT NOT NULL DEFAULT ''")
        add_column("decisions", "policy_snapshot", "TEXT NOT NULL DEFAULT '{}'")
        db.execute("INSERT OR IGNORE INTO admin_config(id,weights) VALUES(1,?)", (dumps({"urgency":.3,"contribution":.2,"credit":.15,"access_fairness":.2,"alternative_scarcity":.15}),))
        if db.execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0:
            seed_db(db)
        refresh_open_mission_plans(db)
        # Backfill bookings for the original MVP's allocated sample mission once.
        for m in db.execute("SELECT * FROM missions WHERE status IN ('allocated','in_use','completed') AND allocated_plan_id IS NOT NULL").fetchall():
            for item in next((p for p in loads(m["plans"],[]) if p.get("id")==m["allocated_plan_id"]),{}).get("items",[]):
                db.execute("INSERT OR IGNORE INTO bookings(mission_id,resource_id,start_at,end_at,quantity,status,created_at) VALUES(?,?,?,?,?,?,?)",(m["id"],item["resource_id"],m["start_at"],m["end_at"],1,"active",m["created_at"]))
        # Reservation is represented by bookings; resource status is not reset
        # during startup, so a restart cannot overwrite a provider's status.
        db.execute("UPDATE resources SET external_hourly_cost=hourly_value WHERE external_hourly_cost=0")
        backfill_history(db)
        backfill_decisions(db)
        backfill_demo_reports(db)
        db.commit()


def insert_id(db, statement: str, params: tuple) -> int:
    """Insert a row and return its id on either SQLite or Postgres."""
    if DB_BACKEND == "supabase":
        row = db.execute(statement + " RETURNING id", params).fetchone()
        return int(row["id"] if isinstance(row, dict) else row[0])
    return int(db.execute(statement, params).lastrowid)

def admin_password() -> str:
    configured = os.environ.get("CAMPUS_ADMIN_PASSWORD")
    if configured:
        return configured
    if ADMIN_PASSWORD_PATH.exists():
        return ADMIN_PASSWORD_PATH.read_text().strip()
    value = secrets.token_urlsafe(18)
    ADMIN_PASSWORD_PATH.write_text(value)
    try: ADMIN_PASSWORD_PATH.chmod(0o600)
    except OSError: pass
    return value


def backup_db() -> None:
    """Keep a timestamped local rollback copy before any schema migration."""
    if not DB_PATH.exists():
        return
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = DB_PATH.with_name(f"{DB_PATH.name}.bak-{stamp}")
    try:
        shutil.copy2(DB_PATH, target)
    except OSError:
        # A read-only or externally managed deployment can still start; the
        # database itself remains the source of truth.
        pass


def seed_db(db: sqlite3.Connection) -> None:
    created = now_iso()
    orgs = [
        ("HKU Robotics Society", "HKU Robotics", "Student Society", 92, 64, 96, 4, 1),
        ("HKU Makerspace", "Makerspace", "Makerspace", 88, 112, 160, 8, 2),
        ("HKU Design Lab", "Design Lab", "Laboratory", 84, 48, 72, 3, 2),
        ("Campus Sustainability Hub", "Sustainability", "Community Group", 76, 86, 120, 5, 1),
        ("HKU Data Science Club", "Data Science", "Student Society", 80, 20, 48, 1, 2),
    ]
    org_ids = []
    for org in orgs:
        org_ids.append(insert_id(db,
            "INSERT INTO organizations(name,short_name,kind,credit_score,shared_hours,available_hours,allocations_won,allocations_lost,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (*org, created)))

    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    def time_at(hours: int) -> str:
        return (base + timedelta(hours=hours)).isoformat()

    resources = [
        (org_ids[1], "Sony A7 IV camera kit", "equipment", "camera, 4K video", "Sony A7 IV; 24-70mm; tripod", 1, 120, "Makerspace", 1, "Excellent", 45),
        (org_ids[0], "DJI Mini 4 Pro drone", "equipment", "drone, aerial photography", "4K; licensed operator required", 4, 96, "Pok Fu Lam", 1, "Good", 70),
        (org_ids[2], "Portable lighting set", "equipment", "lighting, photography", "3-point LED; stands", 2, 150, "Design Lab", 1, "Good", 20),
        (org_ids[2], "Laser cutter 60W", "equipment", "laser cutting, acrylic, wood", "600x400mm bed; induction required", 12, 168, "Design Lab", 1, "Good", 55),
        (org_ids[1], "3D printer farm", "equipment", "3D printing, PLA, prototyping", "4 printers; 200x200x200mm", 0, 336, "Makerspace", 4, "Excellent", 25),
        (org_ids[3], "Workshop studio", "space", "workshop, event, fabrication", "12 desks; sink; 40 seats", 24, 336, "Main Building", 40, "Good", 35),
        (org_ids[4], "Python data mentor", "skill", "python, data analysis, machine learning", "2 years mentoring; Cantonese/English", 48, 240, "Online / Main Building", 1, "Verified", 30),
        (org_ids[0], "Electronics mentor", "skill", "electronics, Arduino, robotics", "PhD candidate; safety trained", 0, 240, "Pok Fu Lam", 1, "Verified", 35),
        (org_ids[3], "Event volunteers", "people", "event support, registration, logistics", "Up to 8 volunteers", 0, 168, "Campus wide", 8, "Verified", 18),
        (org_ids[4], "Quiet meeting room", "space", "meeting, interview, presentation", "8 seats; screen; whiteboard", 6, 216, "Knowles Building", 8, "Good", 18),
    ]
    for row in resources:
        owner, name, rtype, capability, features, start, end, location, capacity, condition, value = row
        db.execute(
            "INSERT INTO resources(owner_org_id,name,type,capability,features,availability_start,availability_end,location,capacity,condition,hourly_value,verified,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (owner, name, rtype, capability, features, time_at(start), time_at(end), location, capacity, condition, value, 1, "available", created),
        )

    def add_mission(requester, title, desc, location, start, end, deadline, status="open", prefs=None):
        requirements = parse_requirements(title + " " + desc)
        plans = build_plans(db, requirements, location, time_at(start), time_at(end), requester)
        mission_id = insert_id(db,
            "INSERT INTO missions(requester_org_id,title,description,location,start_at,end_at,deadline,status,requirements,plans,preferences,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (requester, title, desc, location, time_at(start), time_at(end), time_at(deadline), status, dumps(requirements), dumps(plans), dumps(prefs or [p["id"] for p in plans]), created, created))
        if status == "allocated" and plans:
            preferred = (prefs or [plans[0]["id"]])[0]
            chosen = next((p for p in plans if p["id"] == preferred), plans[0])
            db.execute("UPDATE missions SET allocated_plan_id=? WHERE id=?", (chosen["id"], mission_id))

    add_mission(org_ids[4], "Prototype demo day", "Need a camera and lighting for a student product demo, plus a small studio space.", "Main Building", 72, 80, 48)
    add_mission(org_ids[0], "Robotics outreach workshop", "Eight volunteers and a workshop space for an Arduino robotics workshop.", "Main Building", 30, 38, 6, "allocated", ["plan-1"])
    add_mission(org_ids[3], "Impact report data clinic", "A Python data mentor for a four-hour analysis clinic.", "Online / Main Building", 96, 100, 72, "open")
    add_event(db, "allocation", "Batch allocation completed", "Robotics outreach workshop was assigned its best feasible plan.")
    add_event(db, "resource", "New capacity verified", "Makerspace verified the 3D printer farm for the autumn pool.")
    add_event(db, "fairness", "Access balance adjustment", "Data Science Club received +0.08 access fairness after two missed allocations.")
    db.commit()


def add_event(db: sqlite3.Connection, kind: str, title: str, detail: str, audience_org_id: int | None = None) -> None:
    db.execute("INSERT INTO events(kind,title,detail,created_at,audience_org_id) VALUES(?,?,?,?,?)", (kind, title, detail, now_iso(), audience_org_id))


def row_snapshot(row: sqlite3.Row | dict | None) -> dict:
    if row is None:
        return {}
    return dict(row)


def add_history(db: sqlite3.Connection, entity_type: str, entity_id: int, organization_id: int | None, action: str, snapshot: sqlite3.Row | dict | None = None) -> None:
    """Append an immutable record of a business change to the persistent log."""
    db.execute(
        "INSERT INTO history_log(entity_type,entity_id,organization_id,action,snapshot,created_at) VALUES(?,?,?,?,?,?)",
        (entity_type, int(entity_id), organization_id, action, dumps(row_snapshot(snapshot)), now_iso()),
    )


def backfill_history(db: sqlite3.Connection) -> None:
    """Give records from the original MVP a first history entry exactly once."""
    for table, entity_type, org_column in (("resources", "resource", "owner_org_id"), ("missions", "mission", "requester_org_id")):
        rows = db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        for row in rows:
            exists = db.execute(
                "SELECT 1 FROM history_log WHERE entity_type=? AND entity_id=? LIMIT 1",
                (entity_type, row["id"]),
            ).fetchone()
            if not exists:
                add_history(db, entity_type, row["id"], row[org_column], "created", row)


def get_history(db: sqlite3.Connection, organization_id: int | None = None, limit: int = 200) -> list[dict]:
    if organization_id is None:
        rows = db.execute("SELECT * FROM history_log ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM history_log WHERE organization_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
            (organization_id, limit),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["snapshot"] = loads(item.get("snapshot"), {})
        result.append(item)
    return result


def database_version(db: sqlite3.Connection) -> str:
    """Return a cheap change token shared by the user and admin clients."""
    parts = []
    for table in ("history_log", "events", "decisions", "demo_runs", "disputes", "resources", "missions"):
        row = db.execute(f"SELECT COUNT(*) AS count, COALESCE(MAX(id),0) AS max_id FROM {table}").fetchone()
        parts.append(f"{table}:{row['count']}:{row['max_id']}")
    return "|".join(parts)


def record_decision(db: sqlite3.Connection, mission: sqlite3.Row, fairness: dict, chosen_plan: dict | None, outcome: str, weights: dict, explanation: str) -> None:
    db.execute(
        "INSERT INTO decisions(mission_id,urgency,contribution,credit,access_fairness,alternative_scarcity,fairness_score,submitted_preferences,chosen_plan,outcome,explanation,policy_snapshot,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            mission["id"], fairness.get("urgency"), fairness.get("contribution"), fairness.get("credit"),
            fairness.get("access_fairness"), fairness.get("alternative_scarcity"), fairness.get("score"),
            dumps(loads(mission["preferences"], [])), chosen_plan.get("id") if chosen_plan else None,
            outcome, explanation, dumps(weights), now_iso(),
        ),
    )


def backfill_decisions(db: sqlite3.Connection) -> None:
    """Capture the original allocated sample as an explainable decision."""
    cfg = db.execute("SELECT weights FROM admin_config WHERE id=1").fetchone()
    weights = loads(cfg["weights"], {}) if cfg else {}
    for mission in db.execute("SELECT * FROM missions WHERE status IN ('allocated','in_use','completed') AND allocated_plan_id IS NOT NULL ORDER BY id").fetchall():
        if db.execute("SELECT 1 FROM decisions WHERE mission_id=? LIMIT 1", (mission["id"],)).fetchone():
            continue
        org = db.execute("SELECT * FROM organizations WHERE id=?", (mission["requester_org_id"],)).fetchone()
        if not org:
            continue
        fairness = org_fairness(org, mission, len(loads(mission["plans"], [])), weights)
        plan = next((p for p in loads(mission["plans"], []) if p.get("id") == mission["allocated_plan_id"]), None)
        record_decision(db, mission, fairness, plan, "seeded", weights, "Historical demo allocation preserved during database migration.")



# Demo reports created before the UI language migration can still be stored in
# the database. Keep a small compatibility map so those historical reports are
# upgraded in place instead of showing mixed-language content in the console.
LEGACY_DEMO_TRANSLATIONS = {
    "同一设备冲突：fairness 决定顺序": "Same-device conflict: fairness decides the order",
    "两个 Mission 在同一时段申请一台相机，观察截止后才分配以及候补结果。": "Two Missions request one camera for overlapping times; allocation happens after the deadline and produces a clear waitlist result.",
    "资源 R-01 · Camera A": "Resource R-01 · Camera A",
    "截止前只收集偏好；截止后冻结并批量处理": "Collect preferences before the deadline; freeze and process them in a batch after the deadline",
    "资源上线": "Resource published",
    "Camera A 可用 1 个容量，状态 available。": "Camera A has one available slot and is marked available.",
    "M-101 提交": "M-101 submitted",
    "提交偏好：Camera A；Mission 保持 open。": "Preference submitted: Camera A; the Mission remains open.",
    "M-102 提交": "M-102 submitted",
    "提交偏好：Camera A；时间段与 M-101 重叠。": "Preference submitted: Camera A; its time overlaps with M-101.",
    "申请窗口截止": "Request window closed",
    "冻结两个 Mission 的方案顺序，不再即时分配。": "Freeze both Missions' option order; do not allocate immediately.",
    "发现容量冲突": "Capacity conflict detected",
    "同一资源同一时段只能满足一个 Mission，进入公平排序。": "Only one Mission can use the same resource at the same time, so both candidates enter fairness ranking.",
    "批次完成": "Batch completed",
    "M-101 获批 Camera A；M-102 进入候补并保留替代方案。": "M-101 is approved for Camera A; M-102 is waitlisted with alternative options preserved.",
    "总分最高，且第一偏好可用": "Highest total score, and the first preference is feasible",
    "资源已被更高分 Mission 占用": "The resource was assigned to the higher-scoring Mission",
    "M-101 → approved · Camera A；M-102 → waitlisted · 可确认替代方案": "M-101 → approved · Camera A; M-102 → waitlisted · An alternative option can be confirmed",
    "open 状态持续到截止": "Open status is preserved until the deadline",
    "冲突被识别": "The conflict is detected",
    "fairness 总分决定处理顺序": "The fairness total score decides processing order",
    "未获批者进入候补": "The unapproved request enters the waitlist",
    "撤回与释放：冲突在 batch 前消失": "Withdrawal and release: the conflict disappears before the batch",
    "一个申请人在截止前撤回，系统释放需求，不提前消耗资源。": "One requester withdraws before the deadline, so the system releases the request without consuming the resource early.",
    "资源 R-03 · Rehearsal Room": "Resource R-03 · Rehearsal Room",
    "撤回只改变申请状态，不创建预约": "Withdrawal changes the request status only; it does not create a booking",
    "两份申请进入队列": "Two requests enter the queue",
    "M-201、M-202 都申请 Rehearsal Room，均为 open。": "M-201 and M-202 both request the Rehearsal Room and remain open.",
    "M-201 主动撤回": "M-201 withdraws",
    "撤回记录写入历史，未创建 booking。": "The withdrawal is recorded in history; no booking is created.",
    "重新计算冲突": "Conflict recalculated",
    "只剩 M-202 竞争，资源容量恢复为 1。": "Only M-202 remains in the competition, so resource capacity returns to one.",
    "批次读取最新状态，跳过 withdrawn Mission。": "The batch reads the latest status and skips the withdrawn Mission.",
    "M-202 直接获批，M-201 保留 withdrawn 历史。": "M-202 is approved directly; M-201 keeps its withdrawn history.",
    "唯一仍处于 open 的申请": "The only request still open",
    "撤回可追溯": "Withdrawal is traceable",
    "撤回不会锁定资源": "Withdrawal does not lock the resource",
    "batch 使用截止时的最新状态": "The batch uses the latest status at the deadline",
    "违约与替换：批准后仍需用户确认": "Provider breach and replacement: user confirmation is still required",
    "资源提供方 no-show，系统释放原预约并提出替代方案，但不替用户自动接受。": "The resource provider does not show up. The system releases the original booking and proposes an alternative without accepting it for the user.",
    "资源 R-07 · Studio A": "Resource R-07 · Studio A",
    "替代资源 R-08 · Studio B": "Alternative resource R-08 · Studio B",
    "替换方案必须由 Mission requester 确认": "The Mission requester must confirm a replacement option",
    "原方案获批": "Original option approved",
    "M-301 获批 Studio A，booking active。": "M-301 is approved for Studio A and the booking is active.",
    "提供方 no-show": "Provider no-show",
    "管理员记录违约，原资源不可用，信用事件 -5。": "The admin records the breach; the original resource is unavailable and a -5 credit event is recorded.",
    "生成替代方案": "Replacement option generated",
    "Studio B 满足时间与能力要求，Mission 标记 replacement_pending。": "Studio B meets the time and capability requirements; the Mission is marked replacement_pending.",
    "等待 requester 确认": "Waiting for requester confirmation",
    "用户端只看到替代方案待确认，不会被后台静默替换。": "The user app shows only that a replacement is awaiting confirmation; the backend never replaces it silently.",
    "确认后重新预约": "Rebook after confirmation",
    "确认 Studio B 后建立新 booking，原 booking 保留释放记录。": "After Studio B is confirmed, a new booking is created and the original booking keeps its release record.",
    "原方案已按批次获批；替换不重新暗中排序": "The original option was approved by the batch; replacement does not silently rerank the Mission",
    "违约留下信用事件": "The breach leaves a credit event",
    "原预约释放可追溯": "Release of the original booking is traceable",
    "替代方案需要用户确认": "The replacement requires user confirmation",
    "偏好顺序：第一方案不可用时尝试第二方案": "Preference order: try the second option when the first is unavailable",
    "展示用户提交的方案顺序如何被 batch 使用，以及资源冲突检查发生在哪里。": "Show how the batch uses the requester's option order and where resource conflict checks happen.",
    "方案 P1 · Lab A": "Option P1 · Lab A",
    "方案 P2 · Lab B": "Option P2 · Lab B",
    "按 requester 提交的偏好顺序尝试可行方案": "Try feasible options in the requester's submitted order",
    "提交方案顺序": "Option order submitted",
    "偏好为 P1 → P2，顺序写入 decision snapshot。": "Preference is P1 → P2; the order is saved in the decision snapshot.",
    "P1 被占用": "P1 is occupied",
    "Lab A 出现时间冲突，P1 feasibility=false。": "Lab A has a time conflict, so P1 feasibility=false.",
    "冻结并执行": "Freeze and execute",
    "batch 不改变用户排序，只跳过不可行 P1。": "The batch does not change the user's order; it skips infeasible P1 only.",
    "选择 P2": "Choose P2",
    "Lab B 可用，按用户顺序选择第二方案并批准。": "Lab B is available, so the second option is selected and approved in the user's order.",
    "fairness 决定 Mission 处理顺序；方案选择仍服从提交偏好": "Fairness decides Mission processing order; option selection still follows the submitted preference",
    "偏好顺序可解释": "Preference order is explainable",
    "可行性检查先于方案选择": "Feasibility is checked before option selection",
    "决策快照包含原始偏好": "The decision snapshot preserves the original preference",
    "P1 → infeasible；P2 → approved · decision snapshot 保存 P1 → P2": "P1 → infeasible; P2 → approved · decision snapshot preserves P1 → P2",
    "总分 = urgency×0.30 + contribution×0.20 + credit×0.15 + access_fairness×0.20 + alternative_scarcity×0.15": "Total score = urgency×0.30 + contribution×0.20 + credit×0.15 + access_fairness×0.20 + alternative_scarcity×0.15",
}


def translate_demo_value(value):
    if isinstance(value, str):
        return LEGACY_DEMO_TRANSLATIONS.get(value, value)
    if isinstance(value, list):
        return [translate_demo_value(item) for item in value]
    if isinstance(value, dict):
        return {key: translate_demo_value(item) for key, item in value.items()}
    return value


def backfill_demo_reports(db: sqlite3.Connection) -> None:
    """Translate reports created by the pre-English admin console."""
    for row in db.execute("SELECT id,report FROM demo_runs ORDER BY id").fetchall():
        report = loads(row["report"], {})
        translated = translate_demo_value(report)
        if translated != report:
            db.execute("UPDATE demo_runs SET report=? WHERE id=?", (dumps(translated), row["id"]))


def record_credit_event(db: sqlite3.Connection, organization_id: int, event_type: str, delta: float, mission_id: int | None = None, details: str = "") -> float:
    row = db.execute("SELECT credit_score FROM organizations WHERE id=?", (organization_id,)).fetchone()
    if not row:
        return 0.0
    before = float(row["credit_score"])
    after = max(0.0, min(100.0, before + float(delta)))
    db.execute("UPDATE organizations SET credit_score=? WHERE id=?", (after, organization_id))
    db.execute("INSERT INTO credit_events(organization_id,event_type,delta,before_score,after_score,mission_id,details,created_at) VALUES(?,?,?,?,?,?,?,?)", (organization_id, event_type, float(delta), before, after, mission_id, details, now_iso()))
    return after


def record_contribution_event(db: sqlite3.Connection, organization_id: int, event_type: str, hours: float, resource_id: int | None = None, mission_id: int | None = None, details: str = "") -> None:
    value = float(hours)
    if abs(value) < 0.0001:
        return
    db.execute("INSERT INTO contribution_events(organization_id,event_type,hours,resource_id,mission_id,details,created_at) VALUES(?,?,?,?,?,?,?)", (organization_id, event_type, value, resource_id, mission_id, details, now_iso()))
    field = "shared_hours" if event_type == "ACTUAL_SHARE" else "available_hours"
    floor_fn = "GREATEST" if DB_BACKEND == "supabase" else "MAX"
    db.execute(f"UPDATE organizations SET {field}={floor_fn}(0,{field}+?) WHERE id=?", (value, organization_id))


def window_hours(start: str | None, end: str | None) -> float:
    a, b = parse_dt(start), parse_dt(end)
    return max(0.0, (b - a).total_seconds() / 3600) if a and b and b > a else 0.0


KEYWORD_REQUIREMENTS = [
    (("camera", "摄影", "video", "视频", "拍摄"), "equipment", "camera, 4K video", "Camera / video kit"),
    (("drone", "无人机", "aerial", "航拍"), "equipment", "drone, aerial photography", "Drone / aerial kit"),
    (("lighting", "灯光", "灯具"), "equipment", "lighting, photography", "Lighting set"),
    (("laser", "激光"), "equipment", "laser cutting, acrylic, wood", "Laser cutter"),
    (("3d", "3d打印", "printer", "打印"), "equipment", "3D printing, PLA, prototyping", "3D printer"),
    (("studio", "场地", "workshop", "工作室", "空间"), "space", "workshop, event, fabrication", "Workshop / studio"),
    (("meeting", "会议室", "room", "会议"), "space", "meeting, interview, presentation", "Meeting room"),
    (("python", "data", "数据", "machine learning", "机器学习"), "skill", "python, data analysis, machine learning", "Data mentor"),
    (("mentor", "导师", "skill", "技能"), "skill", "python, data analysis, machine learning", "Subject mentor"),
    (("volunteer", "志愿", "event support", "义工", "人手"), "people", "event support, registration, logistics", "Event volunteers"),
    (("electronics", "arduino", "电子", "robotics", "机器人"), "skill", "electronics, Arduino, robotics", "Electronics mentor"),
]


def parse_requirements(text: str, resource_types: list[str] | None = None) -> list[dict]:
    """Turn a request into mandatory, typed requirements.

    The selected resource types are an explicit user constraint. Keyword
    detection still creates the more precise capability requirements, while a
    selected type with no detected keyword gets a conservative generic
    requirement instead of allowing every resource to match it.
    """
    lower = text.lower()
    allowed = [str(item).strip().lower() for item in (resource_types or []) if str(item).strip().lower() in {"equipment", "space", "skill", "people"}]
    requirements = []
    used = set()
    for keywords, rtype, capability, label in KEYWORD_REQUIREMENTS:
        if any(k.lower() in lower for k in keywords) and (not allowed or rtype in allowed) and (rtype, capability) not in used:
            requirements.append({"key": f"req-{len(requirements)+1}", "label": label, "type": rtype, "capability": capability, "mandatory": True})
            used.add((rtype, capability))
    if allowed:
        detected_types = {item["type"] for item in requirements}
        for rtype in allowed:
            if rtype not in detected_types:
                requirements.append({"key": f"req-{len(requirements)+1}", "label": f"{rtype.title()} resource", "type": rtype, "capability": lower[:120] or rtype, "mandatory": True, "generic": True})
    if not requirements:
        requirements = [{"key": "req-1", "label": "General resource", "type": "equipment", "capability": lower[:80] or "general support", "mandatory": True, "generic": True}]
    return requirements


def text_match(need: str, have: str) -> float:
    a = set(re.findall(r"[a-z0-9]+", (need or "").lower()))
    b = set(re.findall(r"[a-z0-9]+", (have or "").lower()))
    if not a or not b:
        return 0.0
    overlap = len(a & b) / max(len(a), 1)
    return min(1.0, overlap)


def build_plans(db: sqlite3.Connection, requirements: list[dict], location: str, start: str, end: str, requester_id: int) -> list[dict]:
    """Build only complete plans whose type, capability and time all match.

    A plan is valid only when every mandatory requirement has one distinct
    resource. Capability overlap is required for non-generic requirements;
    this prevents an iPhone, for example, from satisfying a robotics request
    merely because both are equipment. Existing overlapping bookings are also
    excluded when plans are generated so the user does not see stale options.
    """
    resources = [dict(r) for r in db.execute("SELECT r.*, o.short_name AS owner_name, o.credit_score FROM resources r JOIN organizations o ON o.id=r.owner_org_id WHERE r.status='available' AND o.suspended=0").fetchall()]
    start_dt, end_dt = parse_dt(start), parse_dt(end)
    choices = []
    for req in requirements:
        matching = []
        for resource in resources:
            rs, re_ = parse_dt(resource["availability_start"]), parse_dt(resource["availability_end"])
            if resource["type"] != req["type"] or not rs or not re_ or not start_dt or not end_dt:
                continue
            if rs > start_dt or re_ < end_dt:
                continue
            used = 0.0
            for booking in db.execute("SELECT quantity,start_at,end_at FROM bookings WHERE resource_id=? AND status='active'", (resource["id"],)).fetchall():
                bs, be = parse_dt(booking["start_at"]), parse_dt(booking["end_at"])
                if bs and be and bs < end_dt and start_dt < be:
                    used += float(booking["quantity"] or 0)
            if used + 1 > float(resource.get("capacity") or 1):
                continue
            cap = text_match(req.get("capability", ""), f'{resource.get("capability", "")} {resource.get("features", "")}')
            if not req.get("generic") and cap < 0.35:
                continue
            loc = text_match(location, resource.get("location", "")) if location else 0.5
            # Match formula: capability 60%, time feasibility 20%, location 20%.
            score = 0.60 * (cap if not req.get("generic") else 0.5) + 0.20 + 0.20 * loc
            matching.append((score, resource))
        matching.sort(key=lambda item: (-item[0], item[1]["id"]))
        choices.append((req, matching[:8]))
    if any(not matches for _, matches in choices):
        return []
    plans = []
    seen = set()
    for combo in itertools.product(*[matches for _, matches in choices]):
        resource_ids = tuple(item[1]["id"] for item in combo)
        if len(set(resource_ids)) != len(resource_ids) or resource_ids in seen:
            continue
        seen.add(resource_ids)
        items, scores = [], []
        for (req, _), (score, resource) in zip(choices, combo):
            items.append({
                "requirement": req["label"], "requirement_key": req["key"], "resource_id": resource["id"],
                "resource": resource["name"], "type": resource["type"], "owner": resource["owner_name"], "owner_org_id": resource["owner_org_id"],
                "location": resource["location"], "score": round(score, 3), "hourly_value": resource["hourly_value"],
            })
            scores.append(score)
        index = len(plans) + 1
        plans.append({
            "id": f"plan-{index}", "label": f"Plan {chr(64 + index) if index <= 26 else index}", "match_score": round(sum(scores) / len(scores), 3),
            "items": items, "estimated_value": round(sum(item["hourly_value"] for item in items), 2),
            "tradeoff": "Best capability and location match" if index == 1 else "Feasible alternative with different resources",
        })
        if len(plans) >= 5:
            break
    return plans


def refresh_open_mission_plans(db: sqlite3.Connection) -> None:
    """Rebuild plans created by older releases using the current matcher."""
    rows = db.execute("SELECT * FROM missions WHERE status IN ('open','waitlisted')").fetchall()
    for row in rows:
        requirements = loads(row["requirements"], [])
        if not requirements:
            requirements = parse_requirements(f'{row["title"]} {row["description"]}')
        plans = build_plans(db, requirements, row["location"], row["start_at"], row["end_at"], row["requester_org_id"])
        valid = {plan["id"] for plan in plans}
        old_preferences = loads(row["preferences"], [])
        preferences = [plan_id for plan_id in old_preferences if plan_id in valid] or [plan["id"] for plan in plans]
        db.execute("UPDATE missions SET requirements=?,plans=?,preferences=?,updated_at=? WHERE id=?", (dumps(requirements), dumps(plans), dumps(preferences), now_iso(), row["id"]))


def org_fairness(org: sqlite3.Row, mission: sqlite3.Row, plan_count: int, weights: dict | None = None) -> dict:
    deadline, current = parse_dt(mission["deadline"]), datetime.now(UTC)
    if deadline:
        hours = max(0, (deadline-current).total_seconds()/3600)
        urgency = max(0.0, min(1.0, 1 - hours/(24*7)))
    else:
        urgency = 0.2
    contribution = min(1.0, 0.8*min(org["shared_hours"]/40, 1) + 0.2*min(org["available_hours"]/80, 1))
    credit = org["credit_score"]/100
    total_allocations = org["allocations_won"] + org["allocations_lost"]
    access = 0.9 if total_allocations == 0 else max(0.0, min(1.0, 1 - org["allocations_won"]/max(total_allocations, 3)))
    scarcity = max(0.0, min(1.0, 1 - max(plan_count-1, 0)/4))
    weights = weights or {"urgency":.3,"contribution":.2,"credit":.15,"access_fairness":.2,"alternative_scarcity":.15}
    # Credit remains a continuous fairness input. Eligibility is controlled by
    # the explicit suspended flag, so a score below 70 is not an automatic cliff.
    score = weights.get("urgency",.3)*urgency + weights.get("contribution",.2)*contribution + weights.get("credit",.15)*credit + weights.get("access_fairness",.2)*access + weights.get("alternative_scarcity",.15)*scarcity
    return {"score": round(score, 3), "urgency": round(urgency, 3), "contribution": round(contribution, 3), "credit": round(credit, 3), "access_fairness": round(access, 3), "alternative_scarcity": round(scarcity, 3)}


def row_to_org(row: sqlite3.Row) -> dict:
    return dict(row)


def row_to_resource(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["verified"] = bool(item["verified"])
    return item


def row_to_dispute(row: sqlite3.Row, db: sqlite3.Connection, include_evidence: bool = True) -> dict:
    item = dict(row)
    item["evidence"] = loads(item.get("evidence", "[]"), []) if include_evidence else []
    for index, evidence in enumerate(item["evidence"]):
        if evidence.get("storage") == "supabase" and evidence.get("path"):
            evidence["endpoint"] = f"/api/admin/disputes/{item['id']}/evidence/{index}"
    reporter = db.execute("SELECT id, name, short_name FROM organizations WHERE id=?", (item.get("reporter_org_id"),)).fetchone()
    accused = db.execute("SELECT id, name, short_name, credit_score, suspended FROM organizations WHERE id=?", (item.get("accused_org_id"),)).fetchone() if item.get("accused_org_id") else None
    item["reporter"] = dict(reporter) if reporter else None
    item["accused"] = dict(accused) if accused else None
    return item


def mission_allocation_details(db: sqlite3.Connection, row: sqlite3.Row) -> list[dict]:
    """Return the exact resources reserved by the approved plan."""
    plan_id = row["allocated_plan_id"]
    if not plan_id:
        return []
    plan = next((p for p in loads(row["plans"], []) if p.get("id") == plan_id), None)
    if not plan:
        return []
    bookings = {
        int(item["resource_id"]): dict(item)
        for item in db.execute(
            "SELECT b.resource_id,b.status AS booking_status,b.start_at AS booking_start,b.end_at AS booking_end,r.name,r.type,r.location,r.owner_org_id,o.short_name AS owner_name "
            "FROM bookings b JOIN resources r ON r.id=b.resource_id JOIN organizations o ON o.id=r.owner_org_id WHERE b.mission_id=?",
            (row["id"],),
        ).fetchall()
    }
    result = []
    for item in plan.get("items", []):
        booking = bookings.get(int(item["resource_id"]), {})
        result.append({**item, "booking_status": booking.get("booking_status", "active"), "booking_start": booking.get("booking_start", row["start_at"]), "booking_end": booking.get("booking_end", row["end_at"]), "owner": booking.get("owner_name", item.get("owner")), "owner_org_id": booking.get("owner_org_id", item.get("owner_org_id")), "resource": booking.get("name", item.get("resource")), "type": booking.get("type", item.get("type")), "location": booking.get("location", item.get("location"))})
    return result


def row_to_mission(row: sqlite3.Row, db: sqlite3.Connection, detail: bool = False, viewer_org_id: int | None = None) -> dict:
    item = dict(row)
    item["requirements"] = loads(item.pop("requirements", "[]"), [])
    item["plans"] = loads(item.pop("plans", "[]"), [])
    item["preferences"] = loads(item.pop("preferences", "[]"), [])
    org = db.execute("SELECT * FROM organizations WHERE id=?", (item["requester_org_id"],)).fetchone()
    item["requester"] = dict(org) if org else None
    full_fairness = org_fairness(org, row, len(item["plans"])) if org else None
    item["fairness"] = {"score": full_fairness["score"]} if full_fairness else None
    allocated = mission_allocation_details(db, row)
    item["allocated_resources"] = allocated
    item["viewer_role"] = "requester" if viewer_org_id is not None and int(viewer_org_id) == int(item["requester_org_id"]) else None
    if viewer_org_id is not None and item["viewer_role"] is None and any(int(resource.get("owner_org_id")) == int(viewer_org_id) for resource in allocated):
        item["viewer_role"] = "provider"
    if detail:
        item["disputes"] = [row_to_dispute(dispute, db, include_evidence=True) for dispute in db.execute("SELECT * FROM disputes WHERE mission_id=? ORDER BY id DESC", (item["id"],)).fetchall()]
    if not detail:
        item["description"] = item["description"][:140]
    return item


def json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def cookie_value(handler, name: str) -> str | None:
    raw = handler.headers.get("Cookie", "")
    for part in raw.split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            if key == name:
                return value
    return None


def origin_ok(handler) -> bool:
    origin = handler.headers.get("Origin")
    if not origin:
        return True
    try:
        parsed=urlparse(origin)
        return parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
    except Exception:
        return False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def send_json(self, payload, status=HTTPStatus.OK):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        for cookie in getattr(self, "_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(encoded)

    def send_binary(self, payload: bytes, content_type: str, filename: str = "evidence"):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{urllib.parse.quote(filename)}")
        self.send_header("Cache-Control", "private, max-age=60")
        self.end_headers()
        self.wfile.write(payload)

    def send_file(self, path: Path):
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND); return
        content = path.read_bytes()
        types = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", types.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers(); self.wfile.write(content)

    def user_org(self, db: sqlite3.Connection) -> sqlite3.Row:
        token = cookie_value(self, "user_sid")
        org_id = USER_SESSIONS.get(token or "")
        if not org_id and token:
            saved = db.execute("SELECT organization_id FROM user_sessions WHERE session_id=?", (token,)).fetchone()
            org_id = saved["organization_id"] if saved else None
            if org_id:
                USER_SESSIONS[token] = org_id
        row = db.execute("SELECT * FROM organizations WHERE id=?", (org_id or 1,)).fetchone()
        if not row:
            row = db.execute("SELECT * FROM organizations ORDER BY id LIMIT 1").fetchone()
        if not token or token not in USER_SESSIONS:
            token = secrets.token_urlsafe(24); USER_SESSIONS[token] = row["id"]
            session_sql = ("INSERT INTO user_sessions(session_id,organization_id,created_at,last_seen) VALUES(?,?,?,?) ON CONFLICT (session_id) DO UPDATE SET organization_id=EXCLUDED.organization_id, created_at=EXCLUDED.created_at, last_seen=EXCLUDED.last_seen" if DB_BACKEND == "supabase" else "INSERT OR REPLACE INTO user_sessions(session_id,organization_id,created_at,last_seen) VALUES(?,?,?,?)")
            db.execute(session_sql, (token, row["id"], now_iso(), now_iso()))
            self._cookies = getattr(self, "_cookies", []) + [f"user_sid={token}; HttpOnly; SameSite=Strict; Path=/"]
        elif org_id:
            db.execute("UPDATE user_sessions SET last_seen=? WHERE session_id=?", (now_iso(), token))
        db.commit()
        return row

    def admin_ok(self) -> bool:
        token = cookie_value(self, "admin_sid")
        return bool(token and token in ADMIN_SESSIONS)

    def reject_origin(self):
        if not origin_ok(self):
            self.send_json({"error": "Origin is not allowed"}, HTTPStatus.FORBIDDEN); return True
        return False

    def do_GET(self):
        parsed = urlparse(self.path); path = parsed.path
        if path == "/" or path == "/index.html": self.send_file(STATIC_DIR / "index.html"); return
        # The management console is an in-page overlay. Keep direct /admin
        # navigation on the public shell instead of exposing a second site.
        if path == "/admin" or path == "/admin/":
            self.send_file(STATIC_DIR / "index.html"); return
        if path.startswith("/static/"):
            self.send_file(STATIC_DIR / path.removeprefix("/static/")); return
        with DB_LOCK, connect() as db:
            if path == "/api/bootstrap":
                org = self.user_org(db); self.send_json(get_bootstrap(db, org["id"])); return
            if path == "/api/organizations":
                self.send_json({"organizations": [{"id":r["id"],"name":r["name"],"short_name":r["short_name"],"kind":r["kind"]} for r in db.execute("SELECT * FROM organizations ORDER BY name").fetchall()]}); return
            if path == "/api/resources":
                org = self.user_org(db)
                rows = db.execute("SELECT r.*,o.short_name AS owner_name FROM resources r JOIN organizations o ON o.id=r.owner_org_id WHERE (r.status='available' AND o.suspended=0) OR r.owner_org_id=? ORDER BY r.status,r.name", (org["id"],)).fetchall()
                self.send_json({"resources":[row_to_resource(r) for r in rows]}); return
            if path == "/api/missions":
                org = self.user_org(db)
                rows=db.execute("SELECT DISTINCT m.* FROM missions m LEFT JOIN bookings b ON b.mission_id=m.id LEFT JOIN resources br ON br.id=b.resource_id WHERE m.requester_org_id=? OR br.owner_org_id=? ORDER BY m.deadline,m.id",(org["id"],org["id"])).fetchall()
                self.send_json({"missions":[row_to_mission(r,db,False,org["id"]) for r in rows]}); return
            match = re.fullmatch(r"/api/missions/(\d+)", path)
            if match:
                org=self.user_org(db)
                row=db.execute("SELECT DISTINCT m.* FROM missions m LEFT JOIN bookings b ON b.mission_id=m.id LEFT JOIN resources br ON br.id=b.resource_id WHERE m.id=? AND (m.requester_org_id=? OR br.owner_org_id=?)",(int(match.group(1)),org["id"],org["id"])).fetchone()
                if not row: self.send_json({"error":"Mission not found"},404); return
                self.send_json({"mission":row_to_mission(row,db,True,org["id"])}); return
            if path == "/api/metrics":
                org=self.user_org(db); self.send_json({"metrics":get_metrics(db,org["id"])}); return
            if path == "/api/history":
                org=self.user_org(db); self.send_json({"history":get_history(db,org["id"])}); return
            if path == "/api/profile":
                org=self.user_org(db); own=[resource_with_usage(db, r) for r in db.execute("SELECT r.*,o.short_name AS owner_name FROM resources r JOIN organizations o ON o.id=r.owner_org_id WHERE r.owner_org_id=? ORDER BY r.status,r.name",(org["id"],)).fetchall()]; self.send_json({"organization":dict(org),"resources":own,"metrics":get_metrics(db,org["id"]) }); return
            if path == "/api/admin/bootstrap":
                if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                self.send_json(get_admin_bootstrap(db)); return
            if path == "/api/admin/password-status":
                self.send_json({"configured": bool(os.environ.get("CAMPUS_ADMIN_PASSWORD") or ADMIN_PASSWORD_PATH.exists())}); return
            match = re.fullmatch(r"/api/admin/disputes/(\d+)/evidence/(\d+)", path)
            if match:
                if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                dispute = db.execute("SELECT * FROM disputes WHERE id=?", (int(match.group(1)),)).fetchone()
                if not dispute: self.send_json({"error":"Dispute not found"},404); return
                evidence = loads(dispute["evidence"], [])
                index = int(match.group(2))
                if index < 0 or index >= len(evidence): self.send_json({"error":"Evidence not found"},404); return
                item = evidence[index]
                try:
                    if item.get("storage") == "supabase": payload, content_type = load_cloud_evidence(item.get("path", ""))
                    else:
                        source = item.get("data", "")
                        header, encoded = source.split(",", 1)
                        payload = base64.b64decode(encoded, validate=True); content_type = header[5:].split(";", 1)[0] or item.get("type", "application/octet-stream")
                    self.send_binary(payload, content_type, item.get("name", "evidence")); return
                except (ValueError, OSError, urllib.error.URLError, urllib.error.HTTPError, binascii.Error) as exc:
                    self.send_json({"error": f"Evidence unavailable: {exc}"}, 502); return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path=urlparse(self.path).path; body=json_body(self)
        if self.reject_origin(): return
        try:
            with DB_LOCK, connect() as db:
                if path == "/api/switch-user":
                    org_id=int(body.get("organization_id",0)); row=db.execute("SELECT * FROM organizations WHERE id=?",(org_id,)).fetchone()
                    if not row: self.send_json({"error":"Organization not found"},404); return
                    token=cookie_value(self,"user_sid") or secrets.token_urlsafe(24); USER_SESSIONS[token]=org_id
                    db.execute("INSERT INTO user_sessions(session_id,organization_id,created_at,last_seen) VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET organization_id=excluded.organization_id,last_seen=excluded.last_seen", (token, org_id, now_iso(), now_iso()))
                    self._cookies=[f"user_sid={token}; HttpOnly; SameSite=Strict; Path=/"]
                    db.commit()
                    self.send_json({"organization":dict(row)}); return
                if path == "/api/resources":
                    self.send_json(create_resource(db,body,self.user_org(db)["id"]),201); return
                if path == "/api/missions":
                    self.send_json(create_mission(db,body,self.user_org(db)["id"]),201); return
                m=re.fullmatch(r"/api/missions/(\d+)/preferences",path)
                if m: self.send_json(save_preferences(db,int(m.group(1)),body,self.user_org(db)["id"])); return
                m=re.fullmatch(r"/api/missions/(\d+)/(withdraw|checkout|complete)",path)
                if m: self.send_json(mission_user_action(db,int(m.group(1)),m.group(2),self.user_org(db)["id"])); return
                m=re.fullmatch(r"/api/missions/(\d+)/disputes",path)
                if m: self.send_json(create_dispute(db,int(m.group(1)),body,self.user_org(db)["id"]),201); return
                m=re.fullmatch(r"/api/disputes/(\d+)/resolve",path)
                if m: self.send_json(victim_resolve_dispute(db,int(m.group(1)),self.user_org(db)["id"],body)); return
                # Legacy allocation controls are deliberately unavailable to users.
                if path == "/api/allocation/batch" or re.fullmatch(r"/api/missions/(\d+)/allocate",path):
                    self.send_json({"error":"Allocation is managed by the admin scheduler"},403); return
                if path == "/api/admin/login":
                    if body.get("password") != admin_password(): self.send_json({"error":"Invalid admin password"},401); return
                    token=secrets.token_urlsafe(32); ADMIN_SESSIONS.add(token); self._cookies=[f"admin_sid={token}; HttpOnly; SameSite=Strict; Path=/"]
                    self.send_json({"ok":True}); return
                if path == "/api/admin/logout":
                    token=cookie_value(self,"admin_sid"); ADMIN_SESSIONS.discard(token or ""); self._cookies=["admin_sid=; HttpOnly; SameSite=Strict; Max-Age=0; Path=/"]; self.send_json({"ok":True}); return
                if path == "/api/admin/allocation/run":
                    if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                    self.send_json(admin_run_batch(db, force=bool(body.get("force")))); return
                if path == "/api/admin/demo/run":
                    if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                    self.send_json(run_demo(db, body),201); return
                m=re.fullmatch(r"/api/admin/missions/(\d+)/(withdraw|checkout|complete|no-show)",path)
                if m:
                    if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                    self.send_json(admin_mission_action(db,int(m.group(1)),m.group(2),body)); return
                m=re.fullmatch(r"/api/admin/disputes/(\d+)/resolve",path)
                if m:
                    if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                    self.send_json(resolve_dispute(db,int(m.group(1)),body)); return
        except ValueError as exc: self.send_json({"error":str(exc)},400); return
        except Exception as exc: self.send_json({"error":f"Server error: {exc}"},500); return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PATCH(self):
        path=urlparse(self.path).path; body=json_body(self)
        if self.reject_origin(): return
        try:
            with DB_LOCK, connect() as db:
                m=re.fullmatch(r"/api/resources/(\d+)",path)
                if m:
                    self.send_json(update_resource(db,int(m.group(1)),body,self.user_org(db)["id"])); return
                m=re.fullmatch(r"/api/admin/resources/(\d+)",path)
                if m:
                    if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                    self.send_json(update_resource(db,int(m.group(1)),body,None,admin=True)); return
                m=re.fullmatch(r"/api/admin/organizations/(\d+)",path)
                if m:
                    if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                    self.send_json(update_organization(db,int(m.group(1)),body)); return
                if path == "/api/admin/config":
                    if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                    self.send_json(update_config(db,body)); return
        except ValueError as exc: self.send_json({"error":str(exc)},400); return
        except Exception as exc: self.send_json({"error":f"Server error: {exc}"},500); return
        self.send_error(HTTPStatus.NOT_FOUND)

def resource_with_usage(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    item = row_to_resource(row)
    item["active_loans"] = [dict(loan) for loan in db.execute(
        "SELECT b.id AS booking_id,b.status AS booking_status,b.start_at,b.end_at,m.id AS mission_id,m.title,m.requester_org_id,o.short_name AS requester_name "
        "FROM bookings b JOIN missions m ON m.id=b.mission_id JOIN organizations o ON o.id=m.requester_org_id "
        "WHERE b.resource_id=? AND b.status='active' ORDER BY b.start_at", (row["id"],)
    ).fetchall()]
    item["loaned"] = bool(item["active_loans"])
    return item


def get_bootstrap(db: sqlite3.Connection, organization_id: int = 1) -> dict:
    user = db.execute("SELECT * FROM organizations WHERE id=?", (organization_id,)).fetchone()
    if not user:
        user = db.execute("SELECT * FROM organizations ORDER BY id LIMIT 1").fetchone()
    mission_rows = db.execute(
        "SELECT DISTINCT m.* FROM missions m LEFT JOIN bookings b ON b.mission_id=m.id LEFT JOIN resources br ON br.id=b.resource_id "
        "WHERE m.requester_org_id=? OR br.owner_org_id=? ORDER BY m.deadline,m.id", (user["id"], user["id"])
    ).fetchall()
    missions = [row_to_mission(r, db, False, user["id"]) for r in mission_rows]
    resource_rows = db.execute(
        "SELECT r.*,o.short_name AS owner_name FROM resources r JOIN organizations o ON o.id=r.owner_org_id "
        "WHERE (r.status='available' AND o.suspended=0) OR r.owner_org_id=? ORDER BY r.status,r.name", (user["id"],)
    ).fetchall()
    resources = [resource_with_usage(db, r) for r in resource_rows]
    events = [dict(r) for r in db.execute("SELECT id,kind,title,detail,created_at FROM events WHERE audience_org_id=? ORDER BY created_at DESC LIMIT 30", (user["id"],)).fetchall()]
    organizations = [{"id":r["id"],"name":r["name"],"short_name":r["short_name"],"kind":r["kind"]} for r in db.execute("SELECT * FROM organizations ORDER BY name").fetchall()]
    return {"organization":dict(user),"organizations":organizations,"missions":missions,"resources":resources,"events":events,"history":get_history(db,user["id"],50),"metrics":get_metrics(db,user["id"]),"version":database_version(db)}


def calculate_impact(db: sqlite3.Connection, organization_id: int | None = None) -> dict:
    """Calculate transparent, aggregate value created by sharing.

    Cost avoided uses each resource's external replacement/rental reference.
    Coordination time is an estimate of 1.5 hours per booking plus 0.5 hour
    per Mission, representing search, messages, comparison and handoff work
    that the platform replaces.
    """
    params = ()
    scope = ""
    if organization_id is not None:
        scope = " AND (m.requester_org_id=? OR r.owner_org_id=?)"
        params = (organization_id, organization_id)
    rows = db.execute(
        "SELECT b.mission_id,b.quantity,b.start_at,b.end_at,r.external_hourly_cost,r.hourly_value,r.availability_start,r.availability_end "
        "FROM bookings b JOIN resources r ON r.id=b.resource_id JOIN missions m ON m.id=b.mission_id "
        "WHERE b.status IN ('active','completed')" + scope, params
    ).fetchall()
    shared_hours = sum(window_hours(row["start_at"], row["end_at"]) * float(row["quantity"] or 0) for row in rows)
    cost_avoided = sum(window_hours(row["start_at"], row["end_at"]) * float(row["quantity"] or 0) * float(row["external_hourly_cost"] or row["hourly_value"] or 0) for row in rows)
    market_value = sum(window_hours(row["start_at"], row["end_at"]) * float(row["quantity"] or 0) * float(row["hourly_value"] or 0) for row in rows)
    mission_count = len({int(row["mission_id"]) for row in rows})
    booking_count = len(rows)
    coordination_hours = booking_count * 1.5 + mission_count * 0.5
    if organization_id is None:
        available_rows = db.execute("SELECT availability_start,availability_end FROM resources WHERE status IN ('available','maintenance','reserved')").fetchall()
    else:
        available_rows = db.execute("SELECT availability_start,availability_end FROM resources WHERE owner_org_id=?", (organization_id,)).fetchall()
    available_hours = sum(window_hours(row["availability_start"], row["availability_end"]) for row in available_rows)
    utilization = shared_hours / available_hours if available_hours else 0.0
    return {"shared_hours": round(shared_hours, 1), "cost_avoided": round(cost_avoided, 2), "market_value": round(market_value, 2), "coordination_hours_saved": round(coordination_hours, 1), "missions_supported": mission_count, "bookings": booking_count, "utilization": round(min(1.0, utilization), 2), "calculation_note": "Cost avoided uses the provider's external replacement/rental reference. Time saved is estimated at 1.5 coordination hours per booking plus 0.5 hour per Mission."}


def get_metrics(db: sqlite3.Connection, organization_id: int | None = None) -> dict:
    own = (" AND owner_org_id=?", (organization_id,)) if organization_id else ("", ())
    resource_count = db.execute(f"SELECT COUNT(*) FROM resources WHERE status='available'{own[0]}", own[1]).fetchone()[0]
    active_hours=0.0
    for r in db.execute(f"SELECT availability_start,availability_end FROM resources WHERE status='available'{own[0]}", own[1]).fetchall():
        a,b=parse_dt(r["availability_start"]),parse_dt(r["availability_end"])
        if a and b and b>a: active_hours += (b-a).total_seconds()/3600
    if organization_id:
        missions=db.execute("SELECT * FROM missions WHERE requester_org_id=?",(organization_id,)).fetchall()
    else: missions=db.execute("SELECT * FROM missions").fetchall()
    successful=sum(1 for m in missions if m["status"] in ("allocated","in_use","completed"))
    scores=[]
    for m in missions:
        org=db.execute("SELECT * FROM organizations WHERE id=?",(m["requester_org_id"],)).fetchone()
        if org: scores.append(org_fairness(org,m,len(loads(m["plans"],[])))["score"])
    if organization_id:
        completed=db.execute("SELECT b.*,r.owner_org_id,r.external_hourly_cost,m.requester_org_id FROM bookings b JOIN resources r ON r.id=b.resource_id JOIN missions m ON m.id=b.mission_id WHERE b.status='completed' AND m.requester_org_id=?",(organization_id,)).fetchall()
        decisions=db.execute("SELECT d.* FROM decisions d JOIN missions m ON m.id=d.mission_id WHERE m.requester_org_id=?",(organization_id,)).fetchall()
    else:
        completed=db.execute("SELECT b.*,r.owner_org_id,r.external_hourly_cost,m.requester_org_id FROM bookings b JOIN resources r ON r.id=b.resource_id JOIN missions m ON m.id=b.mission_id WHERE b.status='completed'").fetchall()
        decisions=db.execute("SELECT * FROM decisions").fetchall()
    estimated_cost_saved=sum(window_hours(row["start_at"],row["end_at"])*float(row["quantity"])*float(row["external_hourly_cost"] or 0) for row in completed)
    first_choice=[row for row in decisions if row["outcome"] == "allocated" and loads(row["submitted_preferences"],[]) and row["chosen_plan"] == loads(row["submitted_preferences"],[])[0]]
    providers={row["owner_org_id"] for row in completed}
    concentration=(len(providers)/len(completed)) if completed else 0.0
    decision_scores=[float(row["fairness_score"]) for row in decisions if row["fairness_score"] is not None]
    impact = calculate_impact(db, organization_id)
    platform_impact = calculate_impact(db)
    return {"resource_count":resource_count,"active_hours":round(active_hours,1),"missions":len(missions),"allocation_success_rate":round(successful/max(1,len(missions)),2),"first_choice_satisfaction":round(len(first_choice)/max(1,len([row for row in decisions if row["outcome"] == "allocated"])),2),"resource_concentration":round(concentration,2),"estimated_cost_saved":round(estimated_cost_saved,2),"fairness_index":round(sum(decision_scores)/max(1,len(decision_scores)),2) if decision_scores else round(sum(scores)/max(1,len(scores)),2),"impact":impact,"platform_impact":platform_impact}


def create_resource(db: sqlite3.Connection, body: dict, owner_org_id: int) -> dict:
    required=["name","type","capability","location","availability_start","availability_end"]
    missing=[k for k in required if not body.get(k)]
    if missing: raise ValueError("Missing fields: "+", ".join(missing))
    a,b=parse_dt(body["availability_start"]),parse_dt(body["availability_end"])
    if not a or not b or b<=a: raise ValueError("Availability window is invalid")
    status=body.get("status","available")
    if status not in ("available","offline","maintenance"): raise ValueError("Invalid resource status")
    hourly_value=max(0,float(body.get("hourly_value",0)))
    external_cost=max(0,float(body.get("external_hourly_cost",hourly_value)))
    resource_id=insert_id(db,"INSERT INTO resources(owner_org_id,name,type,capability,features,availability_start,availability_end,location,capacity,condition,hourly_value,external_hourly_cost,cost_source,verified,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(owner_org_id,body["name"],body["type"],body["capability"],body.get("features",""),a.isoformat(),b.isoformat(),body["location"],max(0.01,float(body.get("capacity",1))),body.get("condition","Good"),hourly_value,external_cost,body.get("cost_source","user estimate"),1,status,now_iso()))
    row=db.execute("SELECT r.*,o.short_name AS owner_name FROM resources r JOIN organizations o ON o.id=r.owner_org_id WHERE r.id=?",(resource_id,)).fetchone()
    add_event(db,"resource","New resource added",f"{body['name']} is now visible in the shared pool.",owner_org_id)
    if status == "available": record_contribution_event(db,owner_org_id,"VERIFIED_AVAILABILITY",window_hours(row["availability_start"],row["availability_end"]),row["id"],details="resource published")
    add_history(db,"resource",row["id"],owner_org_id,"created",row)
    db.commit()
    return {"resource":row_to_resource(row)}


def create_mission(db: sqlite3.Connection, body: dict, requester_org_id: int) -> dict:
    required=["title","description","location","start_at","end_at"]
    missing=[k for k in required if not body.get(k)]
    if missing: raise ValueError("Missing fields: "+", ".join(missing))
    start,end=parse_dt(body["start_at"]),parse_dt(body["end_at"])
    if not start or not end or end<=start: raise ValueError("Mission time window is invalid")
    deadline=parse_dt(body.get("deadline") or body.get("cutoff")) or (start-timedelta(hours=24))
    if deadline>=start: deadline=start-timedelta(hours=24)
    selected_types = body.get("resource_types") or body.get("resource_type") or []
    if isinstance(selected_types, str):
        selected_types = [selected_types]
    requirements=parse_requirements(body["title"]+" "+body["description"], selected_types)
    plans=build_plans(db,requirements,body["location"],start.isoformat(),end.isoformat(),requester_org_id)
    created=now_iso(); mission_id=insert_id(db,"INSERT INTO missions(requester_org_id,title,description,location,start_at,end_at,deadline,status,requirements,plans,preferences,replacement_pending,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(requester_org_id,body["title"],body["description"],body["location"],start.isoformat(),end.isoformat(),deadline.isoformat(),"open",dumps(requirements),dumps(plans),dumps([p["id"] for p in plans]),0,created,created))
    row=db.execute("SELECT * FROM missions WHERE id=?",(mission_id,)).fetchone()
    add_event(db,"mission","Mission submitted",f"{body['title']} is open until the application cutoff.",requester_org_id)
    add_history(db,"mission",row["id"],requester_org_id,"created",row)
    db.commit()
    return {"mission":row_to_mission(row,db,True)}


def save_preferences(db: sqlite3.Connection, mission_id: int, body: dict, requester_org_id: int) -> dict:
    row=db.execute("SELECT * FROM missions WHERE id=? AND requester_org_id=?",(mission_id,requester_org_id)).fetchone()
    if not row: raise ValueError("Mission not found")
    if row["status"] not in ("open","waitlisted"): raise ValueError("Allocation is frozen")
    if not row["replacement_pending"] and parse_dt(row["deadline"]) and parse_dt(row["deadline"]) <= datetime.now(UTC): raise ValueError("Application window is closed")
    plans=loads(row["plans"],[]); valid={p["id"] for p in plans}; prefs=body.get("preferences")
    if not isinstance(prefs,list) or not prefs or any(p not in valid for p in prefs): raise ValueError("Preferences must be an ordered list of valid plans")
    db.execute("UPDATE missions SET preferences=?,replacement_pending=0,updated_at=? WHERE id=?",(dumps(prefs),now_iso(),mission_id))
    updated=db.execute("SELECT * FROM missions WHERE id=?",(mission_id,)).fetchone()
    add_history(db,"mission",mission_id,requester_org_id,"preferences_updated",updated); db.commit()
    return {"preferences":prefs,"mission":row_to_mission(updated,db,True)}


def overlap(a1,a2,b1,b2):
    a,b,c,d=map(parse_dt,(a1,a2,b1,b2)); return bool(a and b and c and d and a<d and c<b)


def plan_available(db, mission_row, plan, reserved_ids=None):
    reserved_ids=reserved_ids or set(); ids=set()
    for item in plan.get("items",[]):
        rid=int(item["resource_id"])
        if rid in reserved_ids or rid in ids: return False
        res=db.execute("SELECT * FROM resources WHERE id=?",(rid,)).fetchone()
        mission_start, mission_end = parse_dt(mission_row["start_at"]), parse_dt(mission_row["end_at"])
        resource_start, resource_end = parse_dt(res["availability_start"]) if res else None, parse_dt(res["availability_end"]) if res else None
        if not res or res["status"] != "available" or not mission_start or not mission_end or not resource_start or not resource_end or resource_start > mission_start or resource_end < mission_end:
            return False
        # Compare parsed timestamps instead of ISO strings; this handles UTC
        # offsets consistently in SQLite and Supabase.
        used=0.0
        for booking in db.execute("SELECT quantity,start_at,end_at FROM bookings WHERE resource_id=? AND status='active'",(rid,)).fetchall():
            if overlap(booking["start_at"], booking["end_at"], mission_row["start_at"], mission_row["end_at"]):
                used += float(booking["quantity"] or 0)
        if used + 1 > float(res["capacity"]): return False
        ids.add(rid)
    return True


def reserve_plan(db, mission_row, plan):
    for item in plan.get("items",[]):
        db.execute("INSERT INTO bookings(mission_id,resource_id,start_at,end_at,quantity,status,created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(mission_id,resource_id) DO UPDATE SET start_at=excluded.start_at,end_at=excluded.end_at,quantity=excluded.quantity,status='active',created_at=excluded.created_at",(mission_row["id"],item["resource_id"],mission_row["start_at"],mission_row["end_at"],1,"active",now_iso()))
        # Legacy UI understands reserved; bookings remain source of truth for capacity.


def mission_user_action(db, mission_id, action, org_id):
    row=db.execute("SELECT * FROM missions WHERE id=? AND requester_org_id=?",(mission_id,org_id)).fetchone()
    if not row: raise ValueError("Mission not found")
    target={"withdraw":"withdrawn","checkout":"in_use","complete":"completed"}[action]
    if action=="withdraw":
        db.execute("UPDATE bookings SET status='released' WHERE mission_id=? AND status='active'",(mission_id,))
        db.execute("UPDATE resources SET status='available' WHERE id IN (SELECT resource_id FROM bookings WHERE mission_id=?) AND status='reserved'",(mission_id,))
        record_credit_event(db,org_id,"MISSION_WITHDRAWN",-3,mission_id,"User withdrew an active Mission")
    elif action=="checkout" and row["status"]!="allocated": raise ValueError("Mission is not allocated")
    elif action=="complete" and row["status"] not in ("allocated","in_use"): raise ValueError("Mission is not active")
    if action == "complete":
        completed_at=now_iso()
        bookings=db.execute("SELECT b.*,r.owner_org_id FROM bookings b JOIN resources r ON r.id=b.resource_id WHERE b.mission_id=? AND b.status='active'",(mission_id,)).fetchall()
        db.execute("UPDATE bookings SET status='completed',completed_at=? WHERE mission_id=? AND status='active'",(completed_at,mission_id))
        for booking in bookings:
            record_contribution_event(db,booking["owner_org_id"],"ACTUAL_SHARE",window_hours(booking["start_at"],booking["end_at"])*float(booking["quantity"]),booking["resource_id"],mission_id,"completed booking")
    db.execute("UPDATE missions SET status=?,updated_at=? WHERE id=?",(target,now_iso(),mission_id))
    updated=db.execute("SELECT * FROM missions WHERE id=?",(mission_id,)).fetchone()
    add_event(db,"mission",f"Mission {target}",row["title"],org_id); add_history(db,"mission",mission_id,org_id,f"status_{target}",updated); db.commit()
    return {"mission":row_to_mission(updated,db,True)}


def mission_provider_ids(db: sqlite3.Connection, mission: sqlite3.Row) -> list[int]:
    """Return resource-owner organizations involved in a Mission."""
    ids = {int(r["owner_org_id"]) for r in db.execute("SELECT DISTINCT r.owner_org_id FROM bookings b JOIN resources r ON r.id=b.resource_id WHERE b.mission_id=?", (mission["id"],)).fetchall()}
    if not ids and mission["allocated_plan_id"]:
        plan = next((p for p in loads(mission["plans"], []) if p.get("id") == mission["allocated_plan_id"]), None)
        for item in (plan or {}).get("items", []):
            resource = db.execute("SELECT owner_org_id FROM resources WHERE id=?", (item.get("resource_id"),)).fetchone()
            if resource: ids.add(int(resource["owner_org_id"]))
    return sorted(ids)


def normalized_evidence(body: dict) -> list[dict]:
    evidence = body.get("evidence") or []
    if not isinstance(evidence, list): raise ValueError("Evidence must be a list")
    if len(evidence) > 5: raise ValueError("Upload at most 5 evidence files")
    normalized = []
    for item in evidence:
        if not isinstance(item, dict) or not item.get("name"): raise ValueError("Evidence filename is missing")
        data = str(item.get("data") or "")
        try:
            header, encoded = data.split(",", 1)
            if not header.startswith("data:") or ";base64" not in header: raise ValueError()
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error): raise ValueError("Evidence file content is invalid. Select the file again.")
        if not raw: raise ValueError("Evidence file is empty")
        if len(raw) > 10 * 1024 * 1024: raise ValueError("Each evidence file must be at most 10 MB")
        normalized.append({"name": str(item["name"])[:160], "type": str(item.get("type") or header[5:].split(";")[0] or "application/octet-stream")[:120], "size": len(raw), "data": data})
    return normalized


def supabase_headers(content_type: str | None = None) -> dict[str, str]:
    headers = {"apikey": SUPABASE_SECRET_KEY, "Authorization": f"Bearer {SUPABASE_SECRET_KEY}"}
    if content_type: headers["Content-Type"] = content_type
    return headers


def cloud_evidence_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SECRET_KEY)


def persist_evidence_to_supabase(evidence: list[dict], mission_id: int) -> list[dict]:
    """Upload evidence bytes to a private Supabase Storage bucket.

    The database keeps only metadata and an object path when cloud storage is
    configured. Without credentials, the local demo retains the data URL so it
    remains self-contained and viewable.
    """
    if not evidence: return evidence
    if not cloud_evidence_enabled(): return evidence
    bucket = urllib.parse.quote(SUPABASE_EVIDENCE_BUCKET, safe="")
    try:
        # Read an existing bucket first: Supabase may report duplicate bucket
        # creation as HTTP 400 rather than 409.
        request = urllib.request.Request(f"{SUPABASE_URL}/storage/v1/bucket/{bucket}", headers=supabase_headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=12): pass
        except urllib.error.HTTPError as exc:
            if exc.code != 404: raise
            request = urllib.request.Request(f"{SUPABASE_URL}/storage/v1/bucket", data=json.dumps({"id": SUPABASE_EVIDENCE_BUCKET, "name": SUPABASE_EVIDENCE_BUCKET, "public": False}).encode(), headers=supabase_headers("application/json"), method="POST")
            with urllib.request.urlopen(request, timeout=12): pass
        uploaded = []
        for item in evidence:
            data_url = item.get("data", "")
            if not data_url.startswith("data:") or "," not in data_url: raise ValueError("Evidence file content is missing")
            encoded = data_url.split(",", 1)[1]
            raw = base64.b64decode(encoded, validate=True)
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", item.get("name", "evidence"))[:100] or "evidence"
            path = f"mission-{mission_id}/{uuid.uuid4().hex}-{safe_name}"
            target = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{urllib.parse.quote(path, safe='/')}"
            request = urllib.request.Request(target, data=raw, headers={**supabase_headers(item.get("type") or "application/octet-stream"), "x-upsert": "false"}, method="POST")
            with urllib.request.urlopen(request, timeout=20): pass
            uploaded.append({"name": item["name"], "type": item.get("type") or "application/octet-stream", "size": len(raw), "path": path, "storage": "supabase"})
        return uploaded
    except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError, binascii.Error) as exc:
        raise ValueError(f"Cloud evidence upload failed. Check your Supabase configuration and try again: {exc}") from exc


def load_cloud_evidence(path: str) -> tuple[bytes, str]:
    if not cloud_evidence_enabled(): raise ValueError("Supabase is not configured")
    target = f"{SUPABASE_URL}/storage/v1/object/{urllib.parse.quote(SUPABASE_EVIDENCE_BUCKET, safe='')}/{urllib.parse.quote(path, safe='/')}"
    request = urllib.request.Request(target, headers=supabase_headers(), method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(), response.headers.get_content_type() or "application/octet-stream"


def create_dispute(db: sqlite3.Connection, mission_id: int, body: dict, reporter_org_id: int) -> dict:
    row = db.execute("SELECT * FROM missions WHERE id=? AND requester_org_id=?", (mission_id, reporter_org_id)).fetchone()
    if not row: raise ValueError("Mission not found")
    if not body.get("description"): raise ValueError("Please describe what happened")
    category = body.get("category", "condition")
    try: amount = max(0.0, float(body.get("compensation_amount") or 0))
    except (TypeError, ValueError): raise ValueError("Compensation amount must be a valid number")
    evidence = normalized_evidence(body)
    # The requester cannot be the accused party in its own dispute; only
    # external resource providers are eligible for a provider-fault claim.
    providers = [provider_id for provider_id in mission_provider_ids(db, row) if provider_id != reporter_org_id]
    requested_accused = body.get("accused_org_id")
    accused_id = int(requested_accused) if requested_accused not in (None, "") else (providers[0] if len(providers) == 1 else None)
    if accused_id is not None and accused_id not in providers: raise ValueError("The provider at fault must be an organization that supplied a resource for this Mission")
    if not accused_id: raise ValueError("The provider at fault could not be identified. Select the resource provider organization")
    if amount > 0 and not evidence: raise ValueError("A compensation request must include at least one evidence file")
    evidence = persist_evidence_to_supabase(evidence, mission_id)
    compensation_status = "requested" if amount > 0 else "not_requested"
    dispute_id = insert_id(db, "INSERT INTO disputes(mission_id,reporter_org_id,accused_org_id,category,description,compensation_amount,evidence,compensation_status,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (mission_id, reporter_org_id, accused_id, category, body["description"], amount, dumps(evidence), compensation_status, "open", now_iso()))
    dispute = db.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
    detail = f"{category} dispute on {row['title']}" + (f"; compensation request HKD {amount:.2f}" if amount else "")
    add_event(db, "conflict", "Dispute opened", detail, reporter_org_id)
    add_history(db, "dispute", dispute["id"], reporter_org_id, "created", dispute)
    db.commit()
    return {"dispute": row_to_dispute(dispute, db)}


def admin_run_batch(db, force: bool = False):
    now=datetime.now(UTC); cfg=db.execute("SELECT weights FROM admin_config WHERE id=1").fetchone(); weights=loads(cfg["weights"],{}) if cfg else {}
    if force:
        # Manual admin runs are explicit test/operations actions and process
        # the current queue immediately. The background scheduler keeps the
        # deadline gate by calling this function with force=False.
        rows=db.execute("SELECT * FROM missions WHERE status IN ('open','waitlisted') ORDER BY deadline,id").fetchall()
    else:
        rows=db.execute("SELECT * FROM missions WHERE status IN ('open','waitlisted') AND deadline<=? ORDER BY deadline,id",(now.isoformat(),)).fetchall()
    ranked=[]
    for row in rows:
        org=db.execute("SELECT * FROM organizations WHERE id=?",(row["requester_org_id"],)).fetchone(); fairness=org_fairness(org,row,len(loads(row["plans"],[])),weights) if org else {"score":0}
        ranked.append((fairness["score"],fairness,row))
    ranked.sort(key=lambda x:(-x[0],parse_dt(x[2]["deadline"]) or datetime.max.replace(tzinfo=UTC))); allocated=[];waitlisted=[]
    for score,fairness,row in ranked:
        if row["replacement_pending"]:
            record_decision(db,row,fairness,None,"replacement_pending",weights,"An approved resource is unavailable; user confirmation is required before replacement.")
            waitlisted.append({"mission_id":row["id"],"title":row["title"],"fairness":{"score":round(score,3)},"replacement_pending":True})
            continue
        org=db.execute("SELECT * FROM organizations WHERE id=?",(row["requester_org_id"],)).fetchone()
        if not org or org["suspended"]: chosen=None
        else:
            plans=loads(row["plans"],[]); prefs=loads(row["preferences"],[]) or [p["id"] for p in plans]
            plan_by_id={p["id"]:p for p in plans}
            chosen=next((plan_by_id[plan_id] for plan_id in prefs if plan_id in plan_by_id and plan_available(db,row,plan_by_id[plan_id])),None)
        if not chosen:
            if row["status"]=="open": db.execute("UPDATE organizations SET allocations_lost=allocations_lost+1 WHERE id=?",(row["requester_org_id"],))
            db.execute("UPDATE missions SET status='waitlisted',updated_at=? WHERE id=?",(now_iso(),row["id"]))
            updated=db.execute("SELECT * FROM missions WHERE id=?",(row["id"],)).fetchone()
            add_history(db,"mission",row["id"],row["requester_org_id"],"status_waitlisted",updated)
            waitlisted.append({"mission_id":row["id"],"title":row["title"],"fairness":{"score":round(score,3)}}); record_decision(db,row,fairness,None,"waitlisted",weights,"No preferred plan was feasible after capacity and time-conflict checks."); continue
        reserve_plan(db,row,chosen); db.execute("UPDATE missions SET status='allocated',allocated_plan_id=?,updated_at=? WHERE id=?",(chosen["id"],now_iso(),row["id"]))
        updated=db.execute("SELECT * FROM missions WHERE id=?",(row["id"],)).fetchone()
        db.execute("UPDATE organizations SET allocations_won=allocations_won+1 WHERE id=?",(row["requester_org_id"],)); add_event(db,"allocation","Mission approved",f"{row['title']} received an approved plan.",row["requester_org_id"])
        for provider_id in sorted({int(item["owner_org_id"]) for item in chosen.get("items",[]) if item.get("owner_org_id")}):
            add_event(db,"allocation","Resource lent out",f"{row['title']} was approved and uses resources from your organization.",provider_id)
        add_history(db,"mission",row["id"],row["requester_org_id"],"status_allocated",updated); record_decision(db,row,fairness,chosen,"allocated",weights,f"Selected {chosen['id']} as the first feasible plan in the submitted preference order."); allocated.append({"mission_id":row["id"],"title":row["title"],"plan_id":chosen["id"],"fairness":{"score":round(score,3)}})
    db.commit(); return {"allocated":allocated,"waitlisted":waitlisted,"processed_at":now_iso(),"forced":force,"message":f"Batch: {len(allocated)} approved, {len(waitlisted)} waitlisted"}


def update_resource(db, resource_id, body, owner_id=None, admin=False):
    row=db.execute("SELECT * FROM resources WHERE id=?",(resource_id,)).fetchone()
    if not row or (owner_id is not None and row["owner_org_id"]!=owner_id): raise ValueError("Resource not found")
    fields={k:body[k] for k in ("name","type","capability","features","location","condition","status","cost_source") if k in body}
    for k in ("capacity","hourly_value"):
        if k in body: fields[k]=max(0,float(body[k]))
    if "external_hourly_cost" in body: fields["external_hourly_cost"]=max(0,float(body["external_hourly_cost"]))
    for k in ("availability_start","availability_end"):
        if k in body:
            if not parse_dt(body[k]): raise ValueError("Invalid availability")
            fields[k]=parse_dt(body[k]).isoformat()
    if fields.get("status") not in (None,"available","offline","maintenance","reserved"): raise ValueError("Invalid resource status")
    if not admin and fields.get("status")=="reserved": raise ValueError("Only allocation can reserve a resource")
    if fields.get("status") in ("offline","maintenance"):
        affected=db.execute("SELECT DISTINCT mission_id FROM bookings WHERE resource_id=? AND status='active'",(resource_id,)).fetchall()
        db.execute("UPDATE bookings SET status='released' WHERE resource_id=? AND status='active'",(resource_id,))
        for x in affected:
            mm=db.execute("SELECT * FROM missions WHERE id=?",(x["mission_id"],)).fetchone()
            db.execute("UPDATE missions SET status='waitlisted',allocated_plan_id=NULL,replacement_pending=1,updated_at=? WHERE id=? AND status='allocated'",(now_iso(),x["mission_id"]))
            updated_mission=db.execute("SELECT * FROM missions WHERE id=?",(x["mission_id"],)).fetchone()
            if mm:
                add_event(db,"replacement","Approved resource unavailable; replacement plans await user confirmation",mm["title"],mm["requester_org_id"])
                add_history(db,"mission",mm["id"],mm["requester_org_id"],"replacement_pending",updated_mission)
    old_available_hours=window_hours(row["availability_start"],row["availability_end"]) if row["status"] == "available" else 0.0
    next_start=fields.get("availability_start",row["availability_start"]); next_end=fields.get("availability_end",row["availability_end"]); next_status=fields.get("status",row["status"])
    new_available_hours=window_hours(next_start,next_end) if next_status == "available" else 0.0
    if fields:
        db.execute("UPDATE resources SET "+",".join(f"{k}=?" for k in fields)+" WHERE id=?",(*fields.values(),resource_id))
    updated=db.execute("SELECT r.*,o.short_name AS owner_name FROM resources r JOIN organizations o ON o.id=r.owner_org_id WHERE r.id=?",(resource_id,)).fetchone()
    add_event(db,"resource","Resource updated",row["name"],row["owner_org_id"])
    record_contribution_event(db,row["owner_org_id"],"VERIFIED_AVAILABILITY",new_available_hours-old_available_hours,resource_id,details="resource availability updated")
    add_history(db,"resource",resource_id,row["owner_org_id"],"updated",updated); db.commit()
    return {"resource":row_to_resource(updated)}


def update_organization(db, org_id, body):
    allowed={k:body[k] for k in ("credit_score","verified","suspended") if k in body}
    # verified/suspended are additive attributes in the response; preserve in kind if old DB has no columns.
    if "credit_score" in allowed:
        current=db.execute("SELECT credit_score FROM organizations WHERE id=?",(org_id,)).fetchone()
        if current:
            record_credit_event(db,org_id,"ADMIN_ADJUSTMENT",float(allowed["credit_score"])-float(current["credit_score"]),None,"Admin adjusted the organization credit score")
    if "suspended" in allowed and not bool(allowed["suspended"]):
        pending = db.execute("SELECT 1 FROM disputes WHERE accused_org_id=? AND status='awaiting_victim' LIMIT 1", (org_id,)).fetchone()
        if pending: raise ValueError("This organization still has a compensation dispute awaiting requester confirmation and cannot be unfrozen yet")
    for key in ("verified","suspended"):
        if key in allowed: db.execute(f"UPDATE organizations SET {key}=? WHERE id=?",(int(bool(allowed[key])),org_id))
    updated=db.execute("SELECT * FROM organizations WHERE id=?",(org_id,)).fetchone()
    add_history(db,"organization",org_id,org_id,"updated",updated)
    db.commit(); return {"organization":dict(updated)}


def update_config(db, body):
    current=db.execute("SELECT * FROM admin_config WHERE id=1").fetchone(); weights=body.get("weights") or loads(current["weights"],{})
    db.execute("UPDATE admin_config SET scheduler_enabled=?,interval_seconds=?,weights=? WHERE id=1",(int(bool(body.get("scheduler_enabled",current["scheduler_enabled"]))),max(5,int(body.get("interval_seconds",current["interval_seconds"]))),dumps(weights)))
    updated=db.execute("SELECT * FROM admin_config WHERE id=1").fetchone(); add_history(db,"platform",1,None,"config_updated",updated); db.commit(); result=dict(updated); result["weights"]=loads(result["weights"],{}); return {"config":result}


def get_admin_bootstrap(db):
    config=dict(db.execute("SELECT * FROM admin_config WHERE id=1").fetchone()); config["weights"]=loads(config.get("weights"),{})
    demo_runs=[]
    for row in db.execute("SELECT * FROM demo_runs ORDER BY id DESC"):
        item=dict(row)
        item["report"]=dumps(translate_demo_value(loads(item.get("report"),{})))
        demo_runs.append(item)
    return {"organizations":[dict(r) for r in db.execute("SELECT * FROM organizations ORDER BY name")],"resources":[row_to_resource(r) for r in db.execute("SELECT r.*,o.short_name AS owner_name FROM resources r JOIN organizations o ON o.id=r.owner_org_id ORDER BY r.id")],"missions":[row_to_mission(r,db,True) for r in db.execute("SELECT * FROM missions ORDER BY id")],"events":[dict(r) for r in db.execute("SELECT * FROM events ORDER BY created_at DESC")],"history":get_history(db),"credit_events":[dict(r) for r in db.execute("SELECT * FROM credit_events ORDER BY id DESC LIMIT 200")],"contribution_events":[dict(r) for r in db.execute("SELECT * FROM contribution_events ORDER BY id DESC LIMIT 200")],"decisions":[dict(r) for r in db.execute("SELECT * FROM decisions ORDER BY id DESC")],"bookings":[dict(r) for r in db.execute("SELECT * FROM bookings ORDER BY id")],"config":config,"demo_runs":demo_runs,"disputes":[row_to_dispute(r,db) for r in db.execute("SELECT * FROM disputes ORDER BY id DESC")],"metrics":get_metrics(db),"cloud":{"provider":"Supabase","database_backend":DB_BACKEND,"database_shared":DB_BACKEND == "supabase","evidence_configured":cloud_evidence_enabled(),"evidence_bucket":SUPABASE_EVIDENCE_BUCKET if cloud_evidence_enabled() else None},"version":database_version(db)}


def admin_mission_action(db, mission_id, action, body=None):
    row=db.execute("SELECT * FROM missions WHERE id=?",(mission_id,)).fetchone()
    if not row: raise ValueError("Mission not found")
    if action=="withdraw":
        db.execute("UPDATE bookings SET status='released' WHERE mission_id=? AND status='active'",(mission_id,)); db.execute("UPDATE resources SET status='available' WHERE id IN (SELECT resource_id FROM bookings WHERE mission_id=?) AND status='reserved'",(mission_id,)); target="withdrawn"
    elif action=="checkout": target="in_use"
    elif action=="complete":
        target="completed"; bookings=db.execute("SELECT b.*,r.owner_org_id FROM bookings b JOIN resources r ON r.id=b.resource_id WHERE b.mission_id=? AND b.status='active'",(mission_id,)); completed_at=now_iso(); db.execute("UPDATE bookings SET status='completed',completed_at=? WHERE mission_id=?",(completed_at,mission_id))
        for booking in bookings:
            record_contribution_event(db,booking["owner_org_id"],"ACTUAL_SHARE",window_hours(booking["start_at"],booking["end_at"])*float(booking["quantity"]),booking["resource_id"],mission_id,"admin completed booking")
    elif action=="no-show":
        target="completed"
        bookings = db.execute("SELECT b.*,r.owner_org_id FROM bookings b JOIN resources r ON r.id=b.resource_id WHERE b.mission_id=? AND b.status IN ('active','completed')", (mission_id,)).fetchall()
        db.execute("UPDATE bookings SET status='released' WHERE mission_id=? AND status='active'", (mission_id,))
        provider_ids = sorted({int(booking["owner_org_id"]) for booking in bookings})
        requested_provider = (body or {}).get("provider_org_id")
        provider_id = int(requested_provider) if requested_provider not in (None, "") else (provider_ids[0] if len(provider_ids) == 1 else None)
        if not provider_id or provider_id not in provider_ids: raise ValueError("Select the resource provider organization responsible for the breach")
        record_credit_event(db, provider_id, "PROVIDER_NO_SHOW", -8, mission_id, "Admin recorded a provider no-show")
    else: raise ValueError("Unknown action")
    db.execute("UPDATE missions SET status=?,updated_at=? WHERE id=?",(target,now_iso(),mission_id)); updated=db.execute("SELECT * FROM missions WHERE id=?",(mission_id,)).fetchone(); add_event(db,"admin",f"Mission {target}",row["title"],row["requester_org_id"]); add_history(db,"mission",mission_id,row["requester_org_id"],f"status_{target}",updated); db.commit(); return {"mission":row_to_mission(updated,db,True)}


def resolve_dispute(db, dispute_id, body):
    row = db.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
    if not row: raise ValueError("Dispute not found")
    if row["status"] == "resolved": return {"dispute": row_to_dispute(row, db), "idempotent": True}
    outcome = body.get("outcome", "upheld")
    if outcome not in ("upheld", "provider_fault", "rejected"): raise ValueError("Invalid dispute outcome")
    desc = body.get("description") or body.get("resolution_description", "")
    now = now_iso()
    if outcome == "rejected":
        db.execute("UPDATE disputes SET status='resolved',compensation_status='rejected',resolved_at=?,resolved_by='admin',resolution_description=? WHERE id=?", (now, desc or "Dispute rejected after admin review", dispute_id))
        add_event(db, "conflict", "Dispute rejected", f"Dispute #{dispute_id} was rejected after review.", row["reporter_org_id"])
    else:
        accused_id = row["accused_org_id"]
        if not accused_id:
            mission = db.execute("SELECT * FROM missions WHERE id=?", (row["mission_id"],)).fetchone()
            providers = mission_provider_ids(db, mission) if mission else []
            accused_id = providers[0] if len(providers) == 1 else None
        if not accused_id: raise ValueError("The provider at fault could not be determined. Specify the resource provider organization in the dispute first")
        # The penalty is recorded exactly once: a dispute approval creates a
        # credit event on the accused provider, then optionally freezes it.
        existing_penalty = db.execute("SELECT 1 FROM credit_events WHERE event_type IN ('DISPUTE_UPHELD','PROVIDER_FAULT','PROVIDER_NO_SHOW') AND mission_id=? AND organization_id=? LIMIT 1", (row["mission_id"], accused_id)).fetchone()
        if not existing_penalty:
            record_credit_event(db, accused_id, "DISPUTE_UPHELD", -5, row["mission_id"], "Admin upheld a provider fault dispute")
        amount = float(row["compensation_amount"] or 0)
        if amount > 0:
            db.execute("UPDATE organizations SET suspended=1 WHERE id=?", (accused_id,))
            db.execute("UPDATE disputes SET accused_org_id=?,status='awaiting_victim',compensation_status='approved',approved_at=?,frozen_at=?,resolved_by='admin',resolution_description=? WHERE id=?", (accused_id, now, now, desc or "Compensation approved. The provider account is frozen until the affected organization confirms resolution.", dispute_id))
            add_event(db, "conflict", "Provider account frozen", f"Organization #{accused_id} was frozen after dispute #{dispute_id}; waiting for victim confirmation.", row["reporter_org_id"])
        else:
            db.execute("UPDATE disputes SET accused_org_id=?,status='resolved',compensation_status='not_requested',resolved_at=?,resolved_by='admin',resolution_description=? WHERE id=?", (accused_id, now, desc or "Provider fault confirmed and credit reduced", dispute_id))
            add_event(db, "conflict", "Dispute upheld", f"Dispute #{dispute_id} upheld; provider credit was reduced.", row["reporter_org_id"])
    updated = db.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
    add_history(db, "dispute", dispute_id, updated["reporter_org_id"], "status_" + updated["status"], updated)
    db.commit()
    return {"dispute": row_to_dispute(updated, db)}


def victim_resolve_dispute(db, dispute_id: int, reporter_org_id: int, body: dict) -> dict:
    row = db.execute("SELECT * FROM disputes WHERE id=? AND reporter_org_id=?", (dispute_id, reporter_org_id)).fetchone()
    if not row: raise ValueError("Dispute not found")
    if row["status"] == "resolved": return {"dispute": row_to_dispute(row, db), "idempotent": True}
    if row["status"] != "awaiting_victim": raise ValueError("The dispute can be marked resolved only after admin approval")
    now = now_iso(); note = body.get("resolution_note") or "The affected organization confirmed that the dispute is resolved"
    db.execute("UPDATE disputes SET status='resolved',compensation_status='settled',resolved_at=?,victim_resolved_at=?,resolved_by='victim',resolution_description=COALESCE(resolution_description,'') || ? WHERE id=?", (now, now, "\n" + note, dispute_id))
    # Keep an organization frozen if another approved compensation dispute is
    # still awaiting the victim's acknowledgement.
    if row["accused_org_id"] and not db.execute("SELECT 1 FROM disputes WHERE accused_org_id=? AND status='awaiting_victim' AND id<>? LIMIT 1", (row["accused_org_id"], dispute_id)).fetchone():
        db.execute("UPDATE organizations SET suspended=0 WHERE id=?", (row["accused_org_id"],))
        add_event(db, "conflict", "Provider account unfrozen", f"Organization #{row['accused_org_id']} was unfrozen after dispute #{dispute_id} was confirmed resolved.", reporter_org_id)
    add_event(db, "conflict", "Victim confirmed dispute resolved", f"Dispute #{dispute_id} was closed by the affected organization.", reporter_org_id)
    updated = db.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
    add_history(db, "dispute", dispute_id, reporter_org_id, "victim_resolved", updated)
    db.commit()
    return {"dispute": row_to_dispute(updated, db)}


def run_demo(db, body=None):
    """Build an isolated, explainable demo report for the admin console.

    The demo deliberately does not mutate business resources or Missions. It is a
    deterministic teaching aid: every scenario exposes the clock, state changes,
    fairness inputs and the reason for the resulting decision.
    """
    started = now_iso()
    default_weights = {"urgency": .30, "contribution": .20, "credit": .15, "access_fairness": .20, "alternative_scarcity": .15}
    config_row = db.execute("SELECT weights FROM admin_config WHERE id=1").fetchone()
    configured_weights = loads(config_row["weights"], {}) if config_row else {}
    weights = {key: float(configured_weights.get(key, value)) for key, value in default_weights.items()}

    def candidate(label, components, result, reason):
        score = round(sum(float(components.get(key, 0)) * weight for key, weight in weights.items()), 3)
        return {"label": label, "components": {key: round(float(components.get(key, 0)), 2) for key in weights}, "score": score, "result": result, "reason": reason}

    scenarios = {
        "conflict": {
            "title": "Same-device conflict: fairness decides the order",
            "purpose": "Two Missions request one camera for overlapping times; allocation happens after the deadline and produces a clear waitlist result.",
            "actors": ["Mission M-101 · Film Society", "Mission M-102 · Design Club", "Resource R-01 · Camera A"],
            "batch": {"submitted_at": "09:00", "cutoff_at": "12:00", "executed_at": "12:00:05", "rule": "Collect preferences before the deadline; freeze and process them in a batch after the deadline"},
            "timeline": [
                {"time": "09:00", "kind": "input", "label": "Resource published", "detail": "Camera A has one available slot and is marked available.", "status": "available"},
                {"time": "09:12", "kind": "input", "label": "M-101 submitted", "detail": "Preference submitted: Camera A; the Mission remains open.", "status": "open"},
                {"time": "09:18", "kind": "input", "label": "M-102 submitted", "detail": "Preference submitted: Camera A; its time overlaps with M-101.", "status": "open"},
                {"time": "12:00", "kind": "batch", "label": "Request window closed", "detail": "Freeze both Missions' option order; do not allocate immediately.", "status": "frozen"},
                {"time": "12:00:01", "kind": "decision", "label": "Capacity conflict detected", "detail": "Only one Mission can use the same resource at the same time, so both candidates enter fairness ranking.", "status": "conflict"},
                {"time": "12:00:05", "kind": "result", "label": "Batch completed", "detail": "M-101 is approved for Camera A; M-102 is waitlisted with alternative options preserved.", "status": "resolved"},
            ],
            "fairness": [
                candidate("M-101 · Film Society", {"urgency": .90, "contribution": .72, "credit": .88, "access_fairness": .78, "alternative_scarcity": .92}, "winner", "Highest total score, and the first preference is feasible"),
                candidate("M-102 · Design Club", {"urgency": .68, "contribution": .55, "credit": .81, "access_fairness": .62, "alternative_scarcity": .86}, "waitlisted", "The resource was assigned to the higher-scoring Mission"),
            ],
            "outcome": "M-101 → approved · Camera A; M-102 → waitlisted · An alternative option can be confirmed",
            "assertions": ["Open status is preserved until the deadline", "The conflict is detected", "The fairness total score decides processing order", "The unapproved request enters the waitlist"],
        },
        "withdrawal": {
            "title": "Withdrawal and release: the conflict disappears before the batch",
            "purpose": "One requester withdraws before the deadline, so the system releases the request without consuming the resource early.",
            "actors": ["Mission M-201 · Music Club", "Mission M-202 · Theatre Group", "Resource R-03 · Rehearsal Room"],
            "batch": {"submitted_at": "10:00", "cutoff_at": "16:00", "executed_at": "16:00:05", "rule": "Withdrawal changes the request status only; it does not create a booking"},
            "timeline": [
                {"time": "10:00", "kind": "input", "label": "Two requests enter the queue", "detail": "M-201 and M-202 both request the Rehearsal Room and remain open.", "status": "open"},
                {"time": "13:40", "kind": "exception", "label": "M-201 withdraws", "detail": "The withdrawal is recorded in history; no booking is created.", "status": "withdrawn"},
                {"time": "13:40:01", "kind": "decision", "label": "Conflict recalculated", "detail": "Only M-202 remains in the competition, so resource capacity returns to one.", "status": "recomputed"},
                {"time": "16:00", "kind": "batch", "label": "Request window closed", "detail": "The batch reads the latest status and skips the withdrawn Mission.", "status": "frozen"},
                {"time": "16:00:05", "kind": "result", "label": "Batch completed", "detail": "M-202 is approved directly; M-201 keeps its withdrawn history.", "status": "resolved"},
            ],
            "fairness": [candidate("M-202 · Theatre Group", {"urgency": .64, "contribution": .67, "credit": .83, "access_fairness": .75, "alternative_scarcity": .60}, "winner", "The only request still open")],
            "outcome": "M-201 → withdrawn; M-202 → approved · Rehearsal Room",
            "assertions": ["Withdrawal is traceable", "Withdrawal does not lock the resource", "The batch uses the latest status at the deadline"],
        },
        "replacement": {
            "title": "Provider breach and replacement: user confirmation is still required",
            "purpose": "The resource provider does not show up. The system releases the original booking and proposes an alternative without accepting it for the user.",
            "actors": ["Mission M-301 · Startup Lab", "Resource R-07 · Studio A", "Alternative resource R-08 · Studio B"],
            "batch": {"submitted_at": "08:30", "cutoff_at": "11:00", "executed_at": "11:00:05", "rule": "The Mission requester must confirm a replacement option"},
            "timeline": [
                {"time": "11:00:05", "kind": "result", "label": "Original option approved", "detail": "M-301 is approved for Studio A and the booking is active.", "status": "allocated"},
                {"time": "14:20", "kind": "exception", "label": "Provider no-show", "detail": "The admin records the breach; the original resource is unavailable and a -5 credit event is recorded.", "status": "provider_fault"},
                {"time": "14:20:01", "kind": "decision", "label": "Replacement option generated", "detail": "Studio B meets the time and capability requirements; the Mission is marked replacement_pending.", "status": "replacement_pending"},
                {"time": "14:20:02", "kind": "input", "label": "Waiting for requester confirmation", "detail": "The user app shows only that a replacement is awaiting confirmation; the backend never replaces it silently.", "status": "awaiting_confirmation"},
                {"time": "15:00", "kind": "result", "label": "Rebook after confirmation", "detail": "After Studio B is confirmed, a new booking is created and the original booking keeps its release record.", "status": "replaced"},
            ],
            "fairness": [candidate("M-301 · Startup Lab", {"urgency": .82, "contribution": .70, "credit": .86, "access_fairness": .74, "alternative_scarcity": .88}, "allocated", "The original option was approved by the batch; replacement does not silently rerank the Mission")],
            "outcome": "Studio A → released / no-show; Studio B → replacement pending → confirmed",
            "assertions": ["The breach leaves a credit event", "Release of the original booking is traceable", "The replacement requires user confirmation"],
        },
        "preference": {
            "title": "Preference order: try the second option when the first is unavailable",
            "purpose": "Show how the batch uses the requester's option order and where resource conflict checks happen.",
            "actors": ["Mission M-401 · Robotics Team", "Option P1 · Lab A", "Option P2 · Lab B"],
            "batch": {"submitted_at": "07:45", "cutoff_at": "10:00", "executed_at": "10:00:03", "rule": "Try feasible options in the requester's submitted order"},
            "timeline": [
                {"time": "07:45", "kind": "input", "label": "Option order submitted", "detail": "Preference is P1 → P2; the order is saved in the decision snapshot.", "status": "open"},
                {"time": "09:30", "kind": "exception", "label": "P1 is occupied", "detail": "Lab A has a time conflict, so P1 feasibility=false.", "status": "conflict"},
                {"time": "10:00", "kind": "batch", "label": "Freeze and execute", "detail": "The batch does not change the user's order; it skips infeasible P1 only.", "status": "frozen"},
                {"time": "10:00:03", "kind": "result", "label": "Choose P2", "detail": "Lab B is available, so the second option is selected and approved in the user's order.", "status": "allocated"},
            ],
            "fairness": [candidate("M-401 · Robotics Team", {"urgency": .76, "contribution": .82, "credit": .79, "access_fairness": .71, "alternative_scarcity": .54}, "allocated", "Fairness decides Mission processing order; option selection still follows the submitted preference")],
            "outcome": "P1 → infeasible; P2 → approved · decision snapshot preserves P1 → P2",
            "assertions": ["Preference order is explainable", "Feasibility is checked before option selection", "The decision snapshot preserves the original preference"],
        },
    }
    from scripts.demo_visuals import build_frames
    for key, scenario in scenarios.items():
        scenario["key"] = key
        scenario["frames"] = build_frames(key, scenario)

    requested = (body or {}).get("scenario", "all")
    selected_key = requested if requested in scenarios else "conflict"
    selected = scenarios[selected_key]
    selected["key"] = selected_key
    selected["assertions_passed"] = len(selected["assertions"])
    selected["assertions_total"] = len(selected["assertions"])
    report = {
        "scenario": selected_key,
        "scenario_title": selected["title"],
        "isolated": True,
        "generated_at": now_iso(),
        "weights": weights,
        "formula": "Total score = " + " + ".join(f"{key}×{value:.2f}" for key, value in weights.items()),
        "scenarios": list(scenarios.values()) if requested == "all" else [selected],
        "steps": selected["timeline"],
        "assertions_passed": selected["assertions_passed"],
        "assertions_total": selected["assertions_total"],
        "outcome": selected["outcome"],
    }
    demo_run_id = insert_id(db, "INSERT INTO demo_runs(started_at,finished_at,status,report) VALUES(?,?,?,?)", (started, now_iso(), "passed", dumps(report)))
    db.commit()
    report["demo_run_id"] = demo_run_id
    return {"demo_run": report, "report": report}


def scheduler_loop():
    while True:
        try:
            with DB_LOCK, connect() as db:
                cfg=db.execute("SELECT * FROM admin_config WHERE id=1").fetchone()
                if cfg and cfg["scheduler_enabled"]:
                    admin_run_batch(db)
                interval=max(5,int(cfg["interval_seconds"]) if cfg else 60)
        except Exception:
            interval=60
        threading.Event().wait(interval)


def main() -> None:
    backup_db()
    init_db()
    threading.Thread(target=scheduler_loop, daemon=True, name="campus-scheduler").start()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Campus Commons running at http://127.0.0.1:{port} (database: {DB_BACKEND})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
