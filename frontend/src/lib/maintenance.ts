/** Maintenance workspace types and labels (mirrors backend schemas_maintenance.py). */
import { useApi } from '../hooks/useApi'
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
}

/** The caller's maintenance permissions, from the API (which also enforces them). */
export function useMaintenanceAccess() {
  const { data } = useApi<Access>('/maintenance/access')
  return {
    role: data?.maintenance_role,
    can: (p: MaintenancePermission) => !!data?.permissions.includes(p),
  }
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
