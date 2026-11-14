import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } } },
  build: {
    rollupOptions: {
      output: {
        // keep large third-party libraries in their own cacheable chunks
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (/[\\/](react|react-dom|react-router|react-router-dom|scheduler)[\\/]/.test(id)) return 'react'
          if (/[\\/](recharts|d3-[a-z-]+|victory-vendor)[\\/]/.test(id)) return 'charts'
          if (/[\\/](leaflet|react-leaflet|@react-leaflet)[\\/]/.test(id)) return 'map'
          return undefined
        },
      },
    },
  },
})
