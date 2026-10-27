/// <reference types="vitest/config" />
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'

import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

/**
 * Writes a `.gz` twin next to every compressible asset at build time so NGINX
 * can serve it with `gzip_static on` — max compression, zero per-request CPU.
 * (CloudFront compresses on its own, so deploy.sh skips the .gz files.)
 */
function precompress(): Plugin {
  let outDir = 'dist'
  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((name) => {
      const path = join(dir, name)
      return statSync(path).isDirectory() ? walk(path) : [path]
    })
  return {
    name: 'precompress-gzip',
    apply: 'build',
    configResolved(config) {
      outDir = config.build.outDir
    },
    closeBundle() {
      for (const file of walk(outDir)) {
        if (!/\.(js|css|html|svg|json|txt)$/.test(file)) continue
        const source = readFileSync(file)
        if (source.length < 1024) continue
        writeFileSync(`${file}.gz`, gzipSync(source, { level: 9 }))
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), precompress()],
  build: {
    sourcemap: false,
    cssCodeSplit: true,
    // The entry is tiny; lazy pages (orders, admin) are split automatically.
    chunkSizeWarningLimit: 200,
  },
  server: {
    port: 5173,
    proxy: {
      // `npm run dev` talks to the docker-compose stack through NGINX.
      '/api': { target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8080', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
})
