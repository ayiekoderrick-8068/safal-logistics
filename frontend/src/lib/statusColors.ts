/** Chart colours for operational statuses (green / amber / red / blue convention). */
export const STATUS_COLORS: Record<string, string> = {
  delivered: '#16a34a',
  in_transit: '#f59e0b',
  pending: '#3b82f6',
  cancelled: '#94a3b8',
  available: '#16a34a',
  loading: '#3b82f6',
  maintenance: '#ef4444',
  out_of_service: '#94a3b8',
}

export function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? '#64748b'
}

export type Tone = 'green' | 'amber' | 'red' | 'blue' | 'slate'

const STATUS_TONES: Record<string, Tone> = {
  delivered: 'green',
  available: 'green',
  active: 'green',
  compliant: 'green',
  resolved: 'green',
  in_transit: 'amber',
  investigating: 'amber',
  in_progress: 'amber',
  expiring_soon: 'amber',
  loading: 'blue',
  pending: 'slate',
  scheduled: 'slate',
  cancelled: 'slate',
  out_of_service: 'slate',
  maintenance: 'red',
  delayed: 'red',
  overdue: 'red',
  deactivated: 'red',
}

/** Badge tone for a status value (unknown statuses fall back to neutral slate). */
export function statusTone(status: string): Tone {
  return STATUS_TONES[status] ?? 'slate'
}
