import { z } from 'zod'

export const truckSchema = z.object({
  registration: z
    .string()
    .trim()
    .min(3, 'Enter the registration number')
    .max(20)
    .regex(/^[A-Za-z0-9][A-Za-z0-9 -]{1,18}[A-Za-z0-9]$/, 'Letters, digits and spaces only, e.g. KDA 123A'),
  make: z.string().trim().max(60),
  model: z.string().trim().max(60),
  capacity_tonnes: z
    .string()
    .trim()
    .min(1, 'Enter the capacity')
    .refine((v) => Number(v) > 0 && Number(v) <= 100, 'Capacity must be between 0 and 100 tonnes'),
  driver_id: z.string(),
  status: z.enum(['available', 'maintenance', 'out_of_service', 'loading', 'in_transit']),
})

export type TruckValues = z.infer<typeof truckSchema>
