import {
  CalendarClock,
  ClipboardList,
  FileText,
  LayoutDashboard,
  Package,
  Settings,
  TriangleAlert,
  Wrench,
} from 'lucide-react'
import type { NavItem, NavSection } from './nav'

/** Maintenance Operations workspace. Routes live under /maintenance. */
export const MAINTENANCE_NAV: NavSection[] = [
  {
    label: 'Maintenance',
    items: [
      {
        to: '/maintenance', label: 'Dashboard', title: 'Maintenance Dashboard', icon: LayoutDashboard,
        description: 'Equipment health, schedules, work orders and breakdowns at a glance.',
      },
      {
        to: '/maintenance/equipment', label: 'Equipment', title: 'Equipment Register', icon: Wrench,
        description: 'Register, locate and track every maintained asset.',
      },
      {
        to: '/maintenance/preventive', label: 'Preventive Maintenance', title: 'Preventive Maintenance',
        icon: CalendarClock,
        description: 'Recurring service plans, due dates and overdue tasks.',
      },
      {
        to: '/maintenance/work-orders', label: 'Work Orders', title: 'Work Orders', icon: ClipboardList,
        description: 'Plan, assign and complete maintenance work.',
      },
      {
        to: '/maintenance/breakdowns', label: 'Breakdown Logs', title: 'Breakdown Logs', icon: TriangleAlert,
        description: 'Record failures, downtime and repairs.',
      },
      {
        to: '/maintenance/spare-parts', label: 'Spare Parts', title: 'Spare Parts Inventory', icon: Package,
        description: 'Stock levels, consumption and reorder alerts.',
      },
      {
        to: '/maintenance/reports', label: 'Reports', title: 'Maintenance Reports', icon: FileText,
        description: 'MTTR, MTBF, PM compliance, availability and exports.',
      },
      {
        to: '/maintenance/settings', label: 'Settings', title: 'Maintenance Settings', icon: Settings,
        description: 'Facilities, categories and maintenance preferences.',
        planned: { milestone: 'Milestone 7', features: ['Facilities, departments and equipment categories'] },
      },
    ],
  },
]

export const ALL_MAINTENANCE_ITEMS: NavItem[] = MAINTENANCE_NAV.flatMap((s) => s.items)
