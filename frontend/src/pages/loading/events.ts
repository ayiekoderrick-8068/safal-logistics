import type { ScheduleStatus } from '../../lib/types'

export type ScheduleEvent = 'arrived' | 'loading_started' | 'loading_finished'

export const EVENT_LABELS: Record<ScheduleEvent, { action: string; field: string }> = {
  arrived: { action: 'Record arrival', field: 'Arrival time' },
  loading_started: { action: 'Start loading', field: 'Loading start time' },
  loading_finished: { action: 'Finish loading', field: 'Loading finish time' },
}

/** The next timestamp to record for a load in the given status (null when none). */
export function nextEvent(status: ScheduleStatus): ScheduleEvent | null {
  switch (status) {
    case 'scheduled':
      return 'arrived'
    case 'arrived':
      return 'loading_started'
    case 'loading':
      return 'loading_finished'
    default:
      return null
  }
}
