import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Local dev only: forward API calls to the FastAPI service (Team F).
    // In production the client and API share an origin (or F fronts it), so
    // the app always fetches relative /api/* paths.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
