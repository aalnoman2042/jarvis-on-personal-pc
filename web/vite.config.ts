import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The HUD is served by the cloud core in production, so it lives at the root
// and talks to same-origin endpoints — no CORS, and the token never has to
// cross an origin boundary. In development, Vite proxies to a local core so the
// exact same relative URLs work from `npm run dev`.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // React barely changes; the HUD changes constantly. Splitting them means a
    // deploy re-downloads a few kilobytes of app rather than the whole bundle,
    // which is most of what makes an update feel instant on mobile data.
    rollupOptions: {
      output: {
        manualChunks: { react: ["react", "react-dom"] },
      },
    },
    // The default warns at 500kB and the app is well under it; raising it stops
    // a meaningless warning from hiding a real one.
    chunkSizeWarningLimit: 700,
  },
  server: {
    port: 5173,
    proxy: {
      // Every endpoint, because a missing one here fails only in development
      // and only for whoever added it — /me, /agenda, /mail and /brief were all
      // written after this list and none of them were reachable from `npm run
      // dev`.
      "/chat": "http://127.0.0.1:8000",
      "/login": "http://127.0.0.1:8000",
      "/status": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/devices": "http://127.0.0.1:8000",
      "/me": "http://127.0.0.1:8000",
      "/facts": "http://127.0.0.1:8000",
      "/agenda": "http://127.0.0.1:8000",
      "/brief": "http://127.0.0.1:8000",
      "/mail": "http://127.0.0.1:8000",
      "/listen": "http://127.0.0.1:8000",
      "/look": "http://127.0.0.1:8000",
      "/tick": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
