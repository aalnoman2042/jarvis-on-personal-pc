/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Overrides where the app looks for the cloud core. See lib/endpoint.ts. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
