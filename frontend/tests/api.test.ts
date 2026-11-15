import { describe, expect, it, vi } from 'vitest'
import { api, ApiError, download, getAuthToken, setAuthToken, setCredential, SESSION_EXPIRED_EVENT } from '../src/lib'
import { mockFetch } from './helpers'

describe('api client', () => {
  it('sends exactly one credential: none, the demo persona header, or the bearer token', async () => {
    const calls = mockFetch(() => ({ body: { ok: true } }))
    setCredential({ kind: 'none' })
    await api('/api/meta')
    expect(calls[0].headers['X-User']).toBeUndefined()          // no silent persona fallback
    expect(calls[0].headers.Authorization).toBeUndefined()
    setCredential({ kind: 'persona', username: 'forest.officer' })
    await api('/api/meta')
    expect(calls[1].headers['X-User']).toBe('forest.officer')
    expect(calls[1].headers.Authorization).toBeUndefined()
    setAuthToken('tok123')
    await api('/api/meta')
    expect(calls[2].headers.Authorization).toBe('Bearer tok123')
    expect(calls[2].headers['X-User']).toBeUndefined()
    setAuthToken(null)
  })

  it('raises ApiError carrying status and Retry-After', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'rate limit exceeded' }), { status: 429, headers: { 'Retry-After': '7' } })))
    const e = await api('/api/auth/login', { body: {} }).catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(429)
    expect(e.retryAfter).toBe(7)
  })

  it('sends JSON bodies as POST and drops an expired session on 401', async () => {
    const calls = mockFetch((url) => (url === '/api/alerts' ? { status: 401, body: { detail: 'session expired' } } : { body: {} }))
    const expired = vi.fn()
    window.addEventListener(SESSION_EXPIRED_EVENT, expired)
    setAuthToken('old')
    await expect(api('/api/alerts', { body: { a: 1 } })).rejects.toThrow('session expired')
    expect(calls[0].method).toBe('POST')
    expect(calls[0].headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(calls[0].body as string)).toEqual({ a: 1 })
    expect(getAuthToken()).toBeNull()
    expect(sessionStorage.getItem('pyro_token')).toBeNull()
    expect(expired).toHaveBeenCalledOnce()
    window.removeEventListener(SESSION_EXPIRED_EVENT, expired)
  })

  it('keeps the token on 403 (authenticated but not permitted)', async () => {
    mockFetch(() => ({ status: 403, body: { detail: "role 'analyst' may not perform this action" } }))
    setAuthToken('good')
    await expect(api('/api/system/config')).rejects.toMatchObject({ status: 403 })
    expect(getAuthToken()).toBe('good')
    setAuthToken(null)
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
