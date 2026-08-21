/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_USE_MOCK?: string
  readonly VITE_RAW_DOWNLOAD_ENABLED?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
