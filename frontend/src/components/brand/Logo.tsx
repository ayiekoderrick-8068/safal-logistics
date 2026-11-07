import clsx from 'clsx'
import compactOnDark from '../../assets/brand/logitrack-compact-on-dark.webp'
import compactOnLight from '../../assets/brand/logitrack-compact-on-light.webp'
import fullOnDark from '../../assets/brand/logitrack-full-on-dark.webp'
import fullOnLight from '../../assets/brand/logitrack-full-on-light.webp'
import icon from '../../assets/brand/logitrack-icon.webp'

/**
 * The official LogiTrack logo, cut from the supplied artwork (docs/brand/logitrack-logo.png,
 * rebuilt with docs/brand/make_brand.py). Never redraw or recolour the truck.
 *
 * - `full`    icon + LogiTrack + Operations Portal: sign-in and workspace pages
 * - `compact` icon + LogiTrack: navigation
 * - `icon`    the cyan truck tile: collapsed navigation (and the favicon)
 *
 * `surface` is the background it sits on: dark surfaces get the white lettering.
 * Size it by height (e.g. `h-12`); the width follows the artwork's own proportions.
 */
const ASSETS = {
  full: { light: fullOnLight, dark: fullOnDark, w: 691, h: 216, alt: 'LogiTrack Operations Portal' },
  compact: { light: compactOnLight, dark: compactOnDark, w: 461, h: 144, alt: 'LogiTrack' },
  icon: { light: icon, dark: icon, w: 192, h: 192, alt: 'LogiTrack' },
} as const

export function Logo({
  variant = 'full',
  surface = 'dark',
  className,
  decorative = false,
}: {
  variant?: keyof typeof ASSETS
  surface?: 'light' | 'dark'
  className?: string
  /** Set when the same name is already announced next to it. */
  decorative?: boolean
}) {
  const a = ASSETS[variant]
  return (
    <img
      src={a[surface]}
      width={a.w}
      height={a.h}
      alt={decorative ? '' : a.alt}
      draggable={false}
      decoding="async"
      className={clsx('block w-auto max-w-none shrink-0 select-none', className)}
    />
  )
}
