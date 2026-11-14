import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RegionPicker, regionName } from '../src/lib'
import { META, withApp } from './helpers'

describe('region filter', () => {
  it('switches country -> state -> district and reports the chosen region id', async () => {
    const setRegion = vi.fn()
    const u = userEvent.setup()
    const { rerender } = render(withApp(<RegionPicker />, { setRegion }))
    await u.selectOptions(screen.getByLabelText('Area type'), 'state')
    expect(setRegion).toHaveBeenLastCalledWith('state:Punjab')
    rerender(withApp(<RegionPicker />, { setRegion, region: 'state:Punjab' }))
    await u.selectOptions(screen.getByLabelText('State'), 'Odisha')
    expect(setRegion).toHaveBeenLastCalledWith('state:Odisha')
    rerender(withApp(<RegionPicker />, { setRegion, region: 'district:D1' }))
    await u.selectOptions(screen.getByLabelText('State of district'), 'Odisha')
    expect(setRegion).toHaveBeenLastCalledWith('district:D2')
  })

  it('refuses an invalid custom bounding box and applies a valid one', async () => {
    const setRegion = vi.fn()
    const u = userEvent.setup()
    render(withApp(<RegionPicker />, { setRegion, region: 'bbox:74,29,77,32' }))
    const box = screen.getByLabelText('West,South,East,North')
    const apply = screen.getByRole('button', { name: 'Apply' })
    await u.clear(box)
    await u.type(box, '77,29,74,32')        // east < west
    expect(apply).toBeDisabled()
    await u.clear(box)
    await u.type(box, '75,30,76,31')
    expect(apply).toBeEnabled()
    await u.click(apply)
    expect(setRegion).toHaveBeenCalledWith('bbox:75,30,76,31')
  })

  it('names regions for headers and reports', () => {
    expect(regionName('country', META)).toBe('India')
    expect(regionName('district:D1', META)).toBe('Ludhiana, Punjab')
    expect(regionName('bbox:1,2,3,4', META)).toBe('Custom area (1,2,3,4)')
  })
})
