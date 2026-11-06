# Maintenance Operations (CMMS)

LogiTrack has two workspaces that share one account system: **Logistics Operations** (the
original application) and **Maintenance Operations** (equipment, preventive maintenance,
work orders, breakdowns, spare parts and maintenance analytics). This document describes the
design; it is updated as each milestone lands.

| Milestone | Scope | Status |
|-----------|-------|--------|
| 1 — Foundation | Workspace chooser, maintenance sign-in, workspace-bound sessions, password re-authentication, maintenance roles | Done |
| 2 — Equipment | Equipment register, details, maintenance history | Done |
| 3 — Scheduling | Preventive-maintenance plans, recurring tasks, overdue flags | Done |
| 4 — Work orders | Work-order lifecycle, breakdown tracking, repair records | Done |
| 5 — Spare parts | Inventory, consumption, reorder alerts | Planned |
| 6 — Analytics | Dashboard KPIs, MTTR, MTBF, PM compliance, availability, exports | Planned |
| 7 — Quality | End-to-end, security and responsive testing; documentation | Planned |

Until a module is built its page says so and shows no figures.

## Workspaces and sessions

* `/welcome` is the public entry point. Choosing a workspace opens its own sign-in page:
  `/login` (logistics, unchanged) or `/maintenance/login`.
* Every session token carries a `ws` claim (`logistics` or `maintenance`). The token is the
  existing signed, httpOnly, `SameSite=Strict` cookie; no second authentication system or
  database was added, and password hashing (bcrypt) is unchanged.
* **The API enforces the workspace.** Each logistics router is mounted with
  `require_workspace(LOGISTICS)` and the maintenance router with
  `require_workspace(MAINTENANCE)` (`backend/app/main.py`). A session for the other workspace
  gets **403** with `X-Workspace-Required`, never data. Authentication, `/api/meta` and
  administrator user management are shared.
* **Switching always needs the password.** `POST /api/auth/switch-workspace` re-verifies the
  password, is throttled with the same lockout as sign-in (5 failures → 15-minute lock) and is
  audited (`auth.workspace_switched` / `auth.workspace_switch_failed`). Success replaces the
  session token, so the previous workspace is closed.
* In the browser, opening a URL of the other workspace shows a password prompt instead of the
  page; there is no automatic cross-workspace access. Signing in on the other workspace's
  sign-in page (username and password) also works.
* Tokens issued before this change carry no `ws` claim and remain logistics sessions, so no
  one was signed out by the upgrade. A token with an unknown `ws` value is rejected.

## Who can enter Maintenance

`users.maintenance_role` (nullable) grants access. `NULL` means no access; administrators
always have full access and act as maintenance managers. Administrators set the role on the
User Management page; changing it revokes that user's sessions immediately. A user without a
role who signs in to Maintenance is refused **after** the password check (so the response does
not reveal whether an account exists) and no session is issued.

| Permission (`maintenance_permissions.py`) | Manager | Planner | Technician | Storekeeper | Viewer |
|---|:-:|:-:|:-:|:-:|:-:|
| View dashboards, registers, history, reports | ✓ | ✓ | ✓ | ✓ | ✓ |
| Add, edit, archive equipment | ✓ | ✓ | | | |
| Manage preventive-maintenance plans | ✓ | ✓ | | | |
| Create work orders | ✓ | ✓ | ✓ | | |
| Assign work orders | ✓ | ✓ | | | |
| Work on / complete work orders | ✓ | ✓ | ✓ | | |
| Log breakdowns | ✓ | ✓ | ✓ | | |
| Manage spare-parts stock | ✓ | | | ✓ | |
| Issue parts to a work order | ✓ | ✓ | ✓ | ✓ | |
| Export reports | ✓ | ✓ | | ✓ | |
| Maintenance settings | ✓ | | | | |

The API checks these with `require_maintenance(<permission>)`; `GET /api/maintenance/access`
returns the caller's effective role and permissions so the UI only offers allowed actions.

## Equipment register (Milestone 2)

Tables `equipment` and `equipment_events` (`backend/app/models_maintenance.py`).

