export type Role = 'admin' | 'operations' | 'fleet_manager' | 'compliance' | 'viewer'

export interface User {
  id: number
  email: string
  username: string
  full_name: string
  role: Role
  status: 'active' | 'pending' | 'deactivated'
  last_login_at: string | null
}

export interface Meta {
  app: string
  version: string
  timezone: string
  turnaround_target_minutes: number
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
