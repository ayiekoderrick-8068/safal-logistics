import { z } from 'zod'

/** Same policy as the server (security.validate_password); the server remains authoritative. */
export const passwordRule = z
  .string()
  .min(8, 'Use at least 8 characters')
  .max(72, 'Use at most 72 characters')
  .refine((v) => /[A-Za-z]/.test(v) && /\d/.test(v), 'Include letters and numbers')
  .refine((v) => /[^A-Za-z0-9]/.test(v), 'Include at least one symbol')

/** Random temporary password that satisfies the policy (letters, digits and a symbol). */
export function generatePassword(): string {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
  const bytes = crypto.getRandomValues(new Uint32Array(12))
  const body = Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('')
  return `${body.slice(0, 6)}-${body.slice(6)}-${(bytes[0] % 90) + 10}!`
}
