import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
  },
  test: {
    // The components render DOM, so they need one.
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    // No globals: every test imports what it uses, so the file says where
    // describe and expect come from.
    globals: false,
    css: false,
  },
})
