/** Maintenance workspace types and labels (mirrors backend schemas_maintenance.py). */
import { useApi } from '../hooks/useApi'
import { api } from './api'

/** JSON request helper for maintenance actions (POST by default). */
export const send = <T,>(path: string, body: unknown, method = 'POST') =>
  api<T>(path, { method, body: JSON.stringify(body) })
export const techId = (v: string) => (v ? Number(v) : null)
import type { MaintenanceRole } from './types'

export type EquipmentCategory =
  | 'conveyor' | 'motor' | 'compressor' | 'hydraulic_system' | 'pump' | 'production_machine'
  | 'generator' | 'electrical' | 'other'
export type EquipmentStatus = 'operational' | 'under_maintenance' | 'out_of_service'
export type ServiceState = 'overdue' | 'due_soon' | 'scheduled' | 'not_scheduled'

export const CATEGORY_LABELS: Record<EquipmentCategory, string> = {
  conveyor: 'Conveyor',
  motor: 'Motor',
  compressor: 'Compressor',
  hydraulic_system: 'Hydraulic system',
  pump: 'Pump',
  production_machine: 'Production machine',
  generator: 'Generator',
  electrical: 'Electrical',
  other: 'Other',
}
export const EQUIPMENT_STATUS_LABELS: Record<EquipmentStatus, string> = {
  operational: 'Operational',
  under_maintenance: 'Under maintenance',
  out_of_service: 'Out of service',
}
export const SERVICE_STATE_LABELS: Record<ServiceState, string> = {
  overdue: 'Overdue',
  due_soon: 'Due soon',
  scheduled: 'Scheduled',
  not_scheduled: 'Not scheduled',
}

export interface Person {
  id: number
  full_name: string
}

export interface Equipment {
  id: number
  code: string
  name: string
  category: EquipmentCategory
  manufacturer: string | null
  model: string | null
  serial_number: string | null
  facility: string
  department: string | null
  location: string | null
  installed_on: string | null
  status: EquipmentStatus
  assigned_technician: Person | null
  last_service_on: string | null
  next_service_on: string | null
  notes: string | null
  archived_at: string | null
  created_at: string
  updated_at: string
  service_state: ServiceState
  days_until_service: number | null
}

export interface EquipmentEvent {
  id: number
  occurred_at: string
  kind: string
  summary: string
  changes: Record<string, unknown> | null
  actor: Person | null
}

export interface EquipmentDetail extends Equipment {
  history: EquipmentEvent[]
  /** Service dates come from preventive maintenance (read-only in the equipment form). */
  schedule_managed: boolean
}

// ---------- Preventive maintenance ----------
export type IntervalUnit = 'days' | 'weeks' | 'months'
export type ScheduleBasis = 'due_date' | 'completion_date'
export type TaskState = 'overdue' | 'due_today' | 'upcoming' | 'completed' | 'cancelled'

export interface EquipmentRef {
  id: number
  code: string
  name: string
}

export interface MaintenancePlan {
  id: number
  equipment: EquipmentRef
  title: string
  instructions: string | null
  interval_value: number
  interval_unit: IntervalUnit
  schedule_basis: ScheduleBasis
  start_on: string
  assigned_technician: Person | null
  is_active: boolean
  next_task: { id: number; due_on: string; state: TaskState; days_until_due: number } | null
  last_completed_on: string | null
  created_at: string
}

export interface MaintenanceTask {
  id: number
  plan_id: number | null
  equipment: EquipmentRef
  title: string
  instructions: string | null
  due_on: string
  status: 'scheduled' | 'completed' | 'cancelled'
  state: TaskState
  days_until_due: number
  assigned_technician: Person | null
  completed_on: string | null
  completed_by: Person | null
  completed_on_time: boolean | null
  work_notes: string | null
  cancel_reason: string | null
}

export interface PmSummary {
  overdue: number
  due_today: number
  due_next_7_days: number
  open: number
  active_plans: number
  completed_last_30_days: number
  compliance: {
    window_days: number
    due: number
    completed_on_time: number
    completed_late: number
    not_completed: number
    pct: number | null
  }
}

