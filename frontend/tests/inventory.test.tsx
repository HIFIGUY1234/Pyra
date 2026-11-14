import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { InventoryCard } from '../src/completion'
import { mockFetch, withApp } from './helpers'

const INV = {
  generated_at: '2026-11-14T00:00:00Z',
  archives: [
    { file: 'DL_FIRE_M-C61_848456.zip', status: 'valid', integrity: 'zip_crc_ok', bytes: 11909796, instrument: 'MODIS', collection: 'Collection 6.1', sha256: '3491e9398b7a8629abcdef', members: [{ name: 'fire_archive_M-C61_848456.csv', kind: 'archive', bytes: 53.2e6 }] },
    { file: 'DL_FIRE_X.zip', status: 'lfs_pointer', integrity: 'not_downloaded', bytes: 133, expected_sha256: 'ffff00001111', message: 'Git LFS pointer, archive not downloaded.' },
  ],
  satellites: {
    'NOAA-21': { status: 'complete_from_firms_start', expected: { firms_start: '2024-01-17' }, loaded: { rows: 2166009, archive: { first: '2023-03-01', last: '2026-07-31' }, nrt: { first: '2026-08-01', last: '2026-10-31' } },
      pre_operational_records: { first: '2023-03-01', note: 'pre-operational' }, gaps: { missing_days: 0, missing_periods: [] } },
  },
  registry: { fire_archive_M: { kind: 'archive', rows_kept: 683359, quality_status: 'good', quality: { dropped_invalid_coordinates: 0, dropped_invalid_timestamp: 0, duplicates_removed: 0 },
    collection: { row_versions: [{ version: '6.03', status: 'undocumented', meaning: 'not defined' }] } } },
  capabilities: { viirs_750m: 'unavailable' }, missing: [], viirs_750m: { facts: ['750 m not in FIRMS.'], how_to_add: 'Use LAADS.' },
}

describe('dataset inventory', () => {
  it('shows integrity, collection, checksum, pointer stubs, undocumented versions and pre-operational records', async () => {
    mockFetch((url) => (url.startsWith('/api/data/inventory') ? { body: INV } : undefined))
    render(withApp(<InventoryCard />))
    expect(await screen.findByText('DL_FIRE_M-C61_848456.zip')).toBeInTheDocument()
    expect(screen.getByText('MODIS Collection 6.1')).toBeInTheDocument()
    expect(screen.getByText('3491e9398b7a')).toBeInTheDocument()
    expect(screen.getByText(/Lfs Pointer \(not downloaded\)/)).toBeInTheDocument()      // a pointer is never shown as a valid zip
    expect(screen.getByText('6.03 (undocumented)')).toHaveClass('text-amber-300')
    expect(screen.getByText(/pre-operational records from 2023-03-01/)).toBeInTheDocument()
    expect(screen.queryByText(/Recover Git LFS archives/)).toBeNull()                    // analysts cannot trigger recovery
  })

  it('lets an administrator recover LFS archives and reports the per-file outcome', async () => {
    const calls = mockFetch((url) => (url === '/api/data/recover-lfs' ? { body: { results: [{ file: 'DL_FIRE_X.zip', status: 'checksum_mismatch' }] } }
      : url.startsWith('/api/data/inventory') ? { body: INV } : undefined))
    const u = userEvent.setup()
    render(withApp(<InventoryCard />, { role: 'admin' }))
    await u.click(await screen.findByRole('button', { name: /Recover Git LFS archives/ }))
    expect(await screen.findByText('DL_FIRE_X.zip: checksum_mismatch')).toBeInTheDocument()
    expect(calls.some((c) => c.url === '/api/data/recover-lfs' && c.method === 'POST')).toBe(true)
    expect(calls.some((c) => c.url === '/api/data/inventory?refresh=true')).toBe(true)
  })
})
