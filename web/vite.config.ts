import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The HUD is served by the cloud core in production, so it lives at the root
// and talks to same-origin endpoints — no CORS, and the token never has to
// cross an origin boundary. In development, Vite proxies to a local core so the
// exact same relative URLs work from `npm run dev`.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      "/chat": "http://127.0.0.1:8000",
      "/pair": "http://127.0.0.1:8000",
      "/status": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/devices": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