export const TASK_STATE_LABELS: Record<TaskState, string> = {
  overdue: 'Overdue',
  due_today: 'Due today',
  upcoming: 'Upcoming',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

export function intervalText(value: number, unit: IntervalUnit): string {
  const word = unit.slice(0, -1)
  return value === 1 ? `Every ${word}` : `Every ${value} ${unit}`
}

export function dueText(t: { state: TaskState; days_until_due: number }): string {
  const n = Math.abs(t.days_until_due)
  if (t.state === 'overdue') return `${n} day${n === 1 ? '' : 's'} overdue`
  if (t.state === 'due_today') return 'Due today'
  if (t.state === 'upcoming') return `Due in ${n} day${n === 1 ? '' : 's'}`
  return ''
}

export interface EquipmentSummary {
  total: number
  operational: number
  under_maintenance: number
  out_of_service: number
  service_overdue: number
  service_due_soon: number
  archived: number
  due_soon_days: number
}

export interface EquipmentOptions {
  facilities: string[]
  departments: string[]
  locations: string[]
  technicians: (Person & { maintenance_role: MaintenanceRole })[]
}

export type MaintenancePermission =
  | 'view' | 'equipment.manage' | 'plans.manage' | 'work_orders.create' | 'work_orders.assign'
  | 'work_orders.work' | 'breakdowns.log' | 'parts.manage' | 'parts.consume' | 'reports.export'
  | 'settings.manage'

interface Access {
  maintenance_role: MaintenanceRole
  permissions: MaintenancePermission[]
  sample_data?: boolean
}

/** MTBF-style durations: hours from 1 h up, minutes below, so a short value never reads "0 h". */
export function hoursOrMinutes(hours: number): string {
  if (hours >= 1) return `${new Intl.NumberFormat('en-KE', { maximumFractionDigits: 1 }).format(hours)} h`
  const minutes = Math.round(hours * 60)
  return minutes < 1 ? '< 1 min' : `${minutes} min`
}

/** The caller's maintenance permissions, from the API (which also enforces them). */
export function useMaintenanceAccess() {
  const { data } = useApi<Access>('/maintenance/access')
  return {
    role: data?.maintenance_role,
    sampleData: !!data?.sample_data,
    can: (p: MaintenancePermission) => !!data?.permissions.includes(p),
  }
}

// ---------- Work orders and breakdowns ----------
export type WorkOrderStatus = 'open' | 'assigned' | 'in_progress' | 'awaiting_parts' | 'completed' | 'cancelled'
export type WorkOrderType = 'corrective' | 'preventive' | 'inspection' | 'improvement'
export type Priority = 'low' | 'medium' | 'high' | 'critical'
export type Severity = 'minor' | 'major' | 'critical'
export type FaultCategory =
  | 'mechanical' | 'electrical' | 'hydraulic' | 'pneumatic' | 'instrumentation' | 'lubrication' | 'operational' | 'other'

export const WO_STATUS_LABELS: Record<WorkOrderStatus, string> = {
  open: 'Open', assigned: 'Assigned', in_progress: 'In progress', awaiting_parts: 'Awaiting parts',
  completed: 'Completed', cancelled: 'Cancelled',
}
export const WO_TYPE_LABELS: Record<WorkOrderType, string> = {
  corrective: 'Corrective repair', preventive: 'Preventive', inspection: 'Inspection', improvement: 'Improvement',
}
export const PRIORITY_LABELS: Record<Priority, string> = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' }
export const SEVERITY_LABELS: Record<Severity, string> = { minor: 'Minor', major: 'Major', critical: 'Critical' }
export const FAULT_LABELS: Record<FaultCategory, string> = {
  mechanical: 'Mechanical', electrical: 'Electrical', hydraulic: 'Hydraulic', pneumatic: 'Pneumatic',
  instrumentation: 'Instrumentation', lubrication: 'Lubrication', operational: 'Operational / operator', other: 'Other',
}

export interface BreakdownBrief {
  id: number
  number: string
  is_open: boolean
  started_at: string
  restored_at: string | null
}

export interface WorkOrder {
  id: number
  number: string
  equipment: EquipmentRef
  maintenance_type: WorkOrderType
  priority: Priority
  status: WorkOrderStatus
  fault_description: string
  assigned_technician: Person | null
  scheduled_on: string | null
  overdue: boolean
  created_at: string
  created_by: Person | null
  started_at: string | null
  completed_at: string | null
  repair_minutes: number | null
  work_performed: string | null
  completion_notes: string | null
  cancel_reason: string | null
  breakdown: BreakdownBrief | null
  allowed_transitions: WorkOrderStatus[]
}

export interface WorkOrderDetail extends WorkOrder {
  history: {
    id: number
    occurred_at: string
    from_status: WorkOrderStatus | null
    to_status: WorkOrderStatus | null
    summary: string
    note: string | null
    actor: Person | null
  }[]
}

export interface WorkOrderSummary {
  open: number
  assigned: number
  in_progress: number
  awaiting_parts: number
  completed_last_30_days: number
  overdue: number
  critical_open: number
}

export interface Breakdown {
  id: number
  number: string
  equipment: EquipmentRef
  started_at: string
  restored_at: string | null
  is_open: boolean
  downtime_minutes: number
  severity: Severity
  category: FaultCategory
  description: string
  possible_cause: string | null
  actions_taken: string | null
  equipment_down: boolean
  reported_by: Person | null
  restored_by: Person | null
  work_orders: { id: number; number: string; status: WorkOrderStatus }[]
}

export interface BreakdownSummary {
  window_days: number
  open: number
  breakdowns: number
  downtime_minutes: number
  repeat_equipment: number
  top_equipment: { equipment: EquipmentRef; breakdowns: number; downtime_minutes: number }[]
  categories: { category: FaultCategory; breakdowns: number; downtime_minutes: number }[]
}

// ---------- Spare parts ----------
export type StockUnit = 'each' | 'set' | 'metre' | 'litre' | 'kg'
export type MovementKind = 'receipt' | 'issue' | 'return' | 'adjustment'
export type StockState = 'out_of_stock' | 'low' | 'ok'

export const UNIT_LABELS: Record<StockUnit, string> = { each: 'Each', set: 'Set', metre: 'Metre', litre: 'Litre', kg: 'Kilogram' }
export const WHOLE_UNITS: StockUnit[] = ['each', 'set']
export const MOVEMENT_LABELS: Record<MovementKind, string> = {
  receipt: 'Received', issue: 'Issued', return: 'Returned', adjustment: 'Stock count',
}
export const STOCK_STATE_LABELS: Record<StockState, string> = { out_of_stock: 'Out of stock', low: 'Low stock', ok: 'In stock' }

export interface SparePart {
  id: number
  part_number: string
  name: string
  description: string | null
  category: string | null
  unit: StockUnit
  on_hand: number
  reorder_level: number
  reorder_quantity: number | null
  location: string | null
  supplier: string | null
  unit_cost: number | null
  is_active: boolean
  stock_state: StockState
  stock_value: number | null
}

export interface StockMovement {
  id: number
  occurred_at: string
  kind: MovementKind
  quantity: number
  balance_after: number
  work_order: { id: number; number: string; status: WorkOrderStatus } | null
  reference: string | null
  note: string | null
  actor: Person | null
}

export interface SparePartDetail extends SparePart {
  movements: StockMovement[]
  issued_last_90_days: number
}

export interface PartsSummary {
  active_parts: number
  low_stock: number
  out_of_stock: number
  stock_value: number
  parts_without_cost: number
}

export interface WorkOrderParts {
  work_order: { id: number; number: string; status: WorkOrderStatus }
  lines: { part: SparePart; issued: number; returned: number; net: number; cost: number | null }[]
  movements: StockMovement[]
  total_cost: number | null
  can_issue: boolean
}

export function qty(n: number, unit: StockUnit): string {
  const text = Number.isInteger(n) ? String(n) : n.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')
  return `${text} ${unit === 'kg' ? 'kg' : unit}`
}

/** Short form for stat cards, e.g. "KES 114K" (the exact amount is shown alongside). */
export const moneyCompact = (n: number) =>
  `KES ${new Intl.NumberFormat('en-KE', { notation: 'compact', maximumFractionDigits: 1 }).format(n)}`

export const money = (n: number | null | undefined) =>
  n == null ? '—' : `KES ${new Intl.NumberFormat('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)}`

/** Mirrors the server rule: positive, at most 3 decimals, whole numbers for counted units. */
export function quantityProblem(raw: string, unit: StockUnit, label = 'quantity', allowZero = false): string | null {
  const n = Number(raw)
  if (raw.trim() === '' || !Number.isFinite(n)) return `Enter the ${label}.`
  if (allowZero ? n < 0 : n <= 0) return `The ${label} must be ${allowZero ? 'zero or more' : 'more than zero'}.`
  if (!/^\d+(\.\d{1,3})?$/.test(raw.trim())) return `The ${label} allows at most 3 decimals.`
  if (WHOLE_UNITS.includes(unit) && !Number.isInteger(n)) return `The ${label} must be a whole number.`
  return null
}

/** One id per user action: a retried or double-clicked submit is applied only once. */
export const newRequestId = () =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`

// ---------- Analytics ----------
export interface MaintenanceKpis {
  window: { start: string; end: string; days: number }
  equipment: number
  availability: { pct: number | null; observed_hours: number; downtime_minutes: number }
  mtbf: { hours: number | null; failures: number; operating_hours: number }
  mttr: { minutes: number | null; repairs: number }
  time_to_restore: { minutes: number | null; restorations: number }
  pm_compliance: { due: number; on_time: number; late: number; missed: number; pct: number | null }
  work_order_completion: { pct: number | null; raised: number; completed: number }
  definitions: string[]
}

export interface MaintenanceDashboard {
  window_days: number
  kpis: {
    equipment_total: number
    operational: number
    under_maintenance: number
    out_of_service: number
    open_work_orders: number
    overdue_tasks: number
    overdue_pm_tasks: number
    overdue_work_orders: number
    scheduled_pm_next_30_days: number
    downtime_minutes: number
    completion_rate_pct: number | null
    completion_sample: number
  }
  schedule: { overdue: number; due_today: number; next_7_days: number }
  work_orders: { open: number; assigned: number; in_progress: number; awaiting_parts: number; completed_in_window: number }
  metrics: Pick<MaintenanceKpis, 'availability' | 'mtbf' | 'mttr' | 'pm_compliance'>
  top_failing: { code: string; name: string; breakdowns: number; downtime_minutes: number }[]
  fault_categories: { category: FaultCategory; breakdowns: number; downtime_minutes: number }[]
  downtime_trend: { day: string; downtime_minutes: number }[]
  recent_activity: {
    id: number
    occurred_at: string
    kind: string
    summary: string
    equipment: EquipmentRef
    actor: string | null
  }[]
  definitions: string[]
}

export interface EquipmentAnalyticsRow {
  equipment_id: number
  code: string
  name: string
  facility: string
  status: EquipmentStatus
  breakdowns: number
  failures: number
  downtime_minutes: number
  observed_hours: number
  availability_pct: number | null
  mtbf_hours: number | null
  repairs: number
  mttr_minutes: number | null
  pm_due: number
  pm_on_time: number
  pm_compliance_pct: number | null
}

export interface ReportPreview {
  key: string
  title: string
  description: string
  window: { start: string; end: string }
  columns: { label: string; key: string }[]
  rows: Record<string, string | number | null>[]
  total: number
  kpis: MaintenanceKpis
}

/** Fired after any change that can move maintenance counts (e.g. the top-bar alert). */
export const MAINTENANCE_CHANGED = 'logitrack:maintenance-changed'
export function notifyMaintenanceChanged() {
  window.dispatchEvent(new Event(MAINTENANCE_CHANGED))
}

export function serviceText(e: Pick<Equipment, 'service_state' | 'days_until_service'>): string {
  const d = e.days_until_service
  switch (e.service_state) {
    case 'overdue':
      return `${Math.abs(d!)} day${Math.abs(d!) === 1 ? '' : 's'} overdue`
    case 'due_soon':
      return d === 0 ? 'Due today' : `Due in ${d} day${d === 1 ? '' : 's'}`
    case 'scheduled':
      return `In ${d} days`
    default:
      return 'No service scheduled'
  }
}
