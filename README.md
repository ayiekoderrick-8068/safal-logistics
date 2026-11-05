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

# End-to-end: builds the app and starts backend + preview server automatically
cd frontend && npx playwright install chromium
E2E_USERNAME=<user> E2E_PASSWORD=<password> npm run e2e
```

## Project status

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

- The dashboard figures currently come from the generated sample dataset, which is flagged in
  the UI. There are no data-entry screens yet, so real records can't be added through the app.

### Not built yet (pages exist and say so; they show no figures)

| Milestone | Scope |
|-----------|-------|
| 2 | Core workflow: register truck → schedule loading → record loading times → dispatch → complete delivery → turnaround |
| 3 | Turnaround analytics and delay reports pages |
| 4 | Compliance records management and expiry alerts workflow |
| 5 | User management UI, activity log viewer, settings (targets, policies) |
| 6 | Reports: filtering, CSV export, PDF reports |

Also outstanding: login rate limiting, notifications, global record search, and a Tasks,
Finance and Announcements backlog.
