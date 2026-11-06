import type { Tone } from '../../../lib/statusColors'
import type { EquipmentStatus, Priority, ServiceState, Severity, TaskState, WorkOrderStatus } from '../../../lib/maintenance'

export const woTone = (s: WorkOrderStatus): Tone =>
  s === 'completed' ? 'green' : s === 'in_progress' ? 'blue' : s === 'awaiting_parts' ? 'amber' : s === 'cancelled' ? 'slate' : s === 'assigned' ? 'blue' : 'amber'
export const priorityTone = (p: Priority | Severity): Tone =>
  p === 'critical' ? 'red' : p === 'high' || p === 'major' ? 'amber' : p === 'medium' ? 'blue' : 'slate'

export const taskTone = (s: TaskState): Tone =>
  s === 'overdue' ? 'red' : s === 'due_today' ? 'amber' : s === 'completed' ? 'green' : s === 'upcoming' ? 'blue' : 'slate'

/** Equipment out of service is a red flag in maintenance (a truck out of service is neutral). */
export const equipmentTone = (s: EquipmentStatus): Tone =>
  s === 'operational' ? 'green' : s === 'under_maintenance' ? 'amber' : 'red'

export const serviceTone = (s: ServiceState): Tone =>
  s === 'overdue' ? 'red' : s === 'due_soon' ? 'amber' : s === 'scheduled' ? 'blue' : 'slate'
