"""Preventive-maintenance scheduling rules.

* Date-based only (no meter readings exist yet, so no operating-hour schedules).
* A plan has exactly one open task at a time (enforced by a partial unique index).
* Closing a task - completing it, or cancelling it with a reason - generates the plan's next
  task. Nothing is ever completed automatically.
* Next due date: `due_date` basis = previous due date + interval (fixed calendar; if work is
  very late the next task may already be overdue, which is reported as such); `completion_date`
  basis = completion date + interval (floating). A cancelled task always advances from its due
  date.
* "Overdue" is derived at read time: status scheduled and due date before today (operations
  timezone).
"""

import calendar
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models_maintenance import (
    Equipment,
    IntervalUnit,
    MaintenancePlan,
    MaintenanceTask,
    ScheduleBasis,
    TaskStatus,
)


def add_interval(d: date, value: int, unit: IntervalUnit) -> date:
    if unit is IntervalUnit.DAYS:
        return date.fromordinal(d.toordinal() + value)
    if unit is IntervalUnit.WEEKS:
        return date.fromordinal(d.toordinal() + 7 * value)
    months = d.month - 1 + value
    year, month = d.year + months // 12, months % 12 + 1
    # Clamp to the month's last day (31 Jan + 1 month = 28/29 Feb).
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def next_due(plan: MaintenancePlan, closed: MaintenanceTask) -> date:
    base = closed.due_on
    if plan.schedule_basis is ScheduleBasis.COMPLETION_DATE and closed.completed_on:
        base = closed.completed_on
    nxt = add_interval(base, plan.interval_value, plan.interval_unit)
    # Never schedule the next cycle on or before the one just closed.
    if nxt <= closed.due_on:
        nxt = add_interval(closed.due_on, plan.interval_value, plan.interval_unit)
    return nxt


def task_state(task: MaintenanceTask, today: date) -> str:
    if task.status is not TaskStatus.SCHEDULED:
        return task.status.value
    if task.due_on < today:
        return "overdue"
    return "due_today" if task.due_on == today else "upcoming"


def create_task_for_plan(db: Session, plan: MaintenancePlan, due_on: date) -> MaintenanceTask:
    task = MaintenanceTask(
        plan_id=plan.id,
        equipment_id=plan.equipment_id,
        title=plan.title,
        due_on=due_on,
        assigned_technician_id=plan.assigned_technician_id,
    )
    db.add(task)
    return task


def sync_equipment_dates(db: Session, equipment: Equipment) -> None:
    """Once an asset has plans, its service dates come from them: next = earliest open task,
    last = latest completion (never moved backwards from a hand-entered value)."""
    db.flush()
    open_due = db.scalar(
        select(func.min(MaintenanceTask.due_on)).where(
            MaintenanceTask.equipment_id == equipment.id,
            MaintenanceTask.status == TaskStatus.SCHEDULED,
        )
    )
    last_done = db.scalar(
        select(func.max(MaintenanceTask.completed_on)).where(
            MaintenanceTask.equipment_id == equipment.id,
            MaintenanceTask.status == TaskStatus.COMPLETED,
        )
    )
    if open_due is not None or is_plan_driven(db, equipment.id):
        equipment.next_service_on = open_due
    if last_done and (equipment.last_service_on is None or last_done > equipment.last_service_on):
        equipment.last_service_on = last_done


def is_plan_driven(db: Session, equipment_id: int) -> bool:
    return bool(
        db.scalar(
            select(func.count(MaintenancePlan.id)).where(
                MaintenancePlan.equipment_id == equipment_id
            )
        )
        or db.scalar(
            select(func.count(MaintenanceTask.id)).where(
                MaintenanceTask.equipment_id == equipment_id
            )
        )
    )
