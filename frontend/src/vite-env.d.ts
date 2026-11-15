/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Public origin of the persistent PyroScope API (no secrets). Empty = same origin. */
  readonly VITE_API_BASE_URL?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
