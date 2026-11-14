import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { GeoJSON, MapContainer, Rectangle, TileLayer, useMap, useMapEvents } from 'react-leaflet'
import type { GeoJsonObject } from 'geojson'
import { api } from './lib'

export type CellLike = { west?: number; south?: number; east?: number; north?: number; lat?: number; lon?: number }
export type PointLike = { latitude: number; longitude: number }

const canvas = L.canvas({ padding: 0.4 })
export const mapRenderer = canvas
let statesCache: GeoJsonObject | null = null

export function useStates() {
  const [g, setG] = useState<GeoJsonObject | null>(statesCache)
  useEffect(() => { if (!statesCache) api<GeoJsonObject>('/api/geo/states').then((d) => { statesCache = d; setG(d) }).catch(() => undefined) }, [])
  return g
}

export function FitBounds({ bbox }: { bbox?: number[] | null }) {
  const map = useMap()
  const key = bbox ? bbox.join(',') : ''
  useEffect(() => { if (bbox) map.fitBounds([[bbox[1], bbox[0]], [bbox[3], bbox[2]]], { padding: [20, 20], maxZoom: 10 }) }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

/** Two-click rectangle selection (no extra dependency). */
export function BoxDraw({ active, onDone }: { active: boolean; onDone: (bbox: [number, number, number, number]) => void }) {
  const [a, setA] = useState<L.LatLng | null>(null)
  const [b, setB] = useState<L.LatLng | null>(null)
  const map = useMap()
  useEffect(() => { map.getContainer().style.cursor = active ? 'crosshair' : ''; if (!active) { setA(null); setB(null) } }, [active, map])
  useMapEvents({
    click(e) {
      if (!active) return
      if (!a) { setA(e.latlng); setB(e.latlng); return }
      const w = Math.min(a.lng, e.latlng.lng), s = Math.min(a.lat, e.latlng.lat), ea = Math.max(a.lng, e.latlng.lng), n = Math.max(a.lat, e.latlng.lat)
      setA(null); setB(null)
      if (ea - w > 0.01 && n - s > 0.01) onDone([+w.toFixed(3), +s.toFixed(3), +ea.toFixed(3), +n.toFixed(3)])
    },
    mousemove(e) { if (active && a) setB(e.latlng) },
  })
  return a && b ? <Rectangle bounds={[[a.lat, a.lng], [b.lat, b.lng]]} pathOptions={{ color: '#f97316', weight: 1.5, dashArray: '4 3', fillOpacity: 0.08 }} /> : null
}

export function BaseMap({ children, height = 560, bbox, showStates = true, className = '' }: { children?: ReactNode; height?: number | string; bbox?: number[] | null; showStates?: boolean; className?: string }) {
  const states = useStates()
  const style = useMemo(() => ({ color: '#64748b', weight: 0.8, fill: false, interactive: false }), [])
  return (
    <MapContainer center={[22.5, 80]} zoom={5} minZoom={3} preferCanvas style={{ height, width: '100%' }} className={`rounded-b-lg ${className}`} worldCopyJump>
      <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" attribution='&copy; OpenStreetMap contributors &copy; CARTO | Boundaries: geoBoundaries' subdomains="abcd" maxZoom={12} />
      {showStates && states && <GeoJSON data={states} style={style} interactive={false} />}
      <FitBounds bbox={bbox} />
      {children}
    </MapContainer>
  )
}

/** Grid cells as rectangles on the shared canvas renderer. `cells` need west/south/east/north or lat/lon (0.25 deg). */
export function CellLayer<T extends CellLike = CellLike>({ cells, colorOf, opacityOf, onClick, popup, stroke }: {
  cells: readonly T[]; colorOf: (c: T) => string; opacityOf?: (c: T) => number; onClick?: (c: T) => void; popup?: (c: T) => string; stroke?: (c: T) => string | undefined
}) {
  const map = useMap()
  useEffect(() => {
    const group = L.layerGroup()
    for (const c of cells) {
      const lon = c.lon ?? 0, lat = c.lat ?? 0
      const w = c.west ?? lon - 0.125, s = c.south ?? lat - 0.125, e = c.east ?? lon + 0.125, n = c.north ?? lat + 0.125
      const sc = stroke?.(c)
      const r = L.rectangle([[s, w], [n, e]], { renderer: canvas, stroke: !!sc, color: sc, weight: sc ? 1.5 : 0, fillColor: colorOf(c), fillOpacity: opacityOf ? opacityOf(c) : 0.6 })
      if (popup) r.bindPopup(() => popup(c), { maxWidth: 300 })
      if (onClick) r.on('click', () => onClick(c))
      group.addLayer(r)
    }
    group.addTo(map)
    return () => { group.remove() }
  }, [cells, map]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

/** Point markers with a distinct shape per instrument (circle = VIIRS, square = MODIS) so identity is not colour-only. */
export function PointLayer<T extends PointLike = PointLike>({ points, colorOf, isSquare, popup, onClick, radius = 3.5 }: { points: readonly T[]; colorOf: (p: T) => string; isSquare: (p: T) => boolean; popup?: (p: T) => string; onClick?: (p: T) => void; radius?: number }) {
  const map = useMap()
  useEffect(() => {
    const group = L.layerGroup()
    for (const p of points) {
      const col = colorOf(p)
      let m: L.Rectangle | L.CircleMarker
      if (isSquare(p)) {
        const d = 0.012
        m = L.rectangle([[p.latitude - d, p.longitude - d], [p.latitude + d, p.longitude + d]], { renderer: canvas, color: col, weight: 1.5, fillColor: col, fillOpacity: 0.55 })
      } else {
        m = L.circleMarker([p.latitude, p.longitude], { renderer: canvas, radius, color: '#0B0F19', weight: 0.6, fillColor: col, fillOpacity: 0.85 })
      }
      if (popup) m.bindPopup(() => popup(p), { maxWidth: 320 })
      if (onClick) m.on('click', () => onClick(p))
      group.addLayer(m)
    }
    group.addTo(map)
    return () => { group.remove() }
  }, [points, map]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

export const Swatch = ({ color, label, square }: { color: string; label: string; square?: boolean }) => (
  <span className="inline-flex items-center gap-1.5 text-xs text-slate-300"><i className={`inline-block h-2.5 w-2.5 ${square ? '' : 'rounded-full'}`} style={{ background: color }} />{label}</span>
)

/** Sequential single-hue ramp (light = low, saturated = high) for magnitude layers. */
export function seq(v: number, max: number) {
  const t = Math.max(0, Math.min(1, Math.log1p(v) / Math.log1p(Math.max(max, 1))))
  const stops = [[254, 237, 222], [253, 190, 133], [253, 141, 60], [230, 85, 13], [166, 54, 3]]
  const i = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)))
  const f = t * (stops.length - 1) - i
  const c = stops[i].map((a, k) => Math.round(a + (stops[i + 1][k] - a) * f))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}
