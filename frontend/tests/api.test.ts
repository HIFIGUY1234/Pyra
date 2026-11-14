import { describe, expect, it, vi } from 'vitest'
import { api, download, getAuthToken, setApiUser, setAuthToken } from '../src/lib'
import { mockFetch } from './helpers'

describe('api client', () => {
  it('uses the dev persona header without a session and the bearer token with one', async () => {
    const calls = mockFetch(() => ({ body: { ok: true } }))
    setAuthToken(null)
    setApiUser('forest.officer')
    await api('/api/meta')
    expect(calls[0].headers['X-User']).toBe('forest.officer')
    expect(calls[0].headers.Authorization).toBeUndefined()
    setAuthToken('tok123')
    await api('/api/meta')
    expect(calls[1].headers.Authorization).toBe('Bearer tok123')
    expect(calls[1].headers['X-User']).toBeUndefined()
    setAuthToken(null)
  })

  it('sends JSON bodies as POST and drops an expired session on 401', async () => {
    const calls = mockFetch((url) => (url === '/api/alerts' ? { status: 401, body: { detail: 'session expired' } } : { body: {} }))
    setAuthToken('old')
    await expect(api('/api/alerts', { body: { a: 1 } })).rejects.toThrow('session expired')
    expect(calls[0].method).toBe('POST')
    expect(calls[0].headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(calls[0].body as string)).toEqual({ a: 1 })
    expect(getAuthToken()).toBeNull()
    expect(sessionStorage.getItem('pyro_token')).toBeNull()
  })

  it('turns FastAPI validation errors into a readable message', async () => {
    mockFetch(() => ({ status: 422, body: { detail: [{ loc: ['query', 'stage'], msg: 'String should match pattern' }] } }))
    await expect(api('/api/validation/model-selection?stage=x')).rejects.toThrow('stage: String should match pattern')
  })
})

describe('download', () => {
  it('fetches with auth and saves under the requested file name', async () => {
    mockFetch(() => ({ body: { x: 1 } }))
    const create = vi.fn(() => 'blob:1')
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe('report.csv')
      expect(this.href).toBe('blob:1')
    })
    await download('/api/reports/csv', 'report.csv')
    expect(click).toHaveBeenCalledOnce()
  })

  it('raises instead of saving an error page', async () => {
    mockFetch(() => ({ status: 403, body: { detail: 'forbidden' } }))
    await expect(download('/api/reports/csv', 'x.csv')).rejects.toThrow('403')
  })
})
