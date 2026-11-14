import { vi } from 'vitest'
import type { ReactNode } from 'react'
import { AppCtx, type Meta } from '../src/lib'

export type Route = (url: string, init?: RequestInit) => { status?: number; body: unknown } | undefined

/** Install a fetch mock that answers by URL; records every call (url, method, headers, body). */
export function mockFetch(route: Route) {
  const calls: { url: string; method: string; headers: Record<string, string>; body?: string }[] = []
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, method: init.method || 'GET', headers: (init.headers || {}) as Record<string, string>, body: init.body as string | undefined })
    const r = route(url, init) ?? { status: 404, body: { detail: `no mock for ${url}` } }
    const status = r.status ?? 200
    return new Response(JSON.stringify(r.body), { status, statusText: status === 200 ? 'OK' : 'ERR', headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fn)
  return calls
}

export const META: Meta = {
  has_data: true, states: ['Punjab', 'Odisha'], districts: [{ id: 'D1', name: 'Ludhiana', state: 'Punjab' }, { id: 'D2', name: 'Puri', state: 'Odisha' }],
  users: [], land_use_classes: [], satellites: ['Terra', 'Aqua', 'Suomi NPP'], auth_mode: 'dev',
}

export function withApp(children: ReactNode, over: Partial<{ role: string; region: string; setRegion: (r: string) => void; meta: Meta | null }> = {}) {
  return (
    <AppCtx.Provider value={{ user: 'analyst', setUser: () => {}, role: over.role ?? 'analyst', region: over.region ?? 'country',
      setRegion: over.setRegion ?? (() => {}), meta: over.meta === undefined ? META : over.meta, reloadMeta: () => {} }}>
      {children}
    </AppCtx.Provider>
  )
}
