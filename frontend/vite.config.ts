import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Split the charting stack (recharts + its d3 deps) into its own chunk
        // so it isn't bundled into the DashboardPage chunk (audit M18). This
        // keeps individual chunks under the size warning and lets the chart
        // code be cached independently of the dashboard's own code.
        manualChunks(id: string) {
          if (
            id.includes('node_modules/recharts') ||
            id.includes('node_modules/d3-') ||
            id.includes('node_modules/victory-vendor') ||
            id.includes('node_modules/internmap')
          ) {
            return 'charts'
          }
          // Observability libs are heavy and only needed when configured.
          if (
            id.includes('node_modules/@sentry') ||
            id.includes('node_modules/posthog-js')
          ) {
            return 'observability'
          }
          // Auth/data SDK.
          if (id.includes('node_modules/@supabase')) {
            return 'supabase'
          }
          return undefined
        },
      },
    },
  },
})
