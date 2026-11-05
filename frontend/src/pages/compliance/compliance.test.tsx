import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ComplianceDocument } from '../../lib/types'
import { DocumentFormModal } from './DocumentFormModal'
import { validateFile } from './files'

const CURRENT: ComplianceDocument = {
  id: 9, truck: { id: 3, label: 'KDB 118M' }, doc_type: 'inspection', reference_number: 'INSP-1',
  issuing_authority: 'NTSA', issued_on: '2025-11-01', expires_on: '2026-11-25', days_remaining: 20,
  state: 'expiring', is_current: true, superseded_at: null, renewed_from_id: null, file: null, notes: null,
  created_at: '2025-11-01T08:00:00Z',
}

describe('file pre-validation', () => {
  it('accepts PDF/PNG/JPEG under 10 MB only', () => {
    expect(validateFile(new File(['x'], 'cert.pdf'))).toBeUndefined()
    expect(validateFile(new File(['x'], 'cert.JPEG'))).toBeUndefined()
    expect(validateFile(new File(['x'], 'cert.docx'))).toBe('Attach a PDF, PNG or JPEG file')
    const big = new File(['x'], 'big.pdf')
    Object.defineProperty(big, 'size', { value: 11 * 1024 * 1024 })
    expect(validateFile(big)).toBe('The file must be 10 MB or smaller')
  })
})

describe('renewal form', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...CURRENT, id: 10, renewed_from_id: 9 }), { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)
  })

  it('keeps type and truck fixed, prefills the authority and validates dates', async () => {
    const onSaved = vi.fn()
    render(<MemoryRouter><DocumentFormModal mode="renew" previous={CURRENT} onClose={() => {}} onSaved={onSaved} /></MemoryRouter>)
    expect(screen.getByLabelText('Document type')).toBeDisabled()
    expect(screen.getByLabelText('Issuing authority (optional)')).toHaveValue('NTSA')
    expect(screen.getByText(/kept as history/)).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Document reference'), 'INSP-2')
    fireEvent.change(screen.getByLabelText('Issue date'), { target: { value: '2026-11-05' } })
    fireEvent.change(screen.getByLabelText('Expiry date'), { target: { value: '2026-11-01' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save renewal' }))
    expect(await screen.findByText('Expiry must be after the issue date')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('Expiry date'), { target: { value: '2027-11-04' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save renewal' }))
    expect(onSaved).toHaveBeenCalled()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/compliance/documents/9/renew')
    expect(JSON.parse(init.body)).toMatchObject({ reference_number: 'INSP-2', issued_on: '2026-11-05', expires_on: '2027-11-04', issuing_authority: 'NTSA' })
  })
})
