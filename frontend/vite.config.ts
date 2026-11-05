import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'
import { defineConfig } from 'vitest/config'

// Dedicated ports so LogiTrack does not collide with other local Vite projects.
const apiTarget = process.env.LOGITRACK_API_URL ?? 'http://127.0.0.1:8090'
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string }

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  // Pre-bundle deps used only by lazy routes, so the dev server doesn't re-optimise and
  // force a full page reload the first time a dashboard is opened.
  optimizeDeps: {
    include: ['recharts', 'react-hook-form', '@hookform/resolvers/zod', 'zod', 'lucide-react', 'clsx'],
  },
  server: {
    port: 5190,
    strictPort: true,
    // Same-origin proxy so the httpOnly SameSite=Strict session cookie just works.
    proxy: { '/api': { target: apiTarget, changeOrigin: false } },
  },
  preview: {
    port: 4190,
    proxy: { '/api': { target: apiTarget, changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
