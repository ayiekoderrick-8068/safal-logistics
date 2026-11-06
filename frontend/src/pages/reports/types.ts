export interface Applied {
  filters: Record<string, string | null>
  applied: { label: string; value: string }[]
  timezone: string
}

export interface Stats {
  count: number
  avg: number | null
  median: number | null
  min: number | null
  max: number | null
}

export interface Summary extends Applied {
  kpis: {
    loads_processed: number
    completed_dispatches: number
    pending_deliveries: number
    on_time_pct: number | null
    avg_turnaround_minutes: number | null
    delayed_loads: number
    bay_utilization_pct: number | null
    compliance_interruptions: number
    delay_incidents: number
  }
  dispatch_outcomes: { status: string; count: number }[]
  trend: { day: string; loads: number; avg_turnaround_minutes: number | null; on_time_pct: number | null; delays: number }[]
  target_minutes: number
}

export interface GroupStats {
  id: number | null
  label: string
  loads: number
  avg_minutes: number | null
  median_minutes: number | null
  min_minutes: number | null
  max_minutes: number | null
  avg_loading_minutes: number | null
  within_target_pct: number | null
}

export interface Turnaround extends Applied {
  target_minutes: number
  completed_loads: number
  ongoing_loads: number
  within_target_pct: number | null
  components: Record<'waiting' | 'loading' | 'post_load' | 'turnaround' | 'delivery', Stats>
  daily: { period: string; loads: number; avg_minutes: number | null; median_minutes: number | null; min_minutes: number | null; max_minutes: number | null }[]
  weekly: Turnaround['daily']
  by_truck: GroupStats[]
  by_route: GroupStats[]
  by_bay: GroupStats[]
}

export interface DelayGroup { id: number | null; label: string; count: number; impact_minutes: number; open: number }

export interface IncidentRow {
  id: number
  started_at: string
  resolved_at: string | null
  status: string
  cause: string
  truck: string | null
  bay: string | null
  route: string | null
  load_ref: string | null
  impact_minutes: number
  duration_minutes: number
  ongoing: boolean
  assigned_to: string | null
  description: string | null
}

export interface Delays extends Applied {
  total: number
  open: number
  resolved: number
  impact_minutes: number
  avg_impact_minutes: number | null
  avg_resolution_minutes: number | null
  by_cause: { cause: string; count: number; impact_minutes: number; avg_impact_minutes: number | null; avg_resolution_minutes: number | null }[]
  by_bay: DelayGroup[]
  by_route: DelayGroup[]
  by_truck: DelayGroup[]
  daily: { period: string; count: number; impact_minutes: number }[]
  weekly: Delays['daily']
  repeat_patterns: { truck: string; cause: string; count: number }[]
  recent: IncidentRow[]
}

export interface Bays extends Applied {
  hours_per_day: number
  days: number
  bays: {
    id: number
    code: string
    name: string
    target_minutes: number
    loads: number
    completed_within_target: number
    delayed: number
    avg_loading_minutes: number | null
    avg_waiting_minutes: number | null
    avg_turnaround_minutes: number | null
    throughput_per_day: number
    throughput_per_operating_hour: number
    occupied_hours: number
    utilization_pct: number | null
    peak_hour: string | null
  }[]
  peak_hours: { hour: number; arrivals: number }[]
}

export interface DispatchPerf extends Applied {
  grace_minutes: number
  scheduled_loads: number
  dispatched: number
  dispatched_trucks: number
  completed: number
  pending: number
  cancelled: number
  on_time: number
  late: number
  on_time_pct: number | null
  avg_delivery_minutes: number | null
  avg_planned_minutes: number | null
  delay_distribution: { bucket: string; count: number }[]
  by_route: {
    id: number; label: string; dispatches: number; completed: number; pending: number; on_time_pct: number | null
    avg_planned_minutes: number | null; avg_actual_minutes: number | null; avg_lateness_minutes: number | null
  }[]
}

export type ExportFormat = 'pdf' | 'csv' | 'xlsx'

export interface CatalogueItem { key: string; title: string; formats: ExportFormat[] }

export interface ReportRun {
  id: number
  report_type: string
  title: string
  format: ExportFormat
  status: 'success' | 'failed'
  filters: Record<string, string | null>
  row_count: number | null
  requested_by: string | null
  created_at: string
}

export interface RecordsPage {
  type: string
  total: number
  limit: number
  offset: number
  items: Record<string, unknown>[]
}
