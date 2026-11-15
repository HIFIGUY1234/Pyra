/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Public origin of the persistent PyroScope API (no secrets). Empty = same origin. */
  readonly VITE_API_BASE_URL?: string
  /** Optional raster basemap template ({z}/{x}/{y}); public value, may include a publishable key. */
  readonly VITE_BASEMAP_URL?: string
  readonly VITE_BASEMAP_ATTRIBUTION?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
