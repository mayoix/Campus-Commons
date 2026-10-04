# Campus Commons

Campus Commons is a web-based campus resource sharing platform that enables organizations to efficiently share equipment, spaces, skills, and people resources through a fair and explainable allocation system.

Instead of each organization independently owning under-utilized resources, Campus Commons creates a shared campus resource pool where organizations can contribute available resources, submit requests, and receive transparent allocation decisions.

---

# Live Demo

The deployed web application:

```
https://your-render-url.onrender.com
```

Campus Commons provides a complete browser-based experience:

- Browse available campus resources
- Publish and manage resources
- Submit Missions
- Select preferred resource plans
- Receive allocation results
- Track contribution and credit history
- Submit disputes with evidence
- Access administrator management tools

---

# System Architecture

Campus Commons is deployed as a full-stack web application.

```
                    User Browser
                         |
                         |
                         v
                Render Web Service
                (Python Backend)
                         |
          +--------------+--------------+
          |                             |
          v                             v
 Supabase PostgreSQL            Supabase Storage
 (Application Data)              (Evidence Files)
```

## Components

### Frontend

Browser-based user interface supporting:

- Resource discovery
- Mission submission
- Organization profiles
- Allocation results
- Dispute submission
- Administrator console

### Backend

Python-based backend responsible for:

- Resource management
- Mission processing
- Fair allocation
- Booking management
- Credit and contribution tracking
- Dispute handling

### Database

Supabase PostgreSQL stores:

- Organizations
- Resources
- Missions
- Bookings
- Allocation decisions
- Credit events
- Contribution events
- History records

### Storage

Supabase Storage stores:

- Dispute evidence files
- Supporting documents

---

# Core Features

## 1. Resource Sharing

Organizations can contribute resources into a shared campus pool.

Supported resource types:

- Equipment
- Spaces
- Skills
- People resources

Each resource contains:

- Resource type
- Capability description
- Availability window
- Location
- Capacity
- External replacement cost
- Verification status

The platform allows organizations to expose unused capacity and improve resource utilization.

---

# 2. Mission-Based Resource Request

Users create Missions when their organization needs shared resources.

A Mission contains:

- Required resource type
- Capability requirements
- Location
- Usage interval
- Preferred resource options

The system automatically generates feasible resource plans based on:

- Capability matching
- Availability constraints
- Capacity constraints
- Location compatibility

Users can review and reorder acceptable plans before allocation.

---

# 3. Fair Allocation System

When the application window closes, administrators run the allocation batch.

The allocation pipeline:

```
Mission Requests
        |
        v
Feasibility Checking
        |
        v
Conflict Detection
        |
        v
Fairness Ranking
        |
        v
Allocation / Waitlist
```

The system considers:

- Resource availability
- Capacity conflicts
- Capability matching
- User preferences

---

## Fairness Model

The allocation score combines:

- Urgency
- Contribution
- Credit score
- Access fairness
- Alternative scarcity


Example:

```
Fairness Score =

w1 * Urgency
+
w2 * Contribution
+
w3 * Credit
+
w4 * Access Fairness
+
w5 * Alternative Scarcity
```

The final decision stores an explanation snapshot to make allocation decisions transparent and auditable.

---

# 4. Contribution and Credit System

Campus Commons separates two concepts:

## Contribution

Measures how much an organization contributes resources to the ecosystem.

Examples:

- Verified availability
- Actual resource sharing
- Completed collaborations


## Credit

Measures organization reliability.

Credit changes based on:

Positive events:

- Successful sharing
- Reliable collaboration

Negative events:

- Provider no-show
- Dispute penalties
- Unfulfilled commitments


Contribution and credit are independently tracked and used for different purposes.

---

# 5. Organization Profile

Each organization has a profile containing:

- Owned resources
- Contribution history
- Credit score
- Allocation history
- Resource usage records

Organizations can manage:

- Resource details
- Availability
- Resource status

---

# 6. Dispute Management

Users can report problems related to resource sharing.

Supported features:

- Dispute submission
- Evidence upload
- Compensation requests
- Administrator review
- Credit adjustment


Evidence files are securely stored in Supabase Storage.

---

# 7. Administrator Console

The administrator console provides platform management.

Administrators can:

- Manage resources
- Manage organizations
- Run allocation batches
- Configure fairness weights
- Review disputes
- Adjust credit events
- Inspect decision history
- Run explainable demonstrations

The administrator interface is protected through authentication.

---

# Deployment

Campus Commons is deployed using Render.

## Deployment Architecture

```
GitHub Repository
        |
        v
Render Web Service
        |
        v
Supabase PostgreSQL
        |
        v
Supabase Storage
```

---

## Render Configuration

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
python render_start.py
```

---

## Environment Variables

The deployment requires:

```dotenv
SUPABASE_URL=your_supabase_project_url

SUPABASE_SECRET_KEY=your_service_role_key

SUPABASE_DATABASE_URL=your_postgresql_connection_string

SUPABASE_EVIDENCE_BUCKET=campus-evidence

CAMPUS_DB_BACKEND=supabase

