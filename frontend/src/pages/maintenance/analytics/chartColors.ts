/**
 * Validated with the dataviz palette validator against the light card surface:
 *   SERIES  #0891b2                     -> all checks pass (single-series magnitude)
 *   STATUS  #15803d / #f59e0b / #b91c1c  -> all checks pass; amber is below 3:1 contrast,
 *           so wherever it is used the value is also printed (legend with counts) and a
 *           table view exists. Status colours mean equipment state only - never a series.
 */
export const SERIES = '#0891b2'
export const STATUS = { good: '#15803d', warning: '#f59e0b', critical: '#b91c1c' } as const
export const GRID = '#e3eef3'
export const MUTED = '#4a6272'