* **Equipment ID** (`code`) is unique, upper-case, 2–30 letters/digits/dashes (e.g. `CNV-001`)
  and cannot be changed after registration. Serial numbers, when given, are unique.
* Categories: conveyor, motor, compressor, hydraulic system, pump, production machine,
  generator, electrical, other. Status: operational, under maintenance, out of service.
* Server-side validation: installation and last-service dates cannot be in the future; the
  last service cannot precede installation; the next service cannot precede the last. The two
  date-order rules are also database CHECK constraints.
* The assigned technician must be an active user with a technician, planner or manager
  maintenance role (or an administrator).
* **Service state** is derived, never stored: `overdue` (next service date has passed),
  `due_soon` (within 14 days), `scheduled`, or `not_scheduled`. Dates use the configured
  operations timezone. Until preventive-maintenance plans exist (Milestone 3) the next service
  date is entered by hand.
* **Archiving** requires a reason, removes the asset from the active register and counts, and
  blocks edits; the record and its history are kept and it can be restored.
* **Maintenance history**: every registration, edit (with before/after values), status change,
  technician assignment, archive and restore is appended to `equipment_events` and to the
  audit log. Later modules add servicing, work orders and breakdowns to the same timeline.

API (`/api/maintenance/equipment`, maintenance session required): `GET` list (search, category,
status, facility, service-state and archived filters, paginated), `GET /summary`,
`GET /options`, `GET /{id}` (with history), `POST`, `PATCH /{id}`, `POST /{id}/archive`,
`POST /{id}/restore`. Writes need `equipment.manage`.

## Preventive maintenance (Milestone 3)

Tables `maintenance_plans` and `maintenance_tasks`; rules in `backend/app/services/pm.py`.

* **Date-based only.** No dependable equipment meter readings exist, so there is no
  operating-hour scheduling.
* A **plan** repeats every N days, weeks or months (month arithmetic clamps to month end:
  31 Jan + 1 month = 28/29 Feb). Creating it generates the first task on its first due date.
  A **once-off service** can also be scheduled without a plan.
* **One open task per plan**, enforced by a partial unique index: a late plan shows one
  overdue task, it never piles up duplicates.
* **Closing a task generates the next one.** Completing it (completion date not in the
  future, *work performed* required) or cancelling it (reason required) schedules the plan's
  next task. Next due date: `due_date` basis = previous due date + interval (fixed calendar;
  late work does not shift the schedule, so a very late completion can leave the next task
  already overdue — reported as such); `completion_date` basis = completion date + interval.
* **Overdue rule:** a task is overdue when its due date (operations timezone) has passed and it
  is still scheduled — not completed and not cancelled. "Overdue" is derived on every read and
  never stored. **Nothing is ever completed automatically.**
* **Concurrency:** completing or cancelling locks the task row; a second simultaneous attempt
  gets 409, and exactly one next task is generated (covered by a two-thread test).
* **Equipment dates follow the schedule.** Once an asset has plans or tasks, its next service
  date is its earliest open task and its last service date its latest completion; the
  equipment form shows them read-only and the API refuses hand edits (409). The Milestone 2
  CHECK "next service ≥ last service" was dropped (migration `d5f9b2c3e4a6`) because an asset
  with several plans can have one task overdue while another was serviced today.
* **Archiving equipment** stops its plans and cancels its open tasks with the archive reason.
* **PM compliance** (summary, last 90 days): of the tasks that fell due in the window
  (excluding cancelled), the share completed on or before the due date. Late completions and
  still-open tasks count against it. When no task fell due the API returns `pct: null` and the
  UI says "No tasks fell due in the last 90 days" rather than showing 0 % or 100 %.
* **Overdue alert:** the maintenance top bar shows the live count of overdue plus due-today
  tasks and links to the overdue view.
* Permissions: plans, once-off scheduling, rescheduling, reassigning and cancelling need
  `plans.manage`; completing needs `work_orders.work` (technicians included).