CAMPUS_ADMIN_PASSWORD=your_admin_password
```

---

# Local Development

For development purposes, Campus Commons can also run locally.

## Requirements

- Python 3.10+
- Git


## Installation

```bash
git clone https://github.com/mayoix/campus-commons.git

cd campus-commons

pip install -r requirements.txt
```


Configure environment variables:

```bash
cp .env.example .env
```


Start the server:

```bash
python server.py
```


Open:

```
http://127.0.0.1:8765
```

---

# Database Modes

Campus Commons supports two modes.

## Cloud Mode

Default deployment mode:

- Supabase PostgreSQL
- Supabase Storage

All users share the same database state.

Recommended for:

- Hosted deployment
- Team collaboration
- Hackathon demonstration


## Local Demo Mode

SQLite mode is available for offline demonstrations.

Local mode:

- Does not share data between machines
- Does not require Supabase

---

# User Workflow

## Resource Provider

1. Publish a resource
2. Define capability and availability
3. Wait for Mission requests
4. Complete sharing
5. Earn contribution records


---

## Resource Requester

1. Browse resources
2. Submit a Mission
3. Select preferred options
4. Wait for allocation
5. Use approved resources
6. Submit feedback or disputes if needed


---

## Administrator

1. Monitor platform activity
2. Run allocation batches
3. Review fairness decisions
4. Manage disputes
5. Maintain platform policies

---

# Explainable Demo Scenarios

The administrator console provides deterministic demonstrations.

---

## Conflict and Fairness

Scenario:

Two Missions compete for one resource.

Demonstrates:

- Conflict detection
- Fair ranking
- Allocation decision


---

## Withdrawal and Release

Scenario:

A Mission withdraws before allocation.

Demonstrates:

- Request cancellation
- Resource release
- Updated allocation state


---

## Provider No-show and Replacement

Scenario:

A provider fails to deliver a resource.

Demonstrates:

- Credit penalty
- Replacement generation
- User confirmation workflow


---

## Preference-Based Allocation

Scenario:

The first preferred option becomes unavailable.

Demonstrates:

- Feasibility checking
- Preference ordering
- Alternative selection


---

# API Overview

## User APIs

```
GET  /api/bootstrap

GET  /api/resources

POST /api/resources

PATCH /api/resources/:id

GET  /api/missions

POST /api/missions

POST /api/missions/:id/preferences

POST /api/missions/:id/checkout

POST /api/missions/:id/complete

POST /api/missions/:id/withdraw

POST /api/missions/:id/disputes
```


---

## Administrator APIs

```
POST  /api/admin/login

GET   /api/admin/bootstrap

POST  /api/admin/allocation/run

POST  /api/admin/demo/run

PATCH /api/admin/config
```

---

# Repository Structure

```
campus-commons/

├── server.py
├── render_start.py
├── render.yaml
├── requirements.txt
│
├── static/
│   ├── index.html
│   ├── app.js
│   └── styles.css
│
└── scripts/
    └── Database utilities
```

---

# Security Notes

- Environment variables are never committed to GitHub.
- Supabase credentials remain on the backend.
- Evidence files are stored in a private bucket.
- Administrator access requires authentication.
- Local sessions are used only for hackathon simulation.

---

# Implementation Decisions

- PostgreSQL is the single source of truth in cloud deployment.
- Bookings represent resource capacity reservations.
- Fairness decisions are stored with explanation snapshots.
- Contribution and credit are modeled separately.
- The current implementation focuses on campus-scale sharing rather than production identity management.

---

# Future Improvements

Potential extensions:

- Real campus identity authentication
- Automated scheduling optimization
- Mobile application
- Geographic campus map integration
- Machine learning based demand prediction
- Larger-scale multi-campus deployment

---

# License

This project is developed as a hackathon MVP.

## Hosted performance fix (based on fdfb903)

Render and local cloud startup now use the same pooled adapter, including SQLite-compatible row indexing. This fixes `KeyError: 0` when reading PostgreSQL aggregate counts. `requirements-cloud.txt` installs the pool dependency for double-click startup too.

User and admin background sync first call `/api/version` (one database query), and only reload the full snapshot when persistent data changes. Hidden tabs pause polling; user polling also pauses while the admin overlay is open. Cloud GET requests use independent pooled transactions instead of waiting on the allocation/write lock. Established sessions no longer write `last_seen` on every read; sessions currently have no inactivity expiry policy.

Resource loans, Mission booking details, organization lookups and fairness metrics are read in batches. Hosted startup applies `scripts/performance_indexes.sql` automatically. Admin snapshots retain the latest 10 demo reports and 200 events; business records are retained in the database. Slow API calls log their path and elapsed time, with no payloads or credentials; unexpected API failures return a safe JSON error instead of dropping the request.

Validation: 21 offline regression tests pass, including pooled commit/rollback, aggregate row compatibility and serializer equivalence. A query-count test keeps user bootstrap at 20 queries before and after adding 40 resources and 40 Missions. This is a query-count result, not a measured production latency guarantee.

After pushing this change, deploy the new commit on Render using `pip install -r requirements.txt` and `python render_start.py`. If automatic deployment is enabled, Render will pick up the main-branch commit. Reload the browser after deployment. No database reset or manual migration is required. Production response times still depend on Render instance resources and the network distance to Supabase.
