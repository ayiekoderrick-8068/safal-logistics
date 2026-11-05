import { api } from '../../lib/api'
import type { ComplianceDocument } from '../../lib/types'

export const ACCEPTED_FILES = '.pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg'
const MAX_BYTES = 10 * 1024 * 1024

/** Client-side pre-check; the server re-validates type (magic bytes) and size. */
export function validateFile(file: File | null): string | undefined {
  if (!file) return undefined
  if (!/\.(pdf|png|jpe?g)$/i.test(file.name)) return 'Attach a PDF, PNG or JPEG file'
  if (file.size > MAX_BYTES) return 'The file must be 10 MB or smaller'
  return undefined
}

export async function uploadDocumentFile(documentId: number, file: File): Promise<ComplianceDocument> {
  const form = new FormData()
  form.append('file', file)
  return api<ComplianceDocument>(`/compliance/documents/${documentId}/file`, { method: 'PUT', body: form })
}
