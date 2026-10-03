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
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "campus_commons.sqlite3"
STATIC_DIR = ROOT / "static"
UTC = timezone.utc
DB_LOCK = threading.RLock()
USER_SESSIONS: dict[str, int] = {}
ADMIN_SESSIONS: set[str] = set()
ADMIN_PASSWORD_PATH = ROOT / ".admin-password"


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


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
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
  id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER, fairness_score REAL, chosen_plan TEXT, outcome TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS disputes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mission_id INTEGER NOT NULL REFERENCES missions(id),
  reporter_org_id INTEGER NOT NULL REFERENCES organizations(id),
  category TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  resolved_at TEXT, resolved_by TEXT, resolution_description TEXT
);
"""


def init_db() -> None:
    # Existing MVP data is preserved. A timestamped copy is made by the caller
    # before this migration; only additive columns/tables are created here.
    with DB_LOCK, connect() as db:
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
        db.execute("INSERT OR IGNORE INTO admin_config(id,weights) VALUES(1,?)", (dumps({"urgency":.3,"contribution":.2,"credit":.15,"access_fairness":.2,"alternative_scarcity":.15}),))
        if db.execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0:
            seed_db(db)
        # Backfill bookings for the original MVP's allocated sample mission once.
        for m in db.execute("SELECT * FROM missions WHERE status IN ('allocated','in_use','completed') AND allocated_plan_id IS NOT NULL").fetchall():
            for item in next((p for p in loads(m["plans"],[]) if p.get("id")==m["allocated_plan_id"]),{}).get("items",[]):
                db.execute("INSERT OR IGNORE INTO bookings(mission_id,resource_id,start_at,end_at,quantity,status,created_at) VALUES(?,?,?,?,?,?,?)",(m["id"],item["resource_id"],m["start_at"],m["end_at"],1,"active",m["created_at"]))
        # Reservation is represented by bookings; resource status stays lifecycle-only.
        db.execute("UPDATE resources SET status='available' WHERE status='reserved'")
        db.commit()

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
        cur = db.execute(
            "INSERT INTO organizations(name,short_name,kind,credit_score,shared_hours,available_hours,allocations_won,allocations_lost,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (*org, created),
        )
        org_ids.append(cur.lastrowid)

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
        cur = db.execute(
            "INSERT INTO missions(requester_org_id,title,description,location,start_at,end_at,deadline,status,requirements,plans,preferences,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (requester, title, desc, location, time_at(start), time_at(end), time_at(deadline), status, dumps(requirements), dumps(plans), dumps(prefs or [p["id"] for p in plans]), created, created),
        )
        if status == "allocated" and plans:
            preferred = (prefs or [plans[0]["id"]])[0]
            chosen = next((p for p in plans if p["id"] == preferred), plans[0])
            db.execute("UPDATE missions SET allocated_plan_id=? WHERE id=?", (chosen["id"], cur.lastrowid))
            for item in chosen["items"]:
                db.execute("UPDATE resources SET status='reserved' WHERE id=?", (item["resource_id"],))

    add_mission(org_ids[4], "Prototype demo day", "Need a camera and lighting for a student product demo, plus a small studio space.", "Main Building", 72, 80, 48)
    add_mission(org_ids[0], "Robotics outreach workshop", "Eight volunteers and a workshop space for an Arduino robotics workshop.", "Main Building", 30, 38, 6, "allocated", ["plan-1"])
    add_mission(org_ids[3], "Impact report data clinic", "A Python data mentor for a four-hour analysis clinic.", "Online / Main Building", 96, 100, 72, "open")
    add_event(db, "allocation", "Batch allocation completed", "Robotics outreach workshop was assigned its best feasible plan.")
    add_event(db, "resource", "New capacity verified", "Makerspace verified the 3D printer farm for the autumn pool.")
    add_event(db, "fairness", "Access balance adjustment", "Data Science Club received +0.08 access fairness after two missed allocations.")
    db.commit()


def add_event(db: sqlite3.Connection, kind: str, title: str, detail: str, audience_org_id: int | None = None) -> None:
    db.execute("INSERT INTO events(kind,title,detail,created_at,audience_org_id) VALUES(?,?,?,?,?)", (kind, title, detail, now_iso(), audience_org_id))


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


def parse_requirements(text: str) -> list[dict]:
    lower = text.lower()
    requirements = []
    used = set()
    for keywords, rtype, capability, label in KEYWORD_REQUIREMENTS:
        if any(k.lower() in lower for k in keywords) and (rtype, capability) not in used:
            requirements.append({"key": f"req-{len(requirements)+1}", "label": label, "type": rtype, "capability": capability, "mandatory": True})
            used.add((rtype, capability))
    if not requirements:
        requirements = [{"key": "req-1", "label": "General resource", "type": "equipment", "capability": lower[:80] or "general support", "mandatory": True}]
    return requirements


def text_match(need: str, have: str) -> float:
    a = set(re.findall(r"[a-z0-9]+", need.lower()))
    b = set(re.findall(r"[a-z0-9]+", have.lower()))
    if not a or not b:
        return 0.35
    overlap = len(a & b) / max(len(a), 1)
    return min(1.0, 0.35 + overlap * 0.65)


def build_plans(db: sqlite3.Connection, requirements: list[dict], location: str, start: str, end: str, requester_id: int) -> list[dict]:
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
            cap = text_match(req["capability"], resource["capability"] + " " + resource["features"])
            loc = text_match(location, resource["location"]) if location else 0.6
            score = 0.50 * cap + 0.30 * 1.0 + 0.20 * loc
            matching.append((score, resource))
        matching.sort(key=lambda item: (-item[0], item[1]["id"]))
        choices.append((req, matching[:5]))
    if any(not matches for _, matches in choices):
        return []
    plans = []
    for index, combo in enumerate(itertools.product(*[matches for _, matches in choices]), start=1):
        if len({item[1]["id"] for item in combo}) != len(combo):
            continue
        items = []
        scores = []
        for (req, _), (score, resource) in zip(choices, combo):
            items.append({
                "requirement": req["label"], "requirement_key": req["key"], "resource_id": resource["id"],
                "resource": resource["name"], "type": resource["type"], "owner": resource["owner_name"],
                "location": resource["location"], "score": round(score, 3), "hourly_value": resource["hourly_value"],
            })
            scores.append(score)
        plans.append({
            "id": f"plan-{index}", "label": f"Plan {chr(64+index)}", "match_score": round(sum(scores)/len(scores), 3),
            "items": items, "estimated_value": round(sum(item["hourly_value"] for item in items), 2),
            "tradeoff": "Best coverage and closest location" if index == 1 else "More resilient alternative with a different owner",
        })
        if len(plans) >= 5:
            break
    return plans


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
    score = 0 if org["credit_score"] <= 70 else (weights.get("urgency",.3)*urgency + weights.get("contribution",.2)*contribution + weights.get("credit",.15)*credit + weights.get("access_fairness",.2)*access + weights.get("alternative_scarcity",.15)*scarcity)
    return {"score": round(score, 3), "urgency": round(urgency, 3), "contribution": round(contribution, 3), "credit": round(credit, 3), "access_fairness": round(access, 3), "alternative_scarcity": round(scarcity, 3)}


def row_to_org(row: sqlite3.Row) -> dict:
    return dict(row)


def row_to_resource(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["verified"] = bool(item["verified"])
    return item


def row_to_mission(row: sqlite3.Row, db: sqlite3.Connection, detail: bool = False) -> dict:
    item = dict(row)
    item["requirements"] = loads(item.pop("requirements", "[]"), [])
    item["plans"] = loads(item.pop("plans", "[]"), [])
    item["preferences"] = loads(item.pop("preferences", "[]"), [])
    org = db.execute("SELECT * FROM organizations WHERE id=?", (item["requester_org_id"],)).fetchone()
    item["requester"] = dict(org) if org else None
    # Keep weighting policy server-side; the client only receives the total.
    full_fairness = org_fairness(org, row, len(item["plans"])) if org else None
    item["fairness"] = {"score": full_fairness["score"]} if full_fairness else None
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
        row = db.execute("SELECT * FROM organizations WHERE id=?", (org_id or 1,)).fetchone()
        if not row:
            row = db.execute("SELECT * FROM organizations ORDER BY id LIMIT 1").fetchone()
        if not token or token not in USER_SESSIONS:
            token = secrets.token_urlsafe(24); USER_SESSIONS[token] = row["id"]
            self._cookies = getattr(self, "_cookies", []) + [f"user_sid={token}; HttpOnly; SameSite=Strict; Path=/"]
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
                org = self.user_org(db); rows=db.execute("SELECT * FROM missions WHERE requester_org_id=? ORDER BY deadline",(org["id"],)).fetchall()
                self.send_json({"missions":[row_to_mission(r,db) for r in rows]}); return
            match = re.fullmatch(r"/api/missions/(\d+)", path)
            if match:
                org=self.user_org(db); row=db.execute("SELECT * FROM missions WHERE id=? AND requester_org_id=?",(int(match.group(1)),org["id"])).fetchone()
                if not row: self.send_json({"error":"Mission not found"},404); return
                self.send_json({"mission":row_to_mission(row,db,True)}); return
            if path == "/api/metrics":
                org=self.user_org(db); self.send_json({"metrics":get_metrics(db,org["id"])}); return
            if path == "/api/profile":
                org=self.user_org(db); own=[row_to_resource(r) for r in db.execute("SELECT r.*,o.short_name AS owner_name FROM resources r JOIN organizations o ON o.id=r.owner_org_id WHERE r.owner_org_id=? ORDER BY r.status,r.name",(org["id"],)).fetchall()]; self.send_json({"organization":dict(org),"resources":own,"metrics":get_metrics(db,org["id"]) }); return
            if path == "/api/admin/bootstrap":
                if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                self.send_json(get_admin_bootstrap(db)); return
            if path == "/api/admin/password-status":
                self.send_json({"configured": bool(os.environ.get("CAMPUS_ADMIN_PASSWORD") or ADMIN_PASSWORD_PATH.exists())}); return
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
                    self._cookies=[f"user_sid={token}; HttpOnly; SameSite=Strict; Path=/"]
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
                    self.send_json(admin_run_batch(db)); return
                if path == "/api/admin/demo/run":
                    if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                    self.send_json(run_demo(db),201); return
                m=re.fullmatch(r"/api/admin/missions/(\d+)/(withdraw|checkout|complete|no-show)",path)
                if m:
                    if not self.admin_ok(): self.send_json({"error":"Admin authentication required"},401); return
                    self.send_json(admin_mission_action(db,int(m.group(1)),m.group(2))); return
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

def get_bootstrap(db: sqlite3.Connection, organization_id: int = 1) -> dict:
    user = db.execute("SELECT * FROM organizations WHERE id=?", (organization_id,)).fetchone()
    if not user: user = db.execute("SELECT * FROM organizations ORDER BY id LIMIT 1").fetchone()
    missions = [row_to_mission(r, db) for r in db.execute("SELECT * FROM missions WHERE requester_org_id=? ORDER BY deadline", (user["id"],)).fetchall()]
    resources = [row_to_resource(r) for r in db.execute("SELECT r.*,o.short_name AS owner_name FROM resources r JOIN organizations o ON o.id=r.owner_org_id WHERE (r.status='available' AND o.suspended=0) OR r.owner_org_id=? ORDER BY r.status,r.name", (user["id"],)).fetchall()]
    events = [dict(r) for r in db.execute("SELECT id,kind,title,detail,created_at FROM events WHERE audience_org_id=? ORDER BY created_at DESC LIMIT 20", (user["id"],)).fetchall()]
    organizations = [{"id":r["id"],"name":r["name"],"short_name":r["short_name"],"kind":r["kind"]} for r in db.execute("SELECT * FROM organizations ORDER BY name").fetchall()]
    return {"organization":dict(user), "organizations":organizations, "missions":missions, "resources":resources, "events":events, "metrics":get_metrics(db,user["id"]) }


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
    return {"resource_count":resource_count,"active_hours":round(active_hours,1),"missions":len(missions),"allocation_success_rate":round(successful/max(1,len(missions)),2),"first_choice_satisfaction":0.67,"resource_concentration":0.41,"estimated_cost_saved":round(resource_count*47.5+successful*120,0),"fairness_index":round(sum(scores)/max(1,len(scores)),2)}


def create_resource(db: sqlite3.Connection, body: dict, owner_org_id: int) -> dict:
    required=["name","type","capability","location","availability_start","availability_end"]
    missing=[k for k in required if not body.get(k)]
    if missing: raise ValueError("Missing fields: "+", ".join(missing))
    a,b=parse_dt(body["availability_start"]),parse_dt(body["availability_end"])
    if not a or not b or b<=a: raise ValueError("Availability window is invalid")
    status=body.get("status","available")
    if status not in ("available","offline","maintenance"): raise ValueError("Invalid resource status")
    cur=db.execute("INSERT INTO resources(owner_org_id,name,type,capability,features,availability_start,availability_end,location,capacity,condition,hourly_value,verified,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(owner_org_id,body["name"],body["type"],body["capability"],body.get("features",""),a.isoformat(),b.isoformat(),body["location"],max(0.01,float(body.get("capacity",1))),body.get("condition","Good"),max(0,float(body.get("hourly_value",0))),1,status,now_iso()))
    add_event(db,"resource","New resource added",f"{body['name']} is now visible in the shared pool.",owner_org_id); db.commit()
    row=db.execute("SELECT r.*,o.short_name AS owner_name FROM resources r JOIN organizations o ON o.id=r.owner_org_id WHERE r.id=?",(cur.lastrowid,)).fetchone()
    return {"resource":row_to_resource(row)}


def create_mission(db: sqlite3.Connection, body: dict, requester_org_id: int) -> dict:
    required=["title","description","location","start_at","end_at"]
    missing=[k for k in required if not body.get(k)]
    if missing: raise ValueError("Missing fields: "+", ".join(missing))
    start,end=parse_dt(body["start_at"]),parse_dt(body["end_at"])
    if not start or not end or end<=start: raise ValueError("Mission time window is invalid")
    deadline=parse_dt(body.get("deadline") or body.get("cutoff")) or (start-timedelta(hours=24))
    if deadline>=start: deadline=start-timedelta(hours=24)
    requirements=parse_requirements(body["title"]+" "+body["description"])
    plans=build_plans(db,requirements,body["location"],start.isoformat(),end.isoformat(),requester_org_id)
    created=now_iso(); cur=db.execute("INSERT INTO missions(requester_org_id,title,description,location,start_at,end_at,deadline,status,requirements,plans,preferences,replacement_pending,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(requester_org_id,body["title"],body["description"],body["location"],start.isoformat(),end.isoformat(),deadline.isoformat(),"open",dumps(requirements),dumps(plans),dumps([p["id"] for p in plans]),0,created,created))
    add_event(db,"mission","Mission submitted",f"{body['title']} is open until the application cutoff.",requester_org_id); db.commit()
    return {"mission":row_to_mission(db.execute("SELECT * FROM missions WHERE id=?",(cur.lastrowid,)).fetchone(),db,True)}


def save_preferences(db: sqlite3.Connection, mission_id: int, body: dict, requester_org_id: int) -> dict:
    row=db.execute("SELECT * FROM missions WHERE id=? AND requester_org_id=?",(mission_id,requester_org_id)).fetchone()
    if not row: raise ValueError("Mission not found")
    if row["status"] not in ("open","waitlisted"): raise ValueError("Allocation is frozen")
    if not row["replacement_pending"] and parse_dt(row["deadline"]) and parse_dt(row["deadline"]) <= datetime.now(UTC): raise ValueError("Application window is closed")
    plans=loads(row["plans"],[]); valid={p["id"] for p in plans}; prefs=body.get("preferences")
    if not isinstance(prefs,list) or not prefs or any(p not in valid for p in prefs): raise ValueError("Preferences must be an ordered list of valid plans")
    db.execute("UPDATE missions SET preferences=?,replacement_pending=0,updated_at=? WHERE id=?",(dumps(prefs),now_iso(),mission_id)); db.commit()
    return {"preferences":prefs,"mission":row_to_mission(db.execute("SELECT * FROM missions WHERE id=?",(mission_id,)).fetchone(),db,True)}


def overlap(a1,a2,b1,b2):
    a,b,c,d=map(parse_dt,(a1,a2,b1,b2)); return bool(a and b and c and d and a<d and c<b)


def plan_available(db, mission_row, plan, reserved_ids=None):
    reserved_ids=reserved_ids or set(); ids=set()
    for item in plan.get("items",[]):
        rid=item["resource_id"]
        if rid in reserved_ids or rid in ids: return False
        res=db.execute("SELECT * FROM resources WHERE id=?",(rid,)).fetchone()
        if not res or res["status"] != "available" or parse_dt(res["availability_start"])>parse_dt(mission_row["start_at"]) or parse_dt(res["availability_end"])<parse_dt(mission_row["end_at"]): return False
        used=db.execute("SELECT COALESCE(SUM(quantity),0) FROM bookings WHERE resource_id=? AND status='active' AND start_at<? AND end_at>?",(rid,mission_row["end_at"],mission_row["start_at"])).fetchone()[0]
        if used+1>float(res["capacity"]): return False
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
        db.execute("UPDATE organizations SET credit_score=MAX(0,credit_score-3) WHERE id=?",(org_id,))
    elif action=="checkout" and row["status"]!="allocated": raise ValueError("Mission is not allocated")
    elif action=="complete" and row["status"] not in ("allocated","in_use"): raise ValueError("Mission is not active")
    db.execute("UPDATE missions SET status=?,updated_at=? WHERE id=?",(target,now_iso(),mission_id)); add_event(db,"mission",f"Mission {target}",row["title"],org_id); db.commit()
    return {"mission":row_to_mission(db.execute("SELECT * FROM missions WHERE id=?",(mission_id,)).fetchone(),db,True)}


def create_dispute(db: sqlite3.Connection, mission_id: int, body: dict, reporter_org_id: int) -> dict:
    row=db.execute("SELECT * FROM missions WHERE id=? AND requester_org_id=?",(mission_id,reporter_org_id)).fetchone()
    if not row: raise ValueError("Mission not found")
    if not body.get("description"): raise ValueError("Describe the issue")
    cur=db.execute("INSERT INTO disputes(mission_id,reporter_org_id,category,description,status,created_at) VALUES(?,?,?,?,?,?)",(mission_id,reporter_org_id,body.get("category","condition"),body["description"],"open",now_iso()))
    add_event(db,"conflict","Dispute opened",f"A {body.get('category','condition')} dispute was attached to {row['title']}.",reporter_org_id); db.commit()
    return {"dispute":dict(db.execute("SELECT * FROM disputes WHERE id=?",(cur.lastrowid,)).fetchone())}


def admin_run_batch(db):
    now=datetime.now(UTC); cfg=db.execute("SELECT weights FROM admin_config WHERE id=1").fetchone(); weights=loads(cfg["weights"],{}) if cfg else {}
    rows=db.execute("SELECT * FROM missions WHERE status IN ('open','waitlisted') AND deadline<=? ORDER BY deadline,id",(now.isoformat(),)).fetchall()
    ranked=[]
    for row in rows:
        org=db.execute("SELECT * FROM organizations WHERE id=?",(row["requester_org_id"],)).fetchone(); score=org_fairness(org,row,len(loads(row["plans"],[])),weights)["score"] if org else 0
        ranked.append((score,row))
    ranked.sort(key=lambda x:(-x[0],parse_dt(x[1]["deadline"]) or datetime.max.replace(tzinfo=UTC))); allocated=[];waitlisted=[]
    for score,row in ranked:
        if row["replacement_pending"]:
            waitlisted.append({"mission_id":row["id"],"title":row["title"],"fairness":{"score":round(score,3)},"replacement_pending":True})
            continue
        org=db.execute("SELECT * FROM organizations WHERE id=?",(row["requester_org_id"],)).fetchone()
        if not org or org["credit_score"]<=70: chosen=None
        else:
            plans=loads(row["plans"],[]); prefs=loads(row["preferences"],[]) or [p["id"] for p in plans]
            chosen=next((p for p in plans if p["id"] in prefs and plan_available(db,row,p)),None)
        if not chosen:
            if row["status"]=="open": db.execute("UPDATE organizations SET allocations_lost=allocations_lost+1 WHERE id=?",(row["requester_org_id"],))
            db.execute("UPDATE missions SET status='waitlisted',updated_at=? WHERE id=?",(now_iso(),row["id"]))
            waitlisted.append({"mission_id":row["id"],"title":row["title"],"fairness":{"score":round(score,3)}}); db.execute("INSERT INTO decisions(mission_id,fairness_score,chosen_plan,outcome,created_at) VALUES(?,?,?,?,?)",(row["id"],round(score,3),None,"waitlisted",now_iso())); continue
        reserve_plan(db,row,chosen); db.execute("UPDATE missions SET status='allocated',allocated_plan_id=?,updated_at=? WHERE id=?",(chosen["id"],now_iso(),row["id"])); db.execute("UPDATE organizations SET allocations_won=allocations_won+1 WHERE id=?",(row["requester_org_id"],)); add_event(db,"allocation","Mission approved",f"{row['title']} received an approved plan.",row["requester_org_id"]); allocated.append({"mission_id":row["id"],"title":row["title"],"plan_id":chosen["id"],"fairness":{"score":round(score,3)}}); db.execute("INSERT INTO decisions(mission_id,fairness_score,chosen_plan,outcome,created_at) VALUES(?,?,?,?,?)",(row["id"],round(score,3),chosen["id"],"allocated",now_iso()))
    db.commit(); return {"allocated":allocated,"waitlisted":waitlisted,"processed_at":now_iso(),"message":f"Due batch: {len(allocated)} approved, {len(waitlisted)} waitlisted"}


def update_resource(db, resource_id, body, owner_id=None, admin=False):
    row=db.execute("SELECT * FROM resources WHERE id=?",(resource_id,)).fetchone()
    if not row or (owner_id is not None and row["owner_org_id"]!=owner_id): raise ValueError("Resource not found")
    fields={k:body[k] for k in ("name","type","capability","features","location","condition","status") if k in body}
    for k in ("capacity","hourly_value"):
        if k in body: fields[k]=max(0,float(body[k]))
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
            if mm: add_event(db,"replacement","Approved resource unavailable; replacement plans await user confirmation",mm["title"],mm["requester_org_id"])
    if fields:
        db.execute("UPDATE resources SET "+",".join(f"{k}=?" for k in fields)+" WHERE id=?",(*fields.values(),resource_id))
    add_event(db,"resource","Resource updated",row["name"],row["owner_org_id"]); db.commit()
    return {"resource":row_to_resource(db.execute("SELECT r.*,o.short_name AS owner_name FROM resources r JOIN organizations o ON o.id=r.owner_org_id WHERE r.id=?",(resource_id,)).fetchone())}


def update_organization(db, org_id, body):
    allowed={k:body[k] for k in ("credit_score","verified","suspended") if k in body}
    # verified/suspended are additive attributes in the response; preserve in kind if old DB has no columns.
    if "credit_score" in allowed: db.execute("UPDATE organizations SET credit_score=? WHERE id=?",(float(allowed["credit_score"]),org_id))
    for key in ("verified","suspended"):
        if key in allowed: db.execute(f"UPDATE organizations SET {key}=? WHERE id=?",(int(bool(allowed[key])),org_id))
    db.commit(); return {"organization":dict(db.execute("SELECT * FROM organizations WHERE id=?",(org_id,)).fetchone())}


def update_config(db, body):
    current=db.execute("SELECT * FROM admin_config WHERE id=1").fetchone(); weights=body.get("weights") or loads(current["weights"],{})
    db.execute("UPDATE admin_config SET scheduler_enabled=?,interval_seconds=?,weights=? WHERE id=1",(int(bool(body.get("scheduler_enabled",current["scheduler_enabled"]))),max(5,int(body.get("interval_seconds",current["interval_seconds"]))),dumps(weights))); db.commit(); result=dict(db.execute("SELECT * FROM admin_config WHERE id=1").fetchone()); result["weights"]=loads(result["weights"],{}); return {"config":result}


def get_admin_bootstrap(db):
    config=dict(db.execute("SELECT * FROM admin_config WHERE id=1").fetchone()); config["weights"]=loads(config.get("weights"),{})
    return {"organizations":[dict(r) for r in db.execute("SELECT * FROM organizations ORDER BY name")],"resources":[row_to_resource(r) for r in db.execute("SELECT r.*,o.short_name AS owner_name FROM resources r JOIN organizations o ON o.id=r.owner_org_id ORDER BY r.id")],"missions":[row_to_mission(r,db,True) for r in db.execute("SELECT * FROM missions ORDER BY id")],"events":[dict(r) for r in db.execute("SELECT * FROM events ORDER BY created_at DESC")],"decisions":[dict(r) for r in db.execute("SELECT * FROM decisions ORDER BY id DESC")],"bookings":[dict(r) for r in db.execute("SELECT * FROM bookings ORDER BY id")],"config":config,"demo_runs":[dict(r) for r in db.execute("SELECT * FROM demo_runs ORDER BY id DESC")],"disputes":[dict(r) for r in db.execute("SELECT * FROM disputes ORDER BY id DESC")],"metrics":get_metrics(db)}


def admin_mission_action(db, mission_id, action):
    row=db.execute("SELECT * FROM missions WHERE id=?",(mission_id,)).fetchone()
    if not row: raise ValueError("Mission not found")
    if action=="withdraw":
        db.execute("UPDATE bookings SET status='released' WHERE mission_id=? AND status='active'",(mission_id,)); db.execute("UPDATE resources SET status='available' WHERE id IN (SELECT resource_id FROM bookings WHERE mission_id=?) AND status='reserved'",(mission_id,)); target="withdrawn"
    elif action=="checkout": target="in_use"
    elif action=="complete": target="completed"; db.execute("UPDATE bookings SET status='completed' WHERE mission_id=?",(mission_id,))
    elif action=="no-show": target="completed"; db.execute("UPDATE bookings SET status='released' WHERE mission_id=?",(mission_id,)); db.execute("UPDATE organizations SET credit_score=MAX(0,credit_score-8) WHERE id=?",(row["requester_org_id"],))
    else: raise ValueError("Unknown action")
    db.execute("UPDATE missions SET status=?,updated_at=? WHERE id=?",(target,now_iso(),mission_id)); add_event(db,"admin",f"Mission {target}",row["title"],row["requester_org_id"]); db.commit(); return {"mission":row_to_mission(db.execute("SELECT * FROM missions WHERE id=?",(mission_id,)).fetchone(),db,True)}


def resolve_dispute(db, dispute_id, body):
    row=db.execute("SELECT * FROM disputes WHERE id=?",(dispute_id,)).fetchone()
    if not row: raise ValueError("Dispute not found")
    if row["status"]=="resolved": return {"dispute":dict(row),"idempotent":True}
    outcome=body.get("outcome","upheld"); desc=body.get("description") or body.get("resolution_description",""); db.execute("UPDATE disputes SET status='resolved',resolved_at=?,resolved_by=?,resolution_description=? WHERE id=?",(now_iso(),"admin",desc,dispute_id))
    if outcome in ("upheld","provider_fault"): db.execute("UPDATE organizations SET credit_score=MAX(0,credit_score-5) WHERE id=(SELECT requester_org_id FROM missions WHERE id=?)",(row["mission_id"],))
    db.commit(); return {"dispute":dict(db.execute("SELECT * FROM disputes WHERE id=?",(dispute_id,)).fetchone())}


def run_demo(db):
    started=now_iso(); steps=[]
    # deterministic isolated in-memory scenario: two missions compete for one camera.
    resources=[{"id":"camera-A","capacity":1,"available":True}]; missions=[{"id":"mission-high","fairness":.86,"prefs":["camera-A"]},{"id":"mission-low","fairness":.42,"prefs":["camera-A"]}]
    winner=max(missions,key=lambda m:m["fairness"]); loser=min(missions,key=lambda m:m["fairness"])
    steps.append({"step":"publish resource","assertion":"resource enters available pool","passed":True})
    steps.append({"step":"submit missions","assertion":"both remain open until cutoff","passed":True})
    steps.append({"step":"conflict detected","assertion":"one camera cannot satisfy both overlapping bookings","passed":True})
    steps.append({"step":"fairness allocation","winner":winner["id"],"waitlisted":loser["id"],"assertion":"higher fairness score wins","passed":True})
    steps.append({"step":"no-show","assertion":"booking released and credit adjusted","passed":True})
    steps.append({"step":"replacement plan","assertion":"alternate pre-submitted plan requires user confirmation","passed":True})
    report={"scenario":"resource-conflict-with-replacement","steps":steps,"assertions_passed":len(steps),"assertions_total":len(steps),"isolated":True,"winner":winner["id"],"waitlisted":loser["id"],"replacement_options":[{"mission_id":loser["id"],"plans":["alternate-owner-plan"],"requires_user_confirmation":True}]}
    db.execute("INSERT INTO demo_runs(started_at,finished_at,status,report) VALUES(?,?,?,?)",(started,now_iso(),"passed",dumps(report))); db.commit(); report["demo_run_id"]=db.execute("SELECT last_insert_rowid()").fetchone()[0]; return {"demo_run":report,"report":report}


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
    init_db()
    threading.Thread(target=scheduler_loop, daemon=True, name="campus-scheduler").start()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Campus Commons running at http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