API under `/api/maintenance`: `GET /pm/summary`; `GET|POST /plans`, `PATCH /plans/{id}`,
`POST /plans/{id}/deactivate|activate`; `GET|POST /tasks` (views: overdue, due_today,
upcoming, open, completed, cancelled, all; `mine`, `equipment_id`, `technician_id`,
`within_days`), `PATCH /tasks/{id}`, `POST /tasks/{id}/complete|cancel`. Every change is added
to the equipment history and the audit log.

## Work orders and breakdowns (Milestone 4)

Tables `work_orders`, `work_order_events`, `breakdowns`; rules in
`backend/app/services/workorders.py`. Numbers come from database sequences
(`WO-2026-00001`, `BD-2026-00001`); they are never reused and may have gaps.

**Lifecycle** (anything else is refused with 409; also enforced by CHECK constraints):

| From | Allowed next |
|---|---|
| Open | Assigned (by assigning a technician), Cancelled |
| Assigned | In progress, Open (by unassigning), Cancelled |
| In progress | Awaiting parts, Completed, Cancelled |
| Awaiting parts | In progress, Cancelled |
| Completed / Cancelled | — (final) |

* **Completing** requires that work started, an assigned technician, the *work performed*
  (≥ 10 characters), and a completion time not in the future and not before the start. Forms
  enter times to the minute, so a time within the start's own minute is clamped to the start.
* **Cancelling** needs a reason and `work_orders.assign`. Started work cannot be unassigned,
  only reassigned.
* **Technicians** may start, pause, resume and complete only work orders assigned to them; they
  can raise work orders and assign them to themselves. Planners and managers can act on any.
* Every transition and assignment is appended to `work_order_events` (who, when, from → to,
  note) and the audit log; completions and cancellations also go into the equipment history.
* Completing and transitioning lock the row; a concurrent second completion gets 409 (tested
  with two simultaneous sessions).
* **Repair duration** = start to completion, including time awaiting parts.
* **Parts consumed** are recorded against work orders by the spare-parts module (Milestone 5).

**Breakdowns**

* A breakdown runs from the failure start to restoration (`restored_at`), with severity, fault
  category, description, possible cause and actions taken. Times cannot be in the future.
* **No double counting.** An asset has at most one open breakdown (partial unique index), and
  a new breakdown cannot start before the previous one of the same asset was restored. Periods
  of one asset therefore never overlap, so summed downtime is exact.
* **Downtime** counts only failures that stopped the asset (`equipment_down`); an open
  breakdown counts up to now. Summaries clip each breakdown to the reporting window.
* Logging a breakdown can raise a corrective work order whose priority follows the severity
  (critical → critical, major → high, minor → medium). Completing that work order can also
  record the restoration at the completion time.
* **Recurring failures:** the summary ranks equipment by breakdowns in the last 90 days, counts
  assets with two or more, and totals breakdowns and downtime per fault category.

**Equipment status follows the work** (each automatic change is written to the equipment
history): a breakdown that stops the asset → out of service; starting work → under
maintenance (unless out of service); restoration or the end of the last active work order →
operational again when nothing else holds it down. Archiving is refused while the asset has
open work orders or an open breakdown.

API under `/api/maintenance`: `GET /work-orders` (status, active, overdue, priority, mine,
equipment, search), `GET /work-orders/summary`, `GET /work-orders/{id}` (with history),
`POST /work-orders`, `PATCH /work-orders/{id}`, `POST /work-orders/{id}/transition`,
`POST /work-orders/{id}/complete`; `GET /breakdowns`, `GET /breakdowns/summary?days=`,
`POST /breakdowns`, `PATCH /breakdowns/{id}`, `POST /breakdowns/{id}/restore`.

## Migrations

`e6a0c3d4f5b7` creates the work-order, work-order-event and breakdown tables and two number
sequences (new objects only).

`d5f9b2c3e4a6` creates the plan and task tables and drops the equipment
`next_service_after_last` CHECK (see above). Its downgrade restores the CHECK after clearing
next-service dates that would violate it.

`c4e8a1d2f3b5` creates the two equipment tables (new tables only).

`b7d2e4f1a9c0` adds the nullable `users.maintenance_role` column with a CHECK constraint. It is
additive: existing users and records are untouched, and every existing user keeps logistics
access only until an administrator grants a maintenance role.
