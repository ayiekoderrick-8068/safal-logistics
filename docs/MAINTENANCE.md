# Maintenance Operations (CMMS)

LogiTrack has two workspaces that share one account system: **Logistics Operations** (the
original application) and **Maintenance Operations** (equipment, preventive maintenance,
work orders, breakdowns, spare parts and maintenance analytics). This document describes the
design; it is updated as each milestone lands.

| Milestone | Scope | Status |
|-----------|-------|--------|
| 1 — Foundation | Workspace chooser, maintenance sign-in, workspace-bound sessions, password re-authentication, maintenance roles | Done |
| 2 — Equipment | Equipment register, details, maintenance history | Planned |
| 3 — Scheduling | Preventive-maintenance plans, recurring tasks, overdue flags | Planned |
| 4 — Work orders | Work-order lifecycle, breakdown tracking, repair records | Planned |
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

## Migration

`b7d2e4f1a9c0` adds the nullable `users.maintenance_role` column with a CHECK constraint. It is
additive: existing users and records are untouched, and every existing user keeps logistics
access only until an administrator grants a maintenance role.
