export type Role = 'admin' | 'operations' | 'fleet_manager' | 'compliance' | 'viewer'
export type MaintenanceRole = 'manager' | 'planner' | 'technician' | 'storekeeper' | 'viewer'
export type Workspace = 'logistics' | 'maintenance'

export interface User {
  id: number
  email: string
  username: string
  full_name: string
  role: Role
  status: 'active' | 'pending' | 'deactivated'
  last_login_at: string | null
  /** Set after an administrator issues a temporary password. */
  must_change_password?: boolean
  /** Null = no Maintenance workspace access (administrators always have it). */
  maintenance_role?: MaintenanceRole | null
  /** Workspaces this account may enter. */
  workspaces?: Workspace[]
}

/** The signed-in account plus the workspace the current session is bound to. */
export interface SessionUser extends User {
  workspace: Workspace
}

/** User as seen by administrators on the User Management page. */
export interface AdminUser extends User {
  created_at: string
  password_changed_at: string | null
}

export interface Meta {
  app: string
  version: string
  timezone: string
  turnaround_target_minutes: number
  delay_grace_minutes: number
  sample_data: boolean
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Ref {
  id: number
  label: string
}

export type TruckStatus = 'available' | 'loading' | 'in_transit' | 'maintenance' | 'out_of_service'
export type ScheduleStatus = 'scheduled' | 'arrived' | 'loading' | 'loaded' | 'departed' | 'cancelled'
export type DispatchStatus = 'pending' | 'in_transit' | 'delivered' | 'cancelled'
export type DelayCause =
  | 'loading_congestion'
  | 'vehicle_breakdown'
  | 'documentation'
  | 'truck_unavailability'
  | 'equipment_breakdown'
  | 'traffic'
  | 'other'

export interface Driver {
  id: number
  full_name: string
  phone: string | null
  licence_number: string
  licence_expiry: string | null
  is_active: boolean
  truck_id: number | null
  truck_registration: string | null
}

export interface Truck {
  id: number
  registration: string
  make: string | null
  model: string | null
  capacity_tonnes: number
  status: TruckStatus
  driver: Ref | null
  last_route: string | null
  last_dispatched_at: string | null
  compliance: {
    status: 'valid' | 'expiring' | 'overdue' | 'missing'
    next_expiry: string | null
    next_expiry_type: string | null
    eligible: boolean
    issues: string[]
  }
}

// ---------- Compliance ----------
export type DocType = 'insurance' | 'licence' | 'inspection' | 'roadworthy' | 'speed_governor' | 'other'
export type DocState = 'valid' | 'expiring' | 'expired' | 'missing' | 'not_required'

export interface ComplianceDocument {
  id: number
  truck: Ref
  doc_type: DocType
  reference_number: string
  issuing_authority: string | null
  issued_on: string
  expires_on: string
  days_remaining: number
  state: 'valid' | 'expiring' | 'expired'
  is_current: boolean
  superseded_at: string | null
  renewed_from_id: number | null
  file: { name: string; content_type: string; size: number; uploaded_at: string } | null
  notes: string | null
  created_at: string
}

export interface VehicleCompliance {
  truck: Ref
  driver_name: string | null
  truck_status: TruckStatus
  status: 'compliant' | 'expiring' | 'non_compliant'
  eligible: boolean
  blockers: string[]
  items: {
    doc_type: DocType
    mandatory: boolean
    state: DocState
    document_id: number | null
    expires_on: string | null
    days_remaining: number | null
  }[]
}

export interface Requirement {
  doc_type: DocType
  label: string
  is_mandatory: boolean
  min_capacity_tonnes: number | null
  reminder_days: number
}

export interface ComplianceOverview {
  total_vehicles: number
  compliant_vehicles: number
  expiring_vehicles: number
  non_compliant_vehicles: number
  compliant_pct: number | null
  expiring_documents: number
  expired_documents: number
  missing_documents: number
  documents_on_record: number
  documents_added_30d: number
  inspections_due_30d: number
  by_type: { doc_type: DocType; valid: number; expiring: number; expired: number; missing: number }[]
  upcoming: { document_id: number; truck: Ref; doc_type: DocType; expires_on: string; days_remaining: number; state: string }[]
  sample_data: boolean
}

// ---------- Delay incidents ----------
export type IncidentStatus = 'open' | 'investigating' | 'in_progress' | 'resolved'

export interface Incident {
  id: number
  source: 'loading' | 'dispatch'
  truck: Ref | null
  operation: string
  load_ref: string | null
  schedule_id: number | null
  dispatch_id: number | null
  cause: DelayCause
  status: IncidentStatus
  started_at: string
  resolved_at: string | null
  duration_minutes: number
  is_ongoing: boolean
  impact_minutes: number
  description: string | null
  resolution_notes: string | null
  assigned_to: Ref | null
  reported_by: string | null
  created_at: string
}

export interface IncidentSummary {
  unresolved: number
  unassigned: number
  resolved_7d: number
  avg_resolution_minutes_30d: number | null
  impact_minutes_7d: number
  oldest_unresolved_minutes: number | null
  by_cause_30d: { cause: DelayCause; count: number; impact_minutes: number }[]
  sample_data: boolean
}

export interface AssignableUser {
  id: number
  label: string
  role: Role
}

export interface TurnaroundAnalytics {
  period_start: string
  period_end: string
  previous_period_start: string
  previous_period_end: string
  target_minutes: number
  kpis: DashboardOverview['kpis']
  trend: DashboardOverview['trend']
  bays: {
    bay: Bay
    loads: number
    avg_turnaround_minutes: number | null
    avg_loading_minutes: number | null
    within_target_pct: number | null
    utilization_pct: number | null
    status: 'within' | 'above' | 'no_data'
  }[]
  causes: { cause: DelayCause; count: number; impact_minutes: number }[]
  recent_incidents: Incident[]
  sample_data: boolean
}

// ---------- Alerts ----------
export type AlertSeverity = 'info' | 'warning' | 'critical'

export interface OpsAlert {
  id: number
  alert_type: string
  severity: AlertSeverity
  status: 'open' | 'acknowledged' | 'resolved'
  title: string
  message: string
  link: string
  truck: Ref | null
  first_seen_at: string
  last_seen_at: string
  acknowledged_at: string | null
  acknowledged_by: string | null
  resolved_at: string | null
  resolved_by: string | null
  resolution_note: string | null
  auto_resolved: boolean
}

export interface AlertSummary {
  critical: number
  warning: number
  info: number
  acknowledged: number
  total_active: number
  latest: OpsAlert[]
}

export interface Eligibility {
  truck: Ref
  eligible: boolean
  reasons: string[]
}

export interface TruckDetail extends Truck {
  documents: { doc_type: string; reference_number: string; expires_on: string; days_remaining: number }[]
  loads_completed_30d: number
  avg_turnaround_30d: number | null
}

export interface DriverAssignment {
  id: number
  driver: Ref
  truck: Ref
  assigned_at: string
  released_at: string | null
  is_current: boolean
  assigned_by: string | null
  released_by: string | null
  note: string | null
  source: 'manual' | 'backfill' | 'sample'
}

export interface FleetSummary {
  total: number
  available: number
  loading: number
  in_transit: number
  maintenance: number
  out_of_service: number
  compliance_due: number
  availability_pct: number | null
}

export interface Route {
  id: number
  origin: string
  destination: string
  label: string
  distance_km: number
  expected_duration_minutes: number
  is_active: boolean
}

export interface Bay {
  id: number
  code: string
  name: string
  target_turnaround_minutes: number | null
  effective_target_minutes: number
  is_active: boolean
}

export interface Schedule {
  id: number
  truck: Ref
  driver_name: string | null
  bay: Ref
  scheduled_start: string
  scheduled_end: string
  arrival_at: string | null
  loading_started_at: string | null
  loading_finished_at: string | null
  departed_at: string | null
  status: ScheduleStatus
  notes: string | null
  loading_minutes: number | null
  turnaround_minutes: number | null
  target_minutes: number
  within_target: boolean | null
  is_late: boolean
  late_minutes: number
  dispatch_id: number | null
  load_ref: string | null
}

export interface LoadingOverview {
  date: string
  active_bays: number
  total_bays: number
  scheduled_count: number
  completed_count: number
  avg_loading_minutes: number | null
  avg_loading_minutes_previous_day: number | null
  avg_turnaround_minutes: number | null
  late_count: number
  hourly: { hour: number; scheduled: number; completed: number }[]
  bay_board: {
    bay: Bay
    state: 'in_use' | 'reserved' | 'available' | 'inactive'
    schedule: Schedule | null
    progress_pct: number | null
  }[]
  upcoming: Schedule[]
  late: Schedule[]
  sample_data: boolean
}

export interface Dispatch {
  id: number
  load_ref: string
  schedule_id: number | null
  truck: Ref
  driver_name: string | null
  route: Ref
  dispatched_at: string
  expected_arrival_at: string
  actual_arrival_at: string | null
  status: DispatchStatus
  is_delayed: boolean
  is_overdue: boolean
  delay_minutes: number
  delivery_minutes: number | null
  turnaround_minutes: number | null
  delay_cause: DelayCause | null
}

export interface DispatchOverview {
  date: string
  active: number
  in_transit: number
  delayed_active: number
  delivered_today: number
  delivered_previous_day: number
  on_time_rate_7d: number | null
  on_time_rate_prev_7d: number | null
  delayed_rate_7d: number | null
  avg_delivery_minutes_7d: number | null
  status_breakdown: { status: string; count: number }[]
  hourly: { hour: number; delivered: number; in_transit: number; delayed: number }[]
  alerts: Dispatch[]
  sample_data: boolean
}

export interface KpiValue {
  current: number | null
  previous: number | null
}

export interface DashboardOverview {
  period_start: string
  period_end: string
  previous_period_start: string
  previous_period_end: string
  sample_data: boolean
  turnaround_target_minutes: number
  kpis: {
    loads_processed: KpiValue
    avg_turnaround_minutes: KpiValue
    within_target_pct: KpiValue
    on_time_delivery_pct: KpiValue
    delay_incidents: KpiValue
    bay_utilization_pct: KpiValue
  }
  trend: {
    day: string
    loads_processed: number
    avg_turnaround_minutes: number | null
    on_time_delivery_pct: number | null
  }[]
  dispatch_status: { status: string; count: number }[]
  delayed_dispatches: number
  fleet_status: { status: string; count: number }[]
  fleet_total: number
  open_delay_incidents: number
  recent_dispatches: {
    id: number
    load_ref: string
    truck_registration: string
    route: string
    dispatched_at: string
    expected_arrival_at: string
    actual_arrival_at: string | null
    status: string
    is_delayed: boolean
  }[]
  expiry_alerts: {
    truck_registration: string
    doc_type: string
    expires_on: string
    days_remaining: number
  }[]
}
