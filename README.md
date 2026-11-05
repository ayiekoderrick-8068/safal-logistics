# LogiTrack — Logistics Operations Portal

LogiTrack is a logistics management platform for fleet, loading-bay scheduling, dispatch,
turnaround-time analytics and vehicle compliance. It was built as a portfolio project inspired
by the Graduate Logistics Systems Analyst role at Safal.

> **Status: Milestones 1–3 complete** (operations dashboard, the truck-to-delivery workflow,
> compliance management, delay incidents, operational alerts, turnaround analytics). See
> [Project status](#project-status) for exactly what works, what is sample data, and what remains.

## Tech stack

| Layer    | Technology |
|----------|------------|
| Frontend | React 19, TypeScript, Tailwind CSS 4, React Router, Recharts, React Hook Form + Zod, Vite |
| Backend  | Python 3.14, FastAPI, SQLAlchemy 2, Alembic, PyJWT, bcrypt |
| Database | PostgreSQL 17 (Docker Compose for local development) |
| Testing  | Pytest (against a real PostgreSQL test database), Vitest + Testing Library, Playwright |

## Architecture

```
frontend/  React SPA. Vite proxies /api -> backend so the session cookie is same-origin.
backend/   FastAPI app
  app/models.py        relational schema
  app/routers/         auth, system, dashboard, fleet, loading, dispatch, compliance,
                       incidents, alerts, analytics
  app/services/        dashboard metrics, turnaround, operations workflow, compliance
                       rules, alert engine, file storage, app settings
  app/sample_data.py   clearly-labelled demonstration dataset
  app/cli.py           create-admin / load-sample / clear-sample / refresh-alerts / reset-e2e
  alembic/             migrations (the source of truth for the schema)
docker-compose.yml     local PostgreSQL (dev + test databases)
```

### Data model

`users`, `drivers`, `trucks`, `routes`, `loading_bays`, `loading_schedules`, `dispatches`,
`delay_incidents`, `compliance_documents`, `compliance_requirements`, `alerts`,
`audit_events`, `app_settings`.

Migrations: `c9ec15ec26f6` (initial schema) and `4cdcd62eb0a9` (compliance history, file
metadata and requirements; delay assignment and resolution; alerts). The second migration
keeps existing records: it marks older duplicate documents as history and fixes incident
status and resolution times before adding the new constraints. It has been verified with a
downgrade → upgrade round trip.

Business rules are enforced **in the database** as well as in the API:

- **No double-booked bays.** A PostgreSQL exclusion constraint (`btree_gist`) rejects
  overlapping bookings on the same bay; cancelled bookings don't block.
- **Ordered timestamps.** Loading can't start before arrival, can't finish before it starts,
  and the truck can't depart before loading finishes.
- **Data integrity.** Positive capacities, distances and durations. Unique truck registrations
  and load references. At most one truck per driver.
- **Complete deliveries.** A delivered dispatch must have an actual arrival time.
- **Traceable delays.** Each delay incident must be linked to a dispatch or a loading schedule.
  A resolved incident must have a resolution time, and it can't be earlier than the start.
- **One current document per truck and type.** Renewals add a new row, so the history is
  never overwritten.
- **One unresolved alert per condition.** A partial unique index on the alert key prevents
  duplicates.

### Metric definitions

| Metric | Definition |
|--------|------------|
| Turnaround time | `departed_at − arrival_at` of a loading schedule (truck arrival → departure) |
| Within target | Turnaround ≤ the bay's target, or the global target (default 120 min) |
| Loads processed | Loading schedules that departed in the period (excluding cancelled ones) |
| On-time delivery | Delivered dispatches arriving in the period with actual arrival ≤ expected arrival + grace (default 15 min) |
| Delay duration | `resolved_at − occurred_at` (or now − start while still open), from stored timestamps |
| Document status | expired if past its expiry date; expiring if within the type's reminder window (default 30 days); otherwise valid; missing if mandatory and absent |
| Bay utilisation | Occupied bay time ÷ (active bays × days × operating hours per day, default 12) |

Every figure is calculated by SQL over recorded rows. When there is no data, the UI shows
"—" or an empty state, never an invented number.

### Security

- Passwords are hashed with bcrypt. A login attempt for an unknown user takes the same time
  as a wrong password, so attackers can't use timing to discover usernames.
- The session is a JWT in an `httpOnly`, `SameSite=Strict` cookie, so page scripts can never
  read it. API clients may send a Bearer token instead.
- Deactivating a user revokes their existing sessions immediately.
- Role-based access: `admin`, `operations`, `fleet_manager`, `compliance`, `viewer`.
- Sign-ins and failed sign-ins are written to `audit_events`.
- No credentials in the repo. Secrets come from `.env` (gitignored), and the admin account is
  created through the CLI.

## Local setup

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22+.

```bash
# 1. Configuration: copy and replace every "change-me" value
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # use for LOGITRACK_JWT_SECRET

# 2. Database
docker compose up -d --wait db

# 3. Backend
cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.cli create-admin --username <you> --email <you@example.com> --name "<Your Name>"
uv run python -m app.cli load-sample          # optional, clearly flagged demo data
uv run uvicorn app.main:app --reload --port 8090

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev                                    # http://localhost:5190
```

API docs are served at http://localhost:8090/docs.

The sample dataset is two weeks of generated activity relative to today. While it is loaded,
every dashboard shows a **Sample data** banner. Remove it with
`uv run python -m app.cli clear-sample --yes`. The command refuses to run on a database that
holds real records.

## Tests

```bash
# Backend: runs Alembic migrations into the separate logitrack_test database
cd backend && uv run pytest && uv run ruff check .

# Frontend unit/component tests, type check and lint
cd frontend && npm test && npm run typecheck && npm run lint

# End-to-end: rebuilds an isolated `logitrack_e2e` database (migrations + sample data +
# a throwaway admin with a per-run random password), builds the app, starts the API on
# :8091 and the preview server on :4190. Your development database is never touched.
cd frontend && npx playwright install chromium && npm run e2e
```

## Operational workflow (Milestone 2)

1. **Fleet & Trucks.** Register drivers and trucks (registration is normalised, e.g.
   `kca 204t` → `KCA 204T`). Assign or reassign drivers, and put trucks into maintenance or
   out of service.
2. **Loading Bays.** Book a bay for an available truck. Overlapping bookings for the same
   bay or the same truck are rejected with a message naming the conflict. Trucks in
   maintenance can't be booked.
3. **Record the loading times:** *Record arrival → Start loading → Finish loading*.
   - Each time defaults to now and can be corrected if entered late.
   - Times can't be in the future and can't be earlier than the previous step.
   - Recording the arrival sets the truck to *loading*.
4. **Dispatch.** Pick a loaded truck and a route. The dispatch time becomes the departure,
   which closes the turnaround (`departure − arrival`). The ETA is calculated from the
   route's expected duration, and the truck becomes *in transit*.
5. **Deliver.**
   - Record the actual arrival.
   - Deliveries more than the grace period late (default 15 min, setting
     `LOGITRACK_DELAY_GRACE_MINUTES`) are flagged as delayed. A **delay cause is required**
     and is recorded as a delay incident for recurring-cause analysis.
   - Trips in transit can also be flagged as delayed early.
   - When the delivery is recorded, the truck becomes *available* again.

Every step is written to the audit log with the acting user. Role permissions:

| Action | Roles |
|--------|-------|
| Register and edit drivers and trucks | Fleet Manager, Administrator |
| Bays, routes, schedules, loading times, dispatch, delivery | Operations, Administrator |
| Add, renew and upload compliance documents | Compliance, Fleet Manager, Administrator |
| Change mandatory-document requirements | Compliance, Administrator |
| Report, assign, update and resolve delays; acknowledge and resolve alerts | Operations, Fleet Manager, Compliance, Administrator |
| View everything, including documents | All signed-in roles (Viewer is read-only) |

Every write is checked on the server; the UI only hides buttons as a convenience.

## Compliance, delays and alerts (Milestone 3)

### Compliance records

- **Documents.** Insurance, vehicle licence, inspection certificate, roadworthiness, speed
  governor and other. Each has a reference, issuing authority, issue and expiry dates, notes
  and an optional supporting file.
- **Renewal.** Renewing a document creates a new current record and keeps the old one as
  history (`renewed_from_id`, `superseded_at`). A renewal must expire later than the current
  document.
- **Configurable requirements.** For each document type you can set whether it's mandatory,
  the minimum truck capacity it applies to, and a reminder window. Defaults: insurance,
  vehicle licence and inspection are mandatory, with a 30-day reminder.
- **Dispatch enforcement.**
  - Rules checked when a dispatch is created, on the server: a truck under maintenance or out
    of service, or one with a missing or expired mandatory document, is blocked. The 409
    response lists every reason.
  - Concurrency: the check runs in the same transaction as the dispatch, with a row lock on
    the truck.
  - Audit: blocked attempts are audited.
  - Restoring eligibility: an authorised renewal makes the truck eligible again.
- **File storage.**
  - Accepted files: PDF, PNG and JPEG up to 10 MB. The type is detected from the file's
    content, not the name or the type the browser reports.
  - Storage: files sit under `backend/var/uploads/` (gitignored, set by
    `LOGITRACK_UPLOAD_DIR`) using random 128-bit keys, and the SHA-256 is recorded.
  - Downloads: served only through the authenticated API, as attachments with `nosniff`.

### Delay incidents

- **Reporting.** Report a delay against a loading schedule or a dispatch. Categories: loading
  congestion, vehicle breakdown, documentation issue, equipment failure, truck unavailability,
  traffic, other. Each records a start time, impact minutes, a description and a responsible
  staff member.
- **Workflow.** Status moves open → investigating → in progress → resolved. Resolving
  requires resolution notes and a resolution time; reopening clears that time.
- **Duration** is always `resolved_at − occurred_at`, calculated from stored timestamps.
  Late-delivery incidents start at the missed ETA.

### Operational alerts

- **Types.** Missing, expired and expiring documents; upcoming inspections; vehicles in
  maintenance; loading over target; missed dispatch times; overdue deliveries; unresolved
  delays (over 4 h).
- **Severity.** Info, warning or critical. If an acknowledged alert gets more severe, it
  re-opens.
- **Deduplication.** Each condition has a stable key, and the database allows only one
  unresolved alert per key.
- **Resolution.** Alerts resolve automatically when the condition clears. Resolving one
  manually needs a note and stops it re-appearing for 24 h. History is kept.
- **Evaluation.** Alerts are re-checked when read, at most every 60 s
  (`LOGITRACK_ALERT_REFRESH_SECONDS`). For a scheduled job, run
  `uv run python -m app.cli refresh-alerts`. No SMS or email is sent.
- **Where they appear.** The top-bar bell, the Alerts page, and the Overview, Fleet, Loading
  Bays and Dispatch pages. Each alert links to the affected truck, booking or dispatch.

### API endpoints (Milestone 3)

| Method & path | Purpose |
|---------------|---------|
| `GET /api/compliance/overview` | KPIs, status by document type, upcoming renewals |
| `GET /api/compliance/vehicles` | Per-vehicle compliance (`q`, `status`, `doc_type`, paging) |
| `GET /api/trucks/{id}/compliance` · `/eligibility` · `/documents` | Vehicle view, dispatch eligibility, documents including history |
| `POST /api/compliance/documents` · `POST …/{id}/renew` | Create a document; renew (keeps history) |
| `PUT` / `GET /api/compliance/documents/{id}/file` | Upload / download the supporting file |
| `GET` / `PUT /api/compliance/requirements[/{type}]` | Read / configure mandatory documents |
| `GET` / `POST /api/incidents`, `PATCH /api/incidents/{id}` | List (filters) / report / update and resolve delays |
| `GET /api/incidents/summary`, `GET /api/users/assignable` | Delay KPIs; staff available for assignment |
| `GET /api/alerts`, `GET /api/alerts/summary` | Alerts (`status`, `severity`, `types`, `truck_id`); bell summary |
| `POST /api/alerts/{id}/acknowledge` · `/resolve` · `POST /api/alerts/refresh` | Alert actions |
| `GET /api/analytics/turnaround` | Turnaround KPIs, trend, per-bay performance, delay causes |

Full interactive documentation: http://localhost:8090/docs.

## Project status

### Working (Milestone 3)

- **Compliance Records page** (approved design): KPIs, expiry overview by type, fleet status
  donut, upcoming renewals, and a vehicle table with filters. The per-vehicle documents view
  covers eligibility, add, renew, upload, download and history, alongside a requirements
  editor.
- **Dispatch enforcement**, shown in the Fleet truck panel and the New Dispatch form, and
  enforced by the server.
- **Delay Reports page:** KPIs, cause breakdown, unresolved list, filterable incident table,
  and the report and update dialogs. A "Delay" action is available on loading schedules.
- **Operational alerts:** bell with badge, Alerts page, and alert cards on Overview, Fleet,
  Loading Bays and Dispatch.
- **Turnaround-Time Analytics page** (approved design): KPIs, trend against target, delay
  causes, turnaround by bay, and recent incidents.
- **Tests:** 89 backend, 29 frontend unit/component, and 12 end-to-end (8 desktop and 4
  mobile). The end-to-end tests cover a dispatch blocked for missing documents and then
  allowed, a delay reported and resolved, and an alert acknowledged and resolved.

### Working (Milestone 2)

- **Fleet Management.** Truck register with search, status filter and pagination. Truck
  detail panel showing driver, last route, capacity, loads and average turnaround over the
  last 30 days, and next compliance expiry. Add, edit and reassign trucks, add drivers, and
  set maintenance or out-of-service status.
- **Loading Bays & Scheduling:**
  - KPIs for the selected day, an hourly scheduled-vs-completed chart, and a live
    bay-utilisation donut.
  - Bay status cards with booking progress, upcoming loads, and alerts for late or
    overrunning loads.
  - A schedule table with bay and status filters and step-by-step workflow actions.
- **Dispatch Management:**
  - KPIs, an hourly status chart, today's status breakdown, alerts, and 7-day performance
    (on-time %, delayed %, average delivery duration).
  - A monitoring table with status and route filters and the Delivered / Flag delay actions.
- **Turnaround** is calculated from recorded timestamps and compared with each bay's
  target, falling back to the global target. It appears in the schedule and dispatch tables,
  the truck panel and the Overview.
- **"On-time"** has one definition everywhere: arrival ≤ ETA + grace period.
- **Tests:** 48 backend, 26 frontend unit/component, and 10 end-to-end. The end-to-end suite
  includes the full workflow driven through the UI and a bay double-booking rejection.

### Working (Milestone 1)

- **Infrastructure:** Docker PostgreSQL, Alembic migrations, a full relational schema with
  constraints and indexes, and environment-based configuration.
- **Authentication:**
  - Sign-in and sign-out with an httpOnly cookie session.
  - Role checks on the API and in the navigation; admin-only modules are hidden from other roles.
  - Audit events for sign-ins.
- **App shell:**
  - The approved design: teal sidebar, navy top bar, cyan gradient workspace, white cards.
  - A collapsible sidebar on desktop and a drawer on mobile, plus module search.
  - Every sidebar item opens a real route.
- **Operations Overview:**
  - KPIs with comparison against the previous period.
  - Performance trend chart, dispatch status breakdown, recent dispatches, fleet status and
    compliance expiry alerts.
  - All figures come from database queries, with loading, empty and error states.
- **Tests:** 28 backend, 16 frontend unit/component, and 8 end-to-end (desktop + mobile).

### Sample / not live

- The local database can hold the generated sample dataset, which is flagged in the UI with
  a banner.
- Records you enter through the app are real rows, but while the sample dataset is loaded
  they sit alongside it. `clear-sample` deletes **all** operational records, so clear the
  sample before entering real data.

### Not built yet (pages exist and say so; they show no figures)

| Next | Scope |
|------|-------|
| 4 | Reports: filtering, CSV export, PDF reports |
| 5 | User management UI, activity log viewer, settings (targets, grace period, policies) |

Also outstanding:
- Login rate limiting and global record search.
- Editing or correcting a document's reference without renewing it (documents are
  deliberately immutable for now).
- Antivirus scanning and object storage for uploaded files.
- A background scheduler for alerts. Alerts are currently refreshed when read or by the CLI.
- Fleet export (it belongs with Reports).
- Editing or deleting bays and routes (they can only be created for now).
- Truck photos, mileage and service-date fields shown in the design. They need new fields
  first, so the panel shows an illustration instead.
- The Tasks, Finance and Announcements backlog.
- A Login screen design. The current sign-in page is provisional, pending an approved design.
