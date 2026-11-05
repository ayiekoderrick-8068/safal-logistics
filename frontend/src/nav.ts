import {
  Activity,
  BarChart3,
  ClipboardList,
  FileText,
  LayoutDashboard,
  Megaphone,
  Send,
  Settings,
  ShieldCheck,
  Timer,
  Truck,
  Users,
  Wallet,
  Warehouse,
  type LucideIcon,
} from 'lucide-react'
import type { Role } from './lib/types'

export interface PlannedModule {
  milestone: string
  features: string[]
}

export interface NavItem {
  to: string
  label: string
  title: string
  description: string
  icon: LucideIcon
  roles?: Role[]
  /** Present while the module is not yet built: the page explains what is coming. */
  planned?: PlannedModule
}

export interface NavSection {
  label: string
  items: NavItem[]
}

export const NAV: NavSection[] = [
  {
    label: 'Dashboard',
    items: [
      {
        to: '/', label: 'Overview', title: 'Operations Overview', icon: LayoutDashboard,
        description: 'Loading, dispatch and fleet performance at a glance.',
      },
      {
        to: '/reports', label: 'Reports', title: 'Reports & Export', icon: FileText,
        description: 'Generate, analyse and export operational reports.',
        planned: {
          milestone: 'Milestone 6',
          features: [
            'Filter by date, vehicle, route, bay and status',
            'CSV export generated from database records',
            'PDF report generation',
            'Quick reports: loading performance, dispatch summary, delay analysis',
          ],
        },
      },
    ],
  },
  {
    label: 'Operations',
    items: [
      {
        to: '/fleet', label: 'Fleet & Trucks', title: 'Fleet Management', icon: Truck,
        description: 'Register trucks, assign drivers and track availability.',
      },
      {
        to: '/loading-bays', label: 'Loading Bays', title: 'Loading Bays & Scheduling', icon: Warehouse,
        description: 'Schedule loading and record bay timestamps.',
      },
      {
        to: '/dispatch', label: 'Dispatch', title: 'Dispatch Management', icon: Send,
        description: 'Dispatch trucks, track deliveries and flag delays.',
      },
      {
        to: '/tasks', label: 'Tasks', title: 'Tasks', icon: ClipboardList,
        description: 'Operational task assignments.',
        planned: { milestone: 'Backlog', features: ['Assign and track operational tasks per shift'] },
      },
    ],
  },
  {
    label: 'Analytics',
    items: [
      {
        to: '/turnaround', label: 'Turnaround Analytics', title: 'Turnaround-Time Analytics', icon: BarChart3,
        description: 'Measure loading turnaround and identify delay causes.',
      },
      {
        to: '/delays', label: 'Delay Reports', title: 'Delay Reports', icon: Timer,
        description: 'Log and investigate loading and dispatch delays.',
      },
    ],
  },
  {
    label: 'Management',
    items: [
      {
        to: '/compliance', label: 'Compliance', title: 'Compliance Records', icon: ShieldCheck,
        description: 'Vehicle documents, inspections and renewals.',
      },
      {
        to: '/finance', label: 'Finance', title: 'Finance', icon: Wallet,
        description: 'Trip costs and billing.',
        planned: { milestone: 'Backlog', features: ['Trip cost tracking', 'Fuel and maintenance spend'] },
      },
      {
        to: '/announcements', label: 'Announcements', title: 'Announcements', icon: Megaphone,
        description: 'Operational notices for staff.',
        planned: { milestone: 'Backlog', features: ['Post notices to operations staff'] },
      },
    ],
  },
  {
    label: 'System',
    items: [
      {
        to: '/users', label: 'User Management', title: 'User Management', icon: Users, roles: ['admin'],
        description: 'Manage system users, roles and access permissions.',
        planned: {
          milestone: 'Milestone 5',
          features: [
            'Create, edit, activate and deactivate users',
            'Administrator, Operations, Fleet Manager, Compliance and Viewer roles',
            'Role-based permissions (already enforced by the API)',
          ],
        },
      },
      {
        to: '/activity-log', label: 'Activity Log', title: 'Activity Log', icon: Activity, roles: ['admin'],
        description: 'Audit trail of important changes.',
        planned: {
          milestone: 'Milestone 5',
          features: ['Browse audit events (sign-ins and record changes are already being recorded)'],
        },
      },
      {
        to: '/settings', label: 'Settings', title: 'System Settings', icon: Settings, roles: ['admin'],
        description: 'Targets, security and system preferences.',
        planned: {
          milestone: 'Milestone 5',
          features: ['Configure turnaround targets', 'Password and session policy'],
        },
      },
    ],
  },
]

export const ALL_NAV_ITEMS = NAV.flatMap((s) => s.items)
