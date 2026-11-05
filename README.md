# LogiTrack — Logistics Operations Portal

LogiTrack is a logistics management platform for fleet, loading-bay scheduling, dispatch,
turnaround-time analytics and vehicle compliance. It was built as a portfolio project inspired
by the Graduate Logistics Systems Analyst role at Safal.

> **Status: Milestone 1 of 6 complete.** See [Project status](#project-status) for exactly what
> works today, what is sample data, and what is still to come.

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
  app/models.py        relational schema (10 domain tables + settings)
  app/routers/         auth, system (health/meta), dashboard
  app/services/        dashboard metrics, turnaround calculations, app settings
  app/sample_data.py   clearly-labelled demonstration dataset
  app/cli.py           create-admin / load-sample / clear-sample
  alembic/             migrations (the source of truth for the schema)
docker-compose.yml     local PostgreSQL (dev + test databases)
```

### Data model

`users`, `drivers`, `trucks`, `routes`, `loading_bays`, `loading_schedules`, `dispatches`,
`delay_incidents`, `compliance_documents`, `audit_events`, `app_settings`.

Business rules are enforced **in the database** as well as in the API:

- **No double-booked bays.** A PostgreSQL exclusion constraint (`btree_gist`) rejects
  overlapping bookings on the same bay; cancelled bookings don't block.
- **Ordered timestamps.** Loading can't start before arrival, can't finish before it starts,
  and the truck can't depart before loading finishes.
- **Data integrity.** Positive capacities, distances and durations. Unique truck registrations
  and load references. At most one truck per driver.
- **Complete deliveries.** A delivered dispatch must have an actual arrival time.
- **Traceable delays.** Each delay incident must be linked to a dispatch or a loading schedule.

### Metric definitions

| Metric | Definition |
|--------|------------|
| Turnaround time | `departed_at − arrival_at` of a loading schedule (truck arrival → departure) |
| Within target | Turnaround ≤ the bay's target, or the global target (default 120 min) |
| Loads processed | Loading schedules that departed in the period (excluding cancelled ones) |
| On-time delivery | Delivered dispatches arriving in the period with actual arrival ≤ expected arrival |
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
| View everything | All signed-in roles |

## Project status

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

| Milestone | Scope |
|-----------|-------|
| 3 | Turnaround analytics and delay reports pages |
| 4 | Compliance records management and expiry alerts workflow |
| 5 | User management UI, activity log viewer, settings (targets, policies) |
| 6 | Reports: filtering, CSV export, PDF reports |

Also outstanding:
- Login rate limiting, notifications, and global record search.
- Fleet export (it belongs with Reports).
- Editing or deleting bays and routes (they can only be created for now).
- Truck photos, mileage and service-date fields shown in the design. They need new fields
  first, so the panel shows an illustration instead.
- The Tasks, Finance and Announcements backlog.
- A Login screen design. The current sign-in page is provisional, pending an approved design.
