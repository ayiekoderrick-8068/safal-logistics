import type { Tone } from '../../../lib/statusColors'
import type { EquipmentStatus, ServiceState } from '../../../lib/maintenance'

/** Equipment out of service is a red flag in maintenance (a truck out of service is neutral). */
export const equipmentTone = (s: EquipmentStatus): Tone =>
  s === 'operational' ? 'green' : s === 'under_maintenance' ? 'amber' : 'red'

export const serviceTone = (s: ServiceState): Tone =>
  s === 'overdue' ? 'red' : s === 'due_soon' ? 'amber' : s === 'scheduled' ? 'blue' : 'slate'
