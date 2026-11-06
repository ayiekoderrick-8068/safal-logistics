"""What each maintenance role may do. Enforced by the API (`deps.require_maintenance`) and
published to the client (`GET /api/maintenance/access`) so the UI only offers allowed actions.

Administrators act as maintenance managers.
"""

import enum

from .models import MaintenanceRole as R


class MaintenancePermission(enum.StrEnum):
    VIEW = "view"  # dashboards, registers, history, reports
    MANAGE_EQUIPMENT = "equipment.manage"  # add, edit, archive equipment
    MANAGE_PLANS = "plans.manage"  # preventive-maintenance plans and schedules
    CREATE_WORK_ORDERS = "work_orders.create"
    ASSIGN_WORK_ORDERS = "work_orders.assign"
    WORK_ON_ORDERS = "work_orders.work"  # start, record work, complete
    LOG_BREAKDOWNS = "breakdowns.log"
    MANAGE_PARTS = "parts.manage"  # catalogue, receipts, stock adjustments
    CONSUME_PARTS = "parts.consume"  # issue parts to a work order
    EXPORT_REPORTS = "reports.export"
    MANAGE_SETTINGS = "settings.manage"


P = MaintenancePermission
_ALL = frozenset(P)

MATRIX: dict[R, frozenset[P]] = {
    R.MANAGER: _ALL,
    R.PLANNER: frozenset(
        {
            P.VIEW,
            P.MANAGE_EQUIPMENT,
            P.MANAGE_PLANS,
            P.CREATE_WORK_ORDERS,
            P.ASSIGN_WORK_ORDERS,
            P.WORK_ON_ORDERS,
            P.LOG_BREAKDOWNS,
            P.CONSUME_PARTS,
            P.EXPORT_REPORTS,
        }
    ),
    R.TECHNICIAN: frozenset(
        {P.VIEW, P.CREATE_WORK_ORDERS, P.WORK_ON_ORDERS, P.LOG_BREAKDOWNS, P.CONSUME_PARTS}
    ),
    R.STOREKEEPER: frozenset({P.VIEW, P.MANAGE_PARTS, P.CONSUME_PARTS, P.EXPORT_REPORTS}),
    R.VIEWER: frozenset({P.VIEW}),
}


def allows(role: R | None, permission: P) -> bool:
    return role is not None and permission in MATRIX[role]


def permissions_for(role: R | None) -> list[str]:
    return sorted(p.value for p in MATRIX.get(role, frozenset())) if role else []
